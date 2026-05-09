from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .database import Database
from .logging_setup import configure_logging
from .scan_state import ScanRunStore
from .scanner import ScanCanceledError, count_supported_files, scan_library

ACTIVE_SCAN_STATUSES = {"counting", "running", "canceling", "paused"}
PAUSE_POLL_SECONDS = 0.5

log = logging.getLogger("printshelf.service")


class PrintShelfService:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        configure_logging(self.data_dir)
        self.preview_dir = self.data_dir / "previews"
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.data_dir / "printshelf.sqlite3")
        self.scan_store = ScanRunStore(self.db)
        self._scan_thread_lock = threading.Lock()
        self._scan_thread: threading.Thread | None = None
        self._scan_owner_token = uuid.uuid4().hex

    def get_root_path(self) -> str:
        return self.db.get_setting("root_path", "")

    def set_root_path(self, root_path: str) -> str:
        normalized = str(Path(root_path).expanduser().resolve()) if root_path else ""
        self.db.set_setting("root_path", normalized)
        return normalized

    def get_config(self) -> dict[str, Any]:
        return {"root_path": self.get_root_path()}

    def request_scan(self) -> dict[str, Any]:
        root_path = self.get_root_path()
        if not root_path:
            raise ValueError("Select a library folder before scanning")

        current = self.scan_store.get_state()
        if current["status"] in ACTIVE_SCAN_STATUSES and current["run_id"]:
            self.scan_store.request_restart(root_path)
            self._ensure_scan_worker()
            return self.scan_store.get_state()

        run_id = uuid.uuid4().hex
        if not self.scan_store.start_run(run_id, root_path):
            self.scan_store.request_restart(root_path)

        self._ensure_scan_worker()
        return self.scan_store.get_state()

    def cancel_scan(self) -> dict[str, Any]:
        self.scan_store.request_cancel()
        return self.scan_store.get_state()

    def pause_scan(self) -> dict[str, Any]:
        self.scan_store.request_pause()
        return self.scan_store.get_state()

    def resume_scan(self) -> dict[str, Any]:
        self.scan_store.request_resume()
        return self.scan_store.get_state()

    def get_scan_status(self) -> dict[str, Any]:
        return self.scan_store.get_state()

    def _ensure_scan_worker(self) -> None:
        with self._scan_thread_lock:
            if self._scan_thread is not None and self._scan_thread.is_alive():
                return
            self._scan_thread = threading.Thread(
                target=self._scan_worker_loop,
                name="printshelf-scan-worker",
                daemon=True,
            )
            self._scan_thread.start()

    @staticmethod
    def _progress_percent(scanned: int, total_files: int) -> float:
        if total_files <= 0:
            return 100.0
        return round((max(scanned, 0) / total_files) * 100.0, 1)

    @classmethod
    def _scan_message(
        cls, scanned: int, total_files: int, changed: int, reused: int, deleted: int
    ) -> str:
        percent = cls._progress_percent(scanned, total_files)
        return (
            f"{percent:.1f}% — {scanned}/{total_files} scanned, "
            f"{changed} changed, {reused} reused, {deleted} deleted"
        )

    def _scan_worker_loop(self) -> None:
        while True:
            state = self.scan_store.get_state()
            run_id = str(state.get("run_id") or "")
            if state.get("status") not in ACTIVE_SCAN_STATUSES or not run_id:
                return

            if not self.scan_store.claim_owner(run_id, self._scan_owner_token):
                return

            state = self.scan_store.get_state()
            if state.get("run_id") != run_id:
                continue

            root_path = str(state.get("root_path") or "")
            log.info("scan run %s starting (root=%s)", run_id, root_path)
            try:
                self._execute_scan_run(run_id=run_id, root_path=root_path)
                log.info("scan run %s finished", run_id)
            except Exception as exc:
                log.exception("scan run %s failed", run_id)
                self.scan_store.fail_run(run_id, str(exc))

            next_run_id = uuid.uuid4().hex
            next_root = self.scan_store.claim_restart(
                previous_run_id=run_id,
                new_run_id=next_run_id,
                owner_token=self._scan_owner_token,
            )
            if next_root:
                continue

            after = self.scan_store.get_state()
            if (
                str(after.get("run_id") or "") == run_id
                and after.get("status") == "canceling"
            ):
                self.scan_store.fail_run(run_id, "Scan canceled")
            return

    def _execute_scan_run(self, run_id: str, root_path: str) -> None:
        if not root_path:
            raise ValueError("Select a library folder before scanning")

        def should_cancel() -> bool:
            cancel = self.scan_store.is_cancel_requested(run_id)
            if cancel:
                self.scan_store.mark_canceling(
                    run_id, "Cancel requested. Waiting for current file to finish..."
                )
            return cancel

        def wait_if_paused() -> None:
            while True:
                state = self.scan_store.get_state()
                if state.get("run_id") != run_id:
                    return
                if not bool(state.get("pause_requested")):
                    return
                if bool(state.get("cancel_requested")):
                    return
                time.sleep(PAUSE_POLL_SECONDS)

        self.scan_store.update_progress(
            run_id,
            status="counting",
            total_files=0,
            scanned=0,
            changed=0,
            reused=0,
            deleted=0,
            progress_percent=0.0,
            message="Counting files...",
        )
        total_files = count_supported_files(
            Path(root_path),
            should_cancel=should_cancel,
            wait_if_paused=wait_if_paused,
        )

        if should_cancel():
            raise ScanCanceledError("Scan canceled")

        self.scan_store.update_progress(
            run_id,
            status="running",
            total_files=total_files,
            scanned=0,
            changed=0,
            reused=0,
            deleted=0,
            progress_percent=self._progress_percent(0, total_files),
            message=self._scan_message(0, total_files, 0, 0, 0),
        )

        def on_progress(snapshot: dict[str, Any]) -> None:
            total = int(snapshot.get("total_files", total_files))
            scanned = int(snapshot.get("scanned", 0))
            changed = int(snapshot.get("changed", 0))
            reused = int(snapshot.get("reused", 0))
            deleted = int(snapshot.get("deleted", 0))
            self.scan_store.update_progress(
                run_id,
                status="running",
                total_files=total,
                scanned=scanned,
                changed=changed,
                reused=reused,
                deleted=deleted,
                progress_percent=self._progress_percent(scanned, total),
                message=self._scan_message(scanned, total, changed, reused, deleted),
            )

        try:
            result = scan_library(
                Path(root_path),
                self.preview_dir,
                self.db,
                total_files=total_files,
                progress_callback=on_progress,
                should_cancel=should_cancel,
                wait_if_paused=wait_if_paused,
            )
        except ScanCanceledError:
            self.scan_store.mark_canceling(
                run_id, "Cancel requested. Waiting for current file to finish..."
            )
            return

        if should_cancel():
            raise ScanCanceledError("Scan canceled")

        completed_message = (
            f"Scan complete. {result['scanned']} files found, {result['changed']} "
            f"updated, {result['reused']} reused, {result['deleted']} removed."
        )
        self.scan_store.complete_run(run_id, result, completed_message)

    def _serialize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        preview_rel_path = item.get("preview_rel_path")
        preview_url = f"/previews/{preview_rel_path}" if preview_rel_path else None

        try:
            user_meta = json.loads(item.get("meta_json") or "{}")
        except json.JSONDecodeError:
            log.warning(
                "item %s has invalid meta_json; coercing to empty dict",
                item.get("id"),
            )
            user_meta = {}

        try:
            indexed_meta = json.loads(item.get("indexed_meta_json") or "{}")
        except json.JSONDecodeError:
            log.warning(
                "item %s has invalid indexed_meta_json; coercing to empty dict",
                item.get("id"),
            )
            indexed_meta = {}

        return {
            "id": item["id"],
            "path": item["path"],
            "root_path": item["root_path"],
            "relative_path": item["relative_path"],
            "filename": item["filename"],
            "file_type": item["file_type"],
            "size_bytes": item["size_bytes"],
            "modified_at": item["modified_at"],
            "preview_url": preview_url,
            "preview_source": item.get("preview_source"),
            "description": item.get("description", ""),
            "tags": item.get("tags", []),
            "meta": user_meta,
            "indexed_meta": indexed_meta,
        }

    def list_items(
        self,
        query: str = "",
        file_type: str = "",
        tag: str = "",
        sort: str = "date_added_desc",
    ) -> list[dict[str, Any]]:
        rows = self.db.list_items(query=query, file_type=file_type, tag=tag, sort=sort)
        return [self._serialize_item(row) for row in rows]

    def list_tags(self, query: str = "") -> list[dict[str, Any]]:
        return self.db.list_tags(query=query)

    def rename_tag(self, tag_id: int, name: str) -> dict[str, Any] | None:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Tag name cannot be empty")
        return self.db.rename_tag(tag_id, normalized_name)

    def delete_tag(self, tag_id: int) -> bool:
        return self.db.delete_tag(tag_id)

    def bulk_update_tags(
        self, item_ids: list[int], add_tags: list[str], remove_tags: list[str]
    ) -> dict[str, Any]:
        updated_items = self.db.bulk_update_item_tags(
            item_ids=item_ids,
            add_tags=add_tags,
            remove_tags=remove_tags,
        )
        return {"updated_items": updated_items}

    def get_item(self, item_id: int) -> dict[str, Any] | None:
        row = self.db.get_item(item_id)
        return self._serialize_item(row) if row else None

    def update_item(
        self, item_id: int, description: str, tags: list[str], meta: dict[str, Any]
    ) -> dict[str, Any] | None:
        updated = self.db.update_item(
            item_id=item_id, description=description, tags=tags, meta=meta
        )
        return self._serialize_item(updated) if updated else None

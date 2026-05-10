from __future__ import annotations

import json
import os
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from pathlib import Path
from typing import Any, Callable, Iterator

from .database import Database
from .preview import generate_preview

SUPPORTED_EXTENSIONS = {".stl": "stl", ".gcode": "gcode"}


class ScanCanceledError(RuntimeError):
    pass


def _iter_supported_files(
    root_path: Path,
    should_cancel: Callable[[], bool] | None = None,
    wait_if_paused: Callable[[], None] | None = None,
) -> Iterator[tuple[Path, str]]:
    for current_root, dirnames, filenames in os.walk(root_path):
        if wait_if_paused is not None:
            wait_if_paused()
        if should_cancel is not None and should_cancel():
            raise ScanCanceledError("Scan canceled")

        dirnames[:] = [
            name
            for name in dirnames
            if name not in {".git", "__pycache__", ".venv", "node_modules"}
        ]
        current_root_path = Path(current_root)

        for filename in filenames:
            file_path = current_root_path / filename
            suffix = file_path.suffix.lower()
            if suffix not in SUPPORTED_EXTENSIONS:
                continue
            if wait_if_paused is not None:
                wait_if_paused()
            if should_cancel is not None and should_cancel():
                raise ScanCanceledError("Scan canceled")
            yield file_path, SUPPORTED_EXTENSIONS[suffix]


def count_supported_files(
    root_path: Path,
    should_cancel: Callable[[], bool] | None = None,
    wait_if_paused: Callable[[], None] | None = None,
) -> int:
    count = 0
    for _file_path, _item_type in _iter_supported_files(
        root_path, should_cancel, wait_if_paused
    ):
        count += 1
    return count


def scan_library(
    root_path: Path,
    preview_dir: Path,
    db: Database,
    *,
    total_files: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    wait_if_paused: Callable[[], None] | None = None,
    scan_workers: int = 1,
) -> dict[str, Any]:
    root_path = root_path.expanduser().resolve()
    if not root_path.exists():
        raise FileNotFoundError(f"Library root does not exist: {root_path}")
    if not root_path.is_dir():
        raise NotADirectoryError(f"Library root is not a folder: {root_path}")

    if total_files is None:
        total_files = count_supported_files(root_path, should_cancel, wait_if_paused)

    discovered_paths: set[str] = set()
    counters = {"scanned": 0, "changed": 0, "reused": 0}

    def emit_progress() -> None:
        if progress_callback is not None:
            progress_callback(
                {
                    "root_path": str(root_path),
                    "total_files": int(total_files),
                    "scanned": counters["scanned"],
                    "changed": counters["changed"],
                    "reused": counters["reused"],
                    "deleted": 0,
                }
            )

    def finalize(
        file_path: Path,
        item_type: str,
        stat: os.stat_result,
        absolute_path: str,
        preview_rel_path: str | None,
        preview_source: str | None,
        indexed_meta: dict[str, Any],
        *,
        was_unchanged: bool,
    ) -> None:
        counters["scanned"] += 1
        if was_unchanged:
            counters["reused"] += 1
        else:
            counters["changed"] += 1
        discovered_paths.add(absolute_path)
        db.upsert_item(
            {
                "path": absolute_path,
                "root_path": str(root_path),
                "relative_path": str(file_path.relative_to(root_path)),
                "filename": file_path.name,
                "file_type": item_type,
                "size_bytes": int(stat.st_size),
                "modified_at": int(stat.st_mtime_ns),
                "preview_rel_path": preview_rel_path,
                "preview_source": preview_source,
                "indexed_meta": indexed_meta,
            }
        )
        emit_progress()

    def classify(
        file_path: Path,
    ) -> tuple[
        str,
        os.stat_result,
        dict[str, Any] | None,
        bool,
        str | None,
        str | None,
        dict[str, Any],
    ]:
        absolute_path = str(file_path.resolve())
        stat = file_path.stat()
        existing = db.get_item_by_path(absolute_path)
        preview_rel_path = existing["preview_rel_path"] if existing else None
        preview_source = existing["preview_source"] if existing else None
        preview_file_exists = bool(
            preview_rel_path and (preview_dir / preview_rel_path).exists()
        )
        is_unchanged = bool(
            existing
            and int(existing["modified_at"]) == int(stat.st_mtime_ns)
            and int(existing["size_bytes"]) == int(stat.st_size)
            and preview_file_exists
        )
        indexed_meta: dict[str, Any] = {}
        if is_unchanged:
            try:
                indexed_meta = json.loads(existing.get("indexed_meta_json") or "{}")
            except Exception:
                indexed_meta = {}
        return (
            absolute_path,
            stat,
            existing,
            is_unchanged,
            preview_rel_path,
            preview_source,
            indexed_meta,
        )

    if scan_workers <= 1:
        for file_path, item_type in _iter_supported_files(
            root_path, should_cancel, wait_if_paused
        ):
            if wait_if_paused is not None:
                wait_if_paused()
            if should_cancel is not None and should_cancel():
                raise ScanCanceledError("Scan canceled")

            (
                absolute_path,
                stat,
                _existing,
                is_unchanged,
                preview_rel_path,
                preview_source,
                indexed_meta,
            ) = classify(file_path)

            if is_unchanged:
                finalize(
                    file_path,
                    item_type,
                    stat,
                    absolute_path,
                    preview_rel_path,
                    preview_source,
                    indexed_meta,
                    was_unchanged=True,
                )
                continue

            preview_rel_path, preview_source, indexed_meta = generate_preview(
                file_path=file_path,
                preview_dir=preview_dir,
                modified_at=int(stat.st_mtime_ns),
            )
            finalize(
                file_path,
                item_type,
                stat,
                absolute_path,
                preview_rel_path,
                preview_source,
                indexed_meta,
                was_unchanged=False,
            )
    else:
        # ProcessPoolExecutor sidesteps the GIL for matplotlib/VTK rendering.
        # Bounded in-flight queue: don't read thousands of files ahead of the
        # workers — keeps memory pressure linear in scan_workers, not library
        # size.
        max_in_flight = max(2, scan_workers * 2)
        in_flight: dict[Future, tuple[Path, str, os.stat_result, str]] = {}
        pool = ProcessPoolExecutor(max_workers=scan_workers)

        def drain_one() -> None:
            done, _ = wait(list(in_flight.keys()), return_when=FIRST_COMPLETED)
            for fut in done:
                fp, it, st, abs_path = in_flight.pop(fut)
                # generate_preview catches per-file errors internally and
                # returns a placeholder result, so a raise here is unexpected.
                rel, src, meta = fut.result()
                finalize(
                    fp,
                    it,
                    st,
                    abs_path,
                    rel,
                    src,
                    meta,
                    was_unchanged=False,
                )

        try:
            for file_path, item_type in _iter_supported_files(
                root_path, should_cancel, wait_if_paused
            ):
                if wait_if_paused is not None:
                    wait_if_paused()
                if should_cancel is not None and should_cancel():
                    raise ScanCanceledError("Scan canceled")

                (
                    absolute_path,
                    stat,
                    _existing,
                    is_unchanged,
                    preview_rel_path,
                    preview_source,
                    indexed_meta,
                ) = classify(file_path)

                if is_unchanged:
                    finalize(
                        file_path,
                        item_type,
                        stat,
                        absolute_path,
                        preview_rel_path,
                        preview_source,
                        indexed_meta,
                        was_unchanged=True,
                    )
                    continue

                while len(in_flight) >= max_in_flight:
                    drain_one()
                    if wait_if_paused is not None:
                        wait_if_paused()
                    if should_cancel is not None and should_cancel():
                        raise ScanCanceledError("Scan canceled")

                fut = pool.submit(
                    generate_preview,
                    file_path,
                    preview_dir,
                    int(stat.st_mtime_ns),
                )
                in_flight[fut] = (file_path, item_type, stat, absolute_path)

            while in_flight:
                drain_one()
        except ScanCanceledError:
            # Drop pending tasks and let in-flight workers finish naturally —
            # consistent with the existing "Cancel requested. Waiting for
            # current file to finish..." UX.
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        except BaseException:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            pool.shutdown(wait=True)

    if wait_if_paused is not None:
        wait_if_paused()
    if should_cancel is not None and should_cancel():
        raise ScanCanceledError("Scan canceled")
    existing_paths = set(db.list_paths_for_root(str(root_path)))
    missing = sorted(existing_paths - discovered_paths)
    deleted = db.delete_paths(missing)

    result = {
        "root_path": str(root_path),
        "total_files": int(total_files),
        "scanned": counters["scanned"],
        "changed": counters["changed"],
        "reused": counters["reused"],
        "deleted": deleted,
    }
    if progress_callback is not None:
        progress_callback(result)
    return result

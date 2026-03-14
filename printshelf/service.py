from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .database import Database
from .scanner import scan_library


class PrintShelfService:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.preview_dir = self.data_dir / "previews"
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.data_dir / "printshelf.sqlite3")

    def get_root_path(self) -> str:
        return self.db.get_setting("root_path", "")

    def set_root_path(self, root_path: str) -> str:
        normalized = str(Path(root_path).expanduser().resolve()) if root_path else ""
        self.db.set_setting("root_path", normalized)
        return normalized

    def get_config(self) -> dict[str, Any]:
        return {"root_path": self.get_root_path()}

    def scan(self) -> dict[str, Any]:
        root_path = self.get_root_path()
        if not root_path:
            raise ValueError("Select a library folder before scanning")
        return scan_library(Path(root_path), self.preview_dir, self.db)

    def _serialize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        preview_rel_path = item.get("preview_rel_path")
        preview_url = f"/previews/{preview_rel_path}" if preview_rel_path else None

        try:
            user_meta = json.loads(item.get("meta_json") or "{}")
        except Exception:
            user_meta = {}

        try:
            indexed_meta = json.loads(item.get("indexed_meta_json") or "{}")
        except Exception:
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
        self, query: str = "", file_type: str = "", tag: str = ""
    ) -> list[dict[str, Any]]:
        rows = self.db.list_items(query=query, file_type=file_type, tag=tag)
        return [self._serialize_item(row) for row in rows]

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

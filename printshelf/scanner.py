from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .database import Database
from .preview import generate_preview

SUPPORTED_EXTENSIONS = {".stl": "stl", ".gcode": "gcode"}


def scan_library(root_path: Path, preview_dir: Path, db: Database) -> dict[str, Any]:
    root_path = root_path.expanduser().resolve()
    if not root_path.exists():
        raise FileNotFoundError(f"Library root does not exist: {root_path}")
    if not root_path.is_dir():
        raise NotADirectoryError(f"Library root is not a folder: {root_path}")

    discovered_paths: set[str] = set()
    scanned = 0
    changed = 0
    reused = 0

    for current_root, dirnames, filenames in os.walk(root_path):
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

            scanned += 1
            absolute_path = str(file_path.resolve())
            discovered_paths.add(absolute_path)

            stat = file_path.stat()
            item_type = SUPPORTED_EXTENSIONS[suffix]
            existing = db.get_item_by_path(absolute_path)
            preview_rel_path = existing["preview_rel_path"] if existing else None
            preview_source = existing["preview_source"] if existing else None
            indexed_meta: dict[str, Any] = {}

            preview_file_exists = False
            if preview_rel_path:
                preview_file_exists = (preview_dir / preview_rel_path).exists()

            is_unchanged = bool(
                existing
                and int(existing["modified_at"]) == int(stat.st_mtime_ns)
                and int(existing["size_bytes"]) == int(stat.st_size)
                and preview_file_exists
            )

            if is_unchanged:
                reused += 1
                try:
                    import json

                    indexed_meta = json.loads(existing.get("indexed_meta_json") or "{}")
                except Exception:
                    indexed_meta = {}
            else:
                changed += 1
                preview_rel_path, preview_source, indexed_meta = generate_preview(
                    file_path=file_path,
                    preview_dir=preview_dir,
                    modified_at=int(stat.st_mtime_ns),
                )

            payload = {
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
            db.upsert_item(payload)

    existing_paths = set(db.list_paths_for_root(str(root_path)))
    missing = sorted(existing_paths - discovered_paths)
    deleted = db.delete_paths(missing)

    return {
        "root_path": str(root_path),
        "scanned": scanned,
        "changed": changed,
        "reused": reused,
        "deleted": deleted,
    }

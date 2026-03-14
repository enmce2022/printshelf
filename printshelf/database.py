from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE,
                    root_path TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    file_type TEXT NOT NULL CHECK(file_type IN ('stl', 'gcode')),
                    size_bytes INTEGER NOT NULL,
                    modified_at INTEGER NOT NULL,
                    preview_rel_path TEXT,
                    preview_source TEXT,
                    description TEXT NOT NULL DEFAULT '',
                    meta_json TEXT NOT NULL DEFAULT '{}',
                    indexed_meta_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE
                );

                CREATE TABLE IF NOT EXISTS item_tags (
                    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    PRIMARY KEY (item_id, tag_id)
                );

                CREATE INDEX IF NOT EXISTS idx_items_type ON items(file_type);
                CREATE INDEX IF NOT EXISTS idx_items_filename ON items(filename);
                CREATE INDEX IF NOT EXISTS idx_items_root_path ON items(root_path);
                CREATE INDEX IF NOT EXISTS idx_items_relative_path ON items(relative_path);
                CREATE INDEX IF NOT EXISTS idx_item_tags_item_id ON item_tags(item_id);

                CREATE TABLE IF NOT EXISTS scan_state (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    status TEXT NOT NULL DEFAULT 'idle',
                    run_id TEXT NOT NULL DEFAULT '',
                    owner_token TEXT NOT NULL DEFAULT '',
                    root_path TEXT NOT NULL DEFAULT '',
                    total_files INTEGER NOT NULL DEFAULT 0,
                    scanned INTEGER NOT NULL DEFAULT 0,
                    changed INTEGER NOT NULL DEFAULT 0,
                    reused INTEGER NOT NULL DEFAULT 0,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    progress_percent REAL NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    restart_requested INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """)
            conn.execute(
                "INSERT INTO scan_state(id) VALUES (1) ON CONFLICT(id) DO NOTHING"
            )

    def _coerce_scan_state(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["cancel_requested"] = bool(payload.get("cancel_requested"))
        payload["restart_requested"] = bool(payload.get("restart_requested"))
        return payload

    def get_scan_state(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM scan_state WHERE id = 1").fetchone()
            if row is None:
                raise RuntimeError("scan_state row is missing")
            return self._coerce_scan_state(row)

    def start_scan_run(self, run_id: str, root_path: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET
                    status = 'counting',
                    run_id = ?,
                    owner_token = '',
                    root_path = ?,
                    total_files = 0,
                    scanned = 0,
                    changed = 0,
                    reused = 0,
                    deleted = 0,
                    progress_percent = 0,
                    message = 'Counting files...',
                    error = '',
                    cancel_requested = 0,
                    restart_requested = 0,
                    started_at = CURRENT_TIMESTAMP,
                    finished_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                  AND status IN ('idle', 'completed', 'failed')
                """,
                (run_id, root_path),
            )
            return cursor.rowcount > 0

    def request_scan_restart(self, root_path: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET
                    status = 'canceling',
                    root_path = ?,
                    cancel_requested = 1,
                    restart_requested = 1,
                    message = 'Restart requested. Waiting for current file to finish...',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                  AND status IN ('counting', 'running', 'canceling')
                """,
                (root_path,),
            )
            return cursor.rowcount > 0

    def claim_scan_owner(self, run_id: str, owner_token: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET owner_token = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                  AND run_id = ?
                  AND (owner_token = '' OR owner_token = ?)
                """,
                (owner_token, run_id, owner_token),
            )
            return cursor.rowcount > 0

    def is_scan_cancel_requested(self, run_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT run_id, cancel_requested FROM scan_state WHERE id = 1"
            ).fetchone()
            if row is None:
                return False
            return str(row["run_id"]) == run_id and bool(row["cancel_requested"])

    def update_scan_progress(
        self,
        run_id: str,
        *,
        status: str,
        total_files: int,
        scanned: int,
        changed: int,
        reused: int,
        deleted: int,
        progress_percent: float,
        message: str,
    ) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET
                    status = ?,
                    total_files = ?,
                    scanned = ?,
                    changed = ?,
                    reused = ?,
                    deleted = ?,
                    progress_percent = ?,
                    message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1 AND run_id = ?
                """,
                (
                    status,
                    int(total_files),
                    int(scanned),
                    int(changed),
                    int(reused),
                    int(deleted),
                    float(progress_percent),
                    message,
                    run_id,
                ),
            )
            return cursor.rowcount > 0

    def mark_scan_canceling(self, run_id: str, message: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET status = 'canceling', message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = 1 AND run_id = ?
                """,
                (message, run_id),
            )
            return cursor.rowcount > 0

    def complete_scan_run(
        self, run_id: str, result: dict[str, Any], message: str
    ) -> bool:
        total_files = int(result.get("total_files", result.get("scanned", 0)))
        scanned = int(result.get("scanned", 0))
        changed = int(result.get("changed", 0))
        reused = int(result.get("reused", 0))
        deleted = int(result.get("deleted", 0))
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET
                    status = 'completed',
                    total_files = ?,
                    scanned = ?,
                    changed = ?,
                    reused = ?,
                    deleted = ?,
                    progress_percent = ?,
                    message = ?,
                    error = '',
                    cancel_requested = 0,
                    restart_requested = 0,
                    finished_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1 AND run_id = ? AND cancel_requested = 0
                """,
                (
                    total_files,
                    scanned,
                    changed,
                    reused,
                    deleted,
                    100.0 if total_files >= 0 else 0.0,
                    message,
                    run_id,
                ),
            )
            return cursor.rowcount > 0

    def fail_scan_run(self, run_id: str, error_message: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET
                    status = 'failed',
                    error = ?,
                    message = 'Scan failed.',
                    cancel_requested = 0,
                    restart_requested = 0,
                    finished_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1 AND run_id = ?
                """,
                (error_message, run_id),
            )
            return cursor.rowcount > 0

    def claim_restart_run(
        self, previous_run_id: str, new_run_id: str, owner_token: str
    ) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT root_path
                FROM scan_state
                WHERE id = 1 AND run_id = ? AND restart_requested = 1
                """,
                (previous_run_id,),
            ).fetchone()
            if row is None:
                return None

            root_path = str(row["root_path"] or "")
            cursor = conn.execute(
                """
                UPDATE scan_state
                SET
                    status = 'counting',
                    run_id = ?,
                    owner_token = ?,
                    total_files = 0,
                    scanned = 0,
                    changed = 0,
                    reused = 0,
                    deleted = 0,
                    progress_percent = 0,
                    message = 'Counting files...',
                    error = '',
                    cancel_requested = 0,
                    restart_requested = 0,
                    started_at = CURRENT_TIMESTAMP,
                    finished_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                  AND run_id = ?
                  AND restart_requested = 1
                """,
                (new_run_id, owner_token, previous_run_id),
            )
            if cursor.rowcount <= 0:
                return None
            return root_path

    def get_setting(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings(key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_item_by_path(self, path: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM items WHERE path = ?",
                (path,),
            ).fetchone()
            return dict(row) if row else None

    def _fetch_tags_for_item(self, conn: sqlite3.Connection, item_id: int) -> list[str]:
        rows = conn.execute(
            """
            SELECT t.name
            FROM tags t
            JOIN item_tags it ON it.tag_id = t.id
            WHERE it.item_id = ?
            ORDER BY t.name COLLATE NOCASE
            """,
            (item_id,),
        ).fetchall()
        return [row["name"] for row in rows]

    def upsert_item(self, payload: dict[str, Any]) -> int:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO items (
                    path, root_path, relative_path, filename, file_type,
                    size_bytes, modified_at, preview_rel_path, preview_source,
                    description, meta_json, indexed_meta_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    root_path = excluded.root_path,
                    relative_path = excluded.relative_path,
                    filename = excluded.filename,
                    file_type = excluded.file_type,
                    size_bytes = excluded.size_bytes,
                    modified_at = excluded.modified_at,
                    preview_rel_path = excluded.preview_rel_path,
                    preview_source = excluded.preview_source,
                    description = COALESCE(items.description, ''),
                    meta_json = COALESCE(items.meta_json, '{}'),
                    indexed_meta_json = excluded.indexed_meta_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    payload["path"],
                    payload["root_path"],
                    payload["relative_path"],
                    payload["filename"],
                    payload["file_type"],
                    payload["size_bytes"],
                    payload["modified_at"],
                    payload.get("preview_rel_path"),
                    payload.get("preview_source"),
                    payload.get("description", ""),
                    json.dumps(payload.get("meta", {}), ensure_ascii=False),
                    json.dumps(payload.get("indexed_meta", {}), ensure_ascii=False),
                ),
            )
            row = conn.execute(
                "SELECT id FROM items WHERE path = ?",
                (payload["path"],),
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to upsert item")
            return int(row["id"])

    def set_tags(self, item_id: int, tags: Iterable[str]) -> None:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in tags:
            value = raw.strip()
            if not value:
                continue
            lowered = value.casefold()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append(value)

        with self._connect() as conn:
            conn.execute("DELETE FROM item_tags WHERE item_id = ?", (item_id,))
            for tag in normalized:
                conn.execute(
                    "INSERT INTO tags(name) VALUES (?) ON CONFLICT(name) DO NOTHING",
                    (tag,),
                )
                row = conn.execute(
                    "SELECT id FROM tags WHERE name = ? COLLATE NOCASE",
                    (tag,),
                ).fetchone()
                if row:
                    conn.execute(
                        "INSERT OR IGNORE INTO item_tags(item_id, tag_id) VALUES (?, ?)",
                        (item_id, int(row["id"])),
                    )
            conn.execute("""
                DELETE FROM tags
                WHERE id NOT IN (SELECT DISTINCT tag_id FROM item_tags)
                """)

    def list_items(
        self,
        query: str = "",
        file_type: str = "",
        tag: str = "",
        sort: str = "date_added_desc",
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        order_by_map = {
            "date_added_desc": (
                "i.created_at DESC, i.filename COLLATE NOCASE ASC, i.id ASC"
            ),
            "date_added_asc": (
                "i.created_at ASC, i.filename COLLATE NOCASE ASC, i.id ASC"
            ),
            "name_asc": "i.filename COLLATE NOCASE ASC, i.created_at DESC, i.id ASC",
            "name_desc": "i.filename COLLATE NOCASE DESC, i.created_at DESC, i.id ASC",
        }
        order_by = order_by_map.get(sort, order_by_map["date_added_desc"])

        if query:
            like = f"%{query.strip()}%"
            where.append("""
                (
                    i.filename LIKE ? COLLATE NOCASE OR
                    i.relative_path LIKE ? COLLATE NOCASE OR
                    i.description LIKE ? COLLATE NOCASE OR
                    i.meta_json LIKE ? COLLATE NOCASE OR
                    EXISTS (
                        SELECT 1
                        FROM item_tags it2
                        JOIN tags t2 ON t2.id = it2.tag_id
                        WHERE it2.item_id = i.id
                          AND t2.name LIKE ? COLLATE NOCASE
                    )
                )
                """)
            params.extend([like, like, like, like, like])

        if file_type:
            where.append("i.file_type = ?")
            params.append(file_type)

        if tag:
            where.append("""
                EXISTS (
                    SELECT 1
                    FROM item_tags it3
                    JOIN tags t3 ON t3.id = it3.tag_id
                    WHERE it3.item_id = i.id
                      AND t3.name = ? COLLATE NOCASE
                )
                """)
            params.append(tag)

        sql = """
            SELECT i.*
            FROM items i
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {order_by}"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["tags"] = self._fetch_tags_for_item(conn, int(item["id"]))
                result.append(item)
            return result

    def get_item(self, item_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            item["tags"] = self._fetch_tags_for_item(conn, item_id)
            return item

    def update_item(
        self, item_id: int, description: str, meta: dict[str, Any], tags: list[str]
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE items
                SET description = ?, meta_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (description, json.dumps(meta, ensure_ascii=False), item_id),
            )
        self.set_tags(item_id, tags)
        return self.get_item(item_id)

    def list_paths_for_root(self, root_path: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT path FROM items WHERE root_path = ?",
                (root_path,),
            ).fetchall()
            return [row["path"] for row in rows]

    def delete_paths(self, paths: list[str]) -> int:
        if not paths:
            return 0
        deleted = 0
        with self._connect() as conn:
            for chunk_start in range(0, len(paths), 500):
                chunk = paths[chunk_start : chunk_start + 500]
                placeholders = ",".join("?" for _ in chunk)
                cursor = conn.execute(
                    f"DELETE FROM items WHERE path IN ({placeholders})",
                    chunk,
                )
                deleted += cursor.rowcount
            conn.execute("""
                DELETE FROM tags
                WHERE id NOT IN (SELECT DISTINCT tag_id FROM item_tags)
                """)
        return deleted

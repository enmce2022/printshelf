from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

log = logging.getLogger("printshelf.database")

# Schema baseline. Idempotent — safe to run on existing or fresh databases.
# After this baseline, additive changes go in `_MIGRATIONS` keyed by version.
_BASELINE_SCHEMA = """
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
CREATE INDEX IF NOT EXISTS idx_item_tags_tag_id ON item_tags(tag_id);

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

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# Append future schema changes here as `(version, sql)` tuples. The runner
# applies each migration whose version is not yet recorded, in ascending order.
_MIGRATIONS: list[tuple[int, str]] = []


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

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection that commits on clean exit and rolls back on error."""
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_BASELINE_SCHEMA)
            conn.execute(
                "INSERT INTO scan_state(id) VALUES (1) ON CONFLICT(id) DO NOTHING"
            )
        self._run_migrations()

    def _run_migrations(self) -> None:
        if not _MIGRATIONS:
            return
        with self.transaction() as conn:
            applied_rows = conn.execute(
                "SELECT version FROM schema_migrations"
            ).fetchall()
            applied = {int(row["version"]) for row in applied_rows}
            for version, sql in sorted(_MIGRATIONS, key=lambda m: m[0]):
                if version in applied:
                    continue
                log.info("applying schema migration %s", version)
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations(version) VALUES (?)",
                    (version,),
                )

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

    @staticmethod
    def _split_concatenated_tags(value: Any) -> list[str]:
        if not value:
            return []
        return [part for part in str(value).split("\x00") if part]

    @staticmethod
    def _normalize_tags(tags: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in tags:
            value = str(raw).strip()
            if not value:
                continue
            lowered = value.casefold()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append(value)
        return normalized

    def _fetch_tag_with_count(
        self, conn: sqlite3.Connection, tag_id: int
    ) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT
                t.id,
                t.name,
                COUNT(DISTINCT it.item_id) AS item_count
            FROM tags t
            LEFT JOIN item_tags it ON it.tag_id = t.id
            WHERE t.id = ?
            GROUP BY t.id, t.name
            """,
            (tag_id,),
        ).fetchone()
        return dict(row) if row else None

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

    def _set_tags_tx(
        self, conn: sqlite3.Connection, item_id: int, tags: Iterable[str]
    ) -> None:
        normalized = self._normalize_tags(tags)
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

    def set_tags(self, item_id: int, tags: Iterable[str]) -> None:
        with self.transaction() as conn:
            self._set_tags_tx(conn, item_id, tags)

    def list_tags(self, query: str = "") -> list[dict[str, Any]]:
        where = ""
        params: list[Any] = []
        trimmed = query.strip()
        if trimmed:
            where = "WHERE t.name LIKE ? COLLATE NOCASE"
            params.append(f"%{trimmed}%")

        sql = f"""
            SELECT
                t.id,
                t.name,
                COUNT(DISTINCT it.item_id) AS item_count
            FROM tags t
            LEFT JOIN item_tags it ON it.tag_id = t.id
            {where}
            GROUP BY t.id, t.name
            ORDER BY t.name COLLATE NOCASE ASC
        """
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def rename_tag(self, tag_id: int, new_name: str) -> dict[str, Any] | None:
        normalized_name = str(new_name).strip()
        if not normalized_name:
            raise ValueError("Tag name cannot be empty")

        with self.transaction() as conn:
            source = conn.execute(
                "SELECT id FROM tags WHERE id = ?",
                (tag_id,),
            ).fetchone()
            if source is None:
                return None

            existing = conn.execute(
                "SELECT id FROM tags WHERE name = ? COLLATE NOCASE",
                (normalized_name,),
            ).fetchone()
            if existing is not None and int(existing["id"]) != tag_id:
                target_id = int(existing["id"])
                conn.execute(
                    """
                    INSERT OR IGNORE INTO item_tags(item_id, tag_id)
                    SELECT item_id, ?
                    FROM item_tags
                    WHERE tag_id = ?
                    """,
                    (target_id, tag_id),
                )
                conn.execute("DELETE FROM item_tags WHERE tag_id = ?", (tag_id,))
                conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
                return self._fetch_tag_with_count(conn, target_id)

            conn.execute(
                "UPDATE tags SET name = ? WHERE id = ?",
                (normalized_name, tag_id),
            )
            return self._fetch_tag_with_count(conn, tag_id)

    def delete_tag(self, tag_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
            return cursor.rowcount > 0

    def bulk_update_item_tags(
        self, item_ids: list[int], add_tags: Iterable[str], remove_tags: Iterable[str]
    ) -> int:
        seen_item_ids: set[int] = set()
        normalized_item_ids: list[int] = []
        for raw in item_ids:
            try:
                item_id = int(raw)
            except (TypeError, ValueError):
                continue
            if item_id <= 0 or item_id in seen_item_ids:
                continue
            seen_item_ids.add(item_id)
            normalized_item_ids.append(item_id)

        if not normalized_item_ids:
            return 0

        normalized_add = self._normalize_tags(add_tags)
        add_keys = {tag.casefold() for tag in normalized_add}
        normalized_remove = [
            tag
            for tag in self._normalize_tags(remove_tags)
            if tag.casefold() not in add_keys
        ]

        with self.transaction() as conn:
            item_placeholders = ",".join("?" for _ in normalized_item_ids)
            existing_rows = conn.execute(
                f"SELECT id FROM items WHERE id IN ({item_placeholders})",
                normalized_item_ids,
            ).fetchall()
            existing_item_ids = [int(row["id"]) for row in existing_rows]
            if not existing_item_ids:
                return 0

            add_tag_ids: list[int] = []
            for tag in normalized_add:
                conn.execute(
                    "INSERT INTO tags(name) VALUES (?) ON CONFLICT(name) DO NOTHING",
                    (tag,),
                )
                row = conn.execute(
                    "SELECT id FROM tags WHERE name = ? COLLATE NOCASE",
                    (tag,),
                ).fetchone()
                if row is not None:
                    add_tag_ids.append(int(row["id"]))

            remove_tag_ids: list[int] = []
            for tag in normalized_remove:
                row = conn.execute(
                    "SELECT id FROM tags WHERE name = ? COLLATE NOCASE",
                    (tag,),
                ).fetchone()
                if row is not None:
                    remove_tag_ids.append(int(row["id"]))

            if remove_tag_ids:
                remove_placeholders = ",".join("?" for _ in remove_tag_ids)
                for item_id in existing_item_ids:
                    conn.execute(
                        f"DELETE FROM item_tags WHERE item_id = ? AND tag_id IN ({remove_placeholders})",
                        [item_id, *remove_tag_ids],
                    )

            if add_tag_ids:
                for item_id in existing_item_ids:
                    conn.executemany(
                        "INSERT OR IGNORE INTO item_tags(item_id, tag_id) VALUES (?, ?)",
                        [(item_id, tag_id) for tag_id in add_tag_ids],
                    )

            conn.execute("""
                DELETE FROM tags
                WHERE id NOT IN (SELECT DISTINCT tag_id FROM item_tags)
                """)
            return len(existing_item_ids)

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

        # Aggregate tags in a single query (was N+1). Tag names are joined
        # with NUL ('\x00') because that byte cannot appear in a tag (names
        # come from `_normalize_tags` which strips whitespace; NUL is safe
        # against legitimate values like commas in tag text).
        sql = """
            SELECT
                i.*,
                (
                    SELECT GROUP_CONCAT(tn.name, char(0))
                    FROM (
                        SELECT t.name
                        FROM tags t
                        JOIN item_tags it ON it.tag_id = t.id
                        WHERE it.item_id = i.id
                        ORDER BY t.name COLLATE NOCASE
                    ) tn
                ) AS tag_names
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
                item["tags"] = self._split_concatenated_tags(item.pop("tag_names", ""))
                result.append(item)
            return result

    def get_item(self, item_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    i.*,
                    (
                        SELECT GROUP_CONCAT(tn.name, char(0))
                        FROM (
                            SELECT t.name
                            FROM tags t
                            JOIN item_tags it ON it.tag_id = t.id
                            WHERE it.item_id = i.id
                            ORDER BY t.name COLLATE NOCASE
                        ) tn
                    ) AS tag_names
                FROM items i
                WHERE i.id = ?
                """,
                (item_id,),
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            item["tags"] = self._split_concatenated_tags(item.pop("tag_names", ""))
            return item

    def update_item(
        self, item_id: int, description: str, tags: list[str], meta: dict[str, Any]
    ) -> dict[str, Any] | None:
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE items
                SET description = ?, meta_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (description, json.dumps(meta, ensure_ascii=False), item_id),
            )
            self._set_tags_tx(conn, item_id, tags)
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

from __future__ import annotations

import gc
from pathlib import Path
from typing import Any, Iterator

import pytest

from spoolhouse.database import Database
from spoolhouse.scan_state import ScanRunStore


@pytest.fixture
def tmp_db(tmp_path: Path) -> Iterator[Database]:
    """A fresh Database backed by a per-test tmp file.

    `:memory:` is unsuitable: Database opens a new connection per operation,
    and an in-memory db is per-connection. A tmp file gives us isolated
    state that survives across calls within one test.
    """
    db = Database(tmp_path / "spoolhouse.sqlite3")
    yield db
    # Encourage prompt SQLite handle close on Windows where the tmp dir
    # cleanup will otherwise hit "file in use".
    del db
    gc.collect()


@pytest.fixture
def scan_store(tmp_db: Database) -> ScanRunStore:
    return ScanRunStore(tmp_db)


def _base_item_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "path": "/library/file.stl",
        "root_path": "/library",
        "relative_path": "file.stl",
        "filename": "file.stl",
        "file_type": "stl",
        "size_bytes": 1024,
        "modified_at": 1_700_000_000,
        "preview_rel_path": None,
        "preview_source": None,
        "description": "",
        "meta": {},
        "indexed_meta": {},
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def make_item(tmp_db: Database):
    """Factory inserting an item with sensible defaults; returns its id."""

    def _make(**overrides: Any) -> int:
        return tmp_db.upsert_item(_base_item_payload(**overrides))

    return _make

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from printshelf.database import Database
from printshelf.scanner import scan_library


def _make_png_bytes(width: int = 32, height: int = 32) -> bytes:
    img = Image.new("RGBA", (width, height), (0, 128, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _embed_thumbnail_block(png_bytes: bytes, width: int, height: int) -> str:
    encoded = base64.b64encode(png_bytes).decode("ascii")
    chunk = 78
    lines = [f"; thumbnail begin {width}x{height} {len(encoded)}"]
    for i in range(0, len(encoded), chunk):
        lines.append(f"; {encoded[i : i + chunk]}")
    lines.append("; thumbnail end")
    return "\n".join(lines) + "\n"


def _populate_library(root: Path, count: int = 4) -> None:
    # Embedded-thumbnail g-code files: hits the fast path inside workers,
    # which keeps the test under a few seconds even with pool spawn cost.
    png = _make_png_bytes(32, 32)
    thumb_block = _embed_thumbnail_block(png, 32, 32)
    for i in range(count):
        (root / f"part_{i}.gcode").write_text(thumb_block, encoding="utf-8")


def _scan_into(db_path: Path, root: Path, preview_dir: Path, workers: int) -> dict:
    db = Database(db_path)
    try:
        return scan_library(
            root,
            preview_dir,
            db,
            scan_workers=workers,
        )
    finally:
        del db


def test_parallel_scan_matches_serial(tmp_path: Path) -> None:
    """scan_workers=N must produce the same DB shape as scan_workers=1."""
    library = tmp_path / "library"
    library.mkdir()
    _populate_library(library, count=4)

    serial_db = tmp_path / "serial.sqlite3"
    serial_previews = tmp_path / "serial_previews"
    serial_result = _scan_into(serial_db, library, serial_previews, workers=1)

    parallel_db = tmp_path / "parallel.sqlite3"
    parallel_previews = tmp_path / "parallel_previews"
    parallel_result = _scan_into(parallel_db, library, parallel_previews, workers=2)

    assert serial_result["scanned"] == parallel_result["scanned"] == 4
    assert serial_result["changed"] == parallel_result["changed"] == 4
    assert serial_result["reused"] == parallel_result["reused"] == 0

    serial_paths = sorted(
        Database(serial_db).list_paths_for_root(str(library.resolve()))
    )
    parallel_paths = sorted(
        Database(parallel_db).list_paths_for_root(str(library.resolve()))
    )
    assert serial_paths == parallel_paths
    assert len(serial_paths) == 4

    # Every preview file referenced by the DB must actually exist on disk.
    for db_path, preview_root in [
        (serial_db, serial_previews),
        (parallel_db, parallel_previews),
    ]:
        db = Database(db_path)
        for absolute in db.list_paths_for_root(str(library.resolve())):
            row = db.get_item_by_path(absolute)
            assert row is not None
            assert row["preview_rel_path"]
            assert (preview_root / row["preview_rel_path"]).exists()


def test_parallel_scan_reuses_unchanged_previews(tmp_path: Path) -> None:
    """Second scan_workers=N run must mark all files as reused."""
    library = tmp_path / "library"
    library.mkdir()
    _populate_library(library, count=3)

    db_path = tmp_path / "scan.sqlite3"
    preview_dir = tmp_path / "previews"

    first = _scan_into(db_path, library, preview_dir, workers=2)
    assert first["changed"] == 3
    assert first["reused"] == 0

    second = _scan_into(db_path, library, preview_dir, workers=2)
    assert second["changed"] == 0
    assert second["reused"] == 3
    assert second["scanned"] == 3


def test_parallel_scan_detects_deletions(tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()
    _populate_library(library, count=3)

    db_path = tmp_path / "scan.sqlite3"
    preview_dir = tmp_path / "previews"

    _scan_into(db_path, library, preview_dir, workers=2)

    # Remove one file and rescan. The deletion sweep must catch it.
    target = next(library.glob("*.gcode"))
    target.unlink()

    result = _scan_into(db_path, library, preview_dir, workers=2)
    assert result["scanned"] == 2
    assert result["deleted"] == 1


def test_parallel_scan_cancels_cleanly(tmp_path: Path) -> None:
    """Raising ScanCanceledError mid-loop must shut the pool down without hanging."""
    from printshelf.scanner import ScanCanceledError

    library = tmp_path / "library"
    library.mkdir()
    _populate_library(library, count=8)

    db_path = tmp_path / "scan.sqlite3"
    preview_dir = tmp_path / "previews"
    db = Database(db_path)

    calls = {"n": 0}

    def should_cancel() -> bool:
        calls["n"] += 1
        # Cancel after the first cancel-check inside the file loop fires
        # (count=1 happens during initial counting; cancel on later checks).
        return calls["n"] > 3

    try:
        with pytest.raises(ScanCanceledError):
            scan_library(
                library,
                preview_dir,
                db,
                should_cancel=should_cancel,
                scan_workers=2,
            )
    finally:
        del db

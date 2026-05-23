from __future__ import annotations

import pytest

from printshelf.database import _derive_group_path


@pytest.mark.parametrize(
    "relative_path, expected",
    [
        ("", ""),  # missing path → root bucket
        ("file.stl", ""),  # loose file in library root
        ("folder/file.stl", "folder"),
        ("a/b/c/file.gcode", "a/b/c"),
        ("a\\b\\file.stl", "a/b"),  # Windows separators normalized
        ("a/b\\c/file.stl", "a/b/c"),  # mixed separators
        ("with spaces/file 1.stl", "with spaces"),
    ],
)
def test_derive_group_path(relative_path: str, expected: str) -> None:
    assert _derive_group_path(relative_path) == expected

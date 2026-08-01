from __future__ import annotations

import json

import pytest

from spoolhouse.database import (
    DEFAULT_DIRS_TO_IGNORE,
    SETTING_DIRS_TO_IGNORE_WHEN_GROUP,
    Database,
    _compile_ignore_patterns,
    _derive_group_path,
)


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
def test_derive_group_path_no_ignore(relative_path: str, expected: str) -> None:
    assert _derive_group_path(relative_path) == expected


def _files_matchers() -> list:
    return _compile_ignore_patterns(["files"])


@pytest.mark.parametrize(
    "relative_path, expected",
    [
        # Thingiverse-style wrapper: drop the literal "files" segment.
        ("category/project/files/x.stl", "category/project"),
        ("project/files/x.stl", "project"),
        # Case-insensitive match.
        ("project/FILES/x.stl", "project"),
        ("project/Files/x.stl", "project"),
        # Loose file inside a top-level "files" dir collapses to root.
        ("files/x.stl", ""),
        # Folder that merely contains "files" in its name is untouched.
        ("category/my_files/x.stl", "category/my_files"),
        # Single level only — no recursion.
        ("a/files/files/x.stl", "a/files"),
        # No parent at all.
        ("loose.stl", ""),
        ("", ""),
    ],
)
def test_derive_group_path_with_exact_ignore(relative_path: str, expected: str) -> None:
    matchers = _files_matchers()
    assert _derive_group_path(relative_path, matchers) == expected


@pytest.mark.parametrize(
    "patterns, relative_path, expected",
    [
        # Glob: match any folder ending in "_files".
        (["glob:*_files"], "project/asset_files/x.stl", "project"),
        (["glob:*_files"], "project/files/x.stl", "project/files"),
        # Glob is case-insensitive on both sides.
        (["glob:*_FILES"], "project/asset_files/x.stl", "project"),
        # Regex: match version-tagged folders like "v1", "v23".
        (["re:^v\\d+$"], "project/v3/x.stl", "project"),
        (["re:^v\\d+$"], "project/v3a/x.stl", "project/v3a"),
        # Regex is case-insensitive.
        (["re:^v\\d+$"], "project/V3/x.stl", "project"),
        # Multiple patterns: any match strips.
        (["files", "glob:*_tmp"], "project/scratch_tmp/x.stl", "project"),
        (["files", "glob:*_tmp"], "project/files/x.stl", "project"),
        # Invalid regex is silently dropped, others still apply.
        (["re:[invalid", "files"], "project/files/x.stl", "project"),
        # No patterns → fall through to vanilla derivation.
        ([], "project/files/x.stl", "project/files"),
    ],
)
def test_derive_group_path_with_pattern_kinds(
    patterns: list[str], relative_path: str, expected: str
) -> None:
    matchers = _compile_ignore_patterns(patterns)
    assert _derive_group_path(relative_path, matchers) == expected


def test_set_ignore_patterns_persists_and_normalizes(tmp_db: Database) -> None:
    # Fresh DB starts with the default.
    assert tmp_db.ignore_patterns == DEFAULT_DIRS_TO_IGNORE

    cleaned = tmp_db.set_ignore_patterns(
        ["  files  ", "", "files", "glob:*_temp", "re:^v\\d+$"]
    )
    # Whitespace stripped, duplicates deduped, empties dropped, order preserved.
    assert cleaned == ["files", "glob:*_temp", "re:^v\\d+$"]
    assert tmp_db.ignore_patterns == cleaned

    # Stored as JSON.
    raw = tmp_db.get_setting(SETTING_DIRS_TO_IGNORE_WHEN_GROUP, "")
    assert json.loads(raw) == cleaned

    # Reopen reflects persisted value.
    reopened = Database(tmp_db.db_path)
    assert reopened.ignore_patterns == cleaned


def test_legacy_boolean_setting_migrates(tmp_db: Database) -> None:
    # Wipe the default and plant a legacy boolean key, then re-open.
    tmp_db.set_ignore_patterns([])
    assert tmp_db.ignore_patterns == []
    tmp_db.set_setting(SETTING_DIRS_TO_IGNORE_WHEN_GROUP, "")  # force absent
    tmp_db.set_setting("group_skip_files_dir", "1")

    reopened = Database(tmp_db.db_path)
    assert reopened.ignore_patterns == ["files"]
    # Legacy key is removed once migrated.
    assert reopened.get_setting("group_skip_files_dir", "") == ""


def test_legacy_boolean_off_migrates_to_empty(tmp_db: Database) -> None:
    tmp_db.set_setting(SETTING_DIRS_TO_IGNORE_WHEN_GROUP, "")
    tmp_db.set_setting("group_skip_files_dir", "0")

    reopened = Database(tmp_db.db_path)
    assert reopened.ignore_patterns == []


def test_invalid_json_setting_falls_back_to_default(tmp_db: Database) -> None:
    tmp_db.set_setting(SETTING_DIRS_TO_IGNORE_WHEN_GROUP, "not json")
    reopened = Database(tmp_db.db_path)
    assert reopened.ignore_patterns == DEFAULT_DIRS_TO_IGNORE


def test_ignore_patterns_change_sql_aggregation(tmp_db: Database, make_item) -> None:
    make_item(
        path="/lib/proj_a/files/x.stl",
        relative_path="proj_a/files/x.stl",
        filename="x.stl",
    )
    make_item(
        path="/lib/proj_a/v3/y.stl",
        relative_path="proj_a/v3/y.stl",
        filename="y.stl",
    )
    make_item(
        path="/lib/proj_b/z.stl",
        relative_path="proj_b/z.stl",
        filename="z.stl",
    )

    # Default (["files"]): only the files/ wrapper folds in.
    counts = {g["group_path"]: g["item_count"] for g in tmp_db.list_groups()}
    assert counts == {"proj_a": 1, "proj_a/v3": 1, "proj_b": 1}

    # Add a regex to also fold version folders.
    tmp_db.set_ignore_patterns(["files", "re:^v\\d+$"])
    counts = {g["group_path"]: g["item_count"] for g in tmp_db.list_groups()}
    assert counts == {"proj_a": 2, "proj_b": 1}

    # Empty list disables stripping entirely.
    tmp_db.set_ignore_patterns([])
    counts = {g["group_path"]: g["item_count"] for g in tmp_db.list_groups()}
    assert counts == {"proj_a/files": 1, "proj_a/v3": 1, "proj_b": 1}

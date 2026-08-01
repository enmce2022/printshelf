from __future__ import annotations

import pytest

from spoolhouse.database import Database


def test_set_and_list_alias(tmp_db: Database) -> None:
    tmp_db.set_group_alias("foo/bar", "Foo & Bar")
    aliases = tmp_db.list_group_aliases()
    assert aliases == {"foo/bar": "Foo & Bar"}


def test_upsert_overwrites_display_name(tmp_db: Database) -> None:
    tmp_db.set_group_alias("foo", "First")
    tmp_db.set_group_alias("foo", "Second")
    assert tmp_db.list_group_aliases() == {"foo": "Second"}


def test_empty_display_name_rejected(tmp_db: Database) -> None:
    with pytest.raises(ValueError):
        tmp_db.set_group_alias("foo", "   ")


def test_delete_alias_returns_true_when_present(tmp_db: Database) -> None:
    tmp_db.set_group_alias("foo", "Foo")
    assert tmp_db.delete_group_alias("foo") is True
    assert tmp_db.list_group_aliases() == {}


def test_delete_alias_returns_false_when_absent(tmp_db: Database) -> None:
    assert tmp_db.delete_group_alias("never-existed") is False


def test_case_insensitive_collision(tmp_db: Database) -> None:
    # The primary key uses COLLATE NOCASE; an upsert with different casing
    # should merge onto the existing row rather than create a new one.
    tmp_db.set_group_alias("Foo/Bar", "Original")
    tmp_db.set_group_alias("foo/bar", "Updated")
    aliases = tmp_db.list_group_aliases()
    # One row, latest display name wins.
    assert len(aliases) == 1
    assert list(aliases.values()) == ["Updated"]


def test_empty_group_path_is_storable(tmp_db: Database) -> None:
    # Library-root bucket must be aliasable too.
    tmp_db.set_group_alias("", "Loose files")
    assert tmp_db.list_group_aliases() == {"": "Loose files"}

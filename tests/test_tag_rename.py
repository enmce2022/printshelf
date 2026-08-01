from __future__ import annotations

import pytest

from spoolhouse.database import Database


def _tag_id(db: Database, name: str) -> int:
    return next(
        t["id"] for t in db.list_tags() if t["name"].casefold() == name.casefold()
    )


def test_rename_to_new_name(tmp_db: Database, make_item) -> None:
    item_id = make_item(path="/lib/a.stl", relative_path="a.stl", filename="a.stl")
    tmp_db.set_tags(item_id, ["voron"])
    voron_id = _tag_id(tmp_db, "voron")

    result = tmp_db.rename_tag(voron_id, "voron-2.4")
    assert result is not None
    assert result["name"] == "voron-2.4"
    assert int(result["id"]) == voron_id  # id preserved on simple rename
    assert int(result["item_count"]) == 1


def test_rename_onto_existing_merges_items(tmp_db: Database, make_item) -> None:
    a = make_item(path="/lib/a.stl", relative_path="a.stl", filename="a.stl")
    b = make_item(path="/lib/b.stl", relative_path="b.stl", filename="b.stl")
    tmp_db.set_tags(a, ["petg"])
    tmp_db.set_tags(b, ["voron"])

    petg_id = _tag_id(tmp_db, "petg")
    result = tmp_db.rename_tag(petg_id, "voron")

    # Result is the surviving "voron" tag with merged item count.
    assert result is not None
    assert result["name"].casefold() == "voron"
    assert int(result["item_count"]) == 2

    # Both items now reference the same canonical tag, no orphans.
    item_a = tmp_db.get_item(a)
    item_b = tmp_db.get_item(b)
    assert [t.casefold() for t in item_a["tags"]] == ["voron"]
    assert [t.casefold() for t in item_b["tags"]] == ["voron"]

    # The "petg" tag is gone.
    remaining = {t["name"].casefold() for t in tmp_db.list_tags()}
    assert "petg" not in remaining


def test_rename_case_only_preserves_id(tmp_db: Database, make_item) -> None:
    item_id = make_item()
    tmp_db.set_tags(item_id, ["voron"])
    original_id = _tag_id(tmp_db, "voron")

    # Case-only rename: same tag (NOCASE unique), so it just updates the
    # stored casing, keeping the id.
    result = tmp_db.rename_tag(original_id, "VORON")
    assert result is not None
    assert int(result["id"]) == original_id
    assert result["name"] == "VORON"


def test_rename_empty_name_rejected(tmp_db: Database, make_item) -> None:
    item_id = make_item()
    tmp_db.set_tags(item_id, ["voron"])
    voron_id = _tag_id(tmp_db, "voron")

    with pytest.raises(ValueError):
        tmp_db.rename_tag(voron_id, "   ")


def test_rename_unknown_id_returns_none(tmp_db: Database) -> None:
    assert tmp_db.rename_tag(9999, "anything") is None


def test_delete_tag_cascades_to_item_tags(tmp_db: Database, make_item) -> None:
    a = make_item(path="/lib/a.stl", relative_path="a.stl", filename="a.stl")
    b = make_item(path="/lib/b.stl", relative_path="b.stl", filename="b.stl")
    tmp_db.set_tags(a, ["voron", "petg"])
    tmp_db.set_tags(b, ["petg"])

    petg_id = _tag_id(tmp_db, "petg")
    assert tmp_db.delete_tag(petg_id) is True

    # Items still exist; "petg" stripped from both.
    item_a = tmp_db.get_item(a)
    item_b = tmp_db.get_item(b)
    assert item_a is not None and item_b is not None
    assert [t.casefold() for t in item_a["tags"]] == ["voron"]
    assert item_b["tags"] == []

    # Tag itself is gone.
    remaining = {t["name"].casefold() for t in tmp_db.list_tags()}
    assert "petg" not in remaining
    assert "voron" in remaining


def test_delete_unknown_tag_returns_false(tmp_db: Database) -> None:
    assert tmp_db.delete_tag(9999) is False

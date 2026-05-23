from __future__ import annotations

from printshelf.database import Database


def test_bulk_set_group_override_assigns_to_many(
    tmp_db: Database, make_item
) -> None:
    a = make_item(path="/lib/a.stl", relative_path="a.stl", filename="a.stl")
    b = make_item(path="/lib/b.stl", relative_path="b.stl", filename="b.stl")
    c = make_item(path="/lib/c.stl", relative_path="c.stl", filename="c.stl")
    untouched = make_item(
        path="/lib/d.stl", relative_path="d.stl", filename="d.stl"
    )

    updated = tmp_db.bulk_set_group_override([a, b, c], "Project Alpha")

    assert updated == 3
    rows = tmp_db.list_items()
    by_id = {row["id"]: row for row in rows}
    assert by_id[a]["group_override"] == "Project Alpha"
    assert by_id[b]["group_override"] == "Project Alpha"
    assert by_id[c]["group_override"] == "Project Alpha"
    assert by_id[untouched]["group_override"] is None


def test_bulk_set_group_override_clear_with_none(
    tmp_db: Database, make_item
) -> None:
    a = make_item(path="/lib/a.stl", relative_path="a.stl", filename="a.stl")
    tmp_db.bulk_set_group_override([a], "Temporary")

    cleared = tmp_db.bulk_set_group_override([a], None)
    assert cleared == 1

    rows = tmp_db.list_items()
    assert rows[0]["group_override"] is None


def test_bulk_set_group_override_empty_ids_returns_zero(
    tmp_db: Database,
) -> None:
    assert tmp_db.bulk_set_group_override([], "anywhere") == 0
    assert tmp_db.bulk_set_group_override([0, -1, "bad"], "anywhere") == 0

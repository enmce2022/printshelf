from __future__ import annotations

from printshelf.database import Database


def _names(rows: list[dict]) -> list[str]:
    return [row["filename"] for row in rows]


def _seed_diverse_library(tmp_db: Database, make_item) -> None:
    # Mix of stl/gcode, distinct names + relative paths, distinct tags,
    # distinct descriptions/meta to cover every search branch.
    a = make_item(
        path="/lib/voron/a-bracket.stl",
        relative_path="voron/a-bracket.stl",
        filename="a-bracket.stl",
        file_type="stl",
        description="bed mount",
    )
    b = make_item(
        path="/lib/prusa/calibration_cube.gcode",
        relative_path="prusa/calibration_cube.gcode",
        filename="calibration_cube.gcode",
        file_type="gcode",
    )
    c = make_item(
        path="/lib/voron/exhaust.stl",
        relative_path="voron/exhaust.stl",
        filename="exhaust.stl",
        file_type="stl",
    )
    d = make_item(
        path="/lib/misc/extra.stl",
        relative_path="misc/extra.stl",
        filename="extra.stl",
        file_type="stl",
        description="",
    )
    tmp_db.set_tags(a, ["voron", "petg"])
    tmp_db.set_tags(b, ["benchmark"])
    tmp_db.set_tags(c, ["voron"])
    # d has no tags
    return a, b, c, d


def test_filter_by_query_matches_filename(tmp_db: Database, make_item) -> None:
    _seed_diverse_library(tmp_db, make_item)
    rows = tmp_db.list_items(query="bracket")
    assert _names(rows) == ["a-bracket.stl"]


def test_filter_by_query_matches_relative_path(tmp_db: Database, make_item) -> None:
    _seed_diverse_library(tmp_db, make_item)
    rows = tmp_db.list_items(query="prusa/")
    assert _names(rows) == ["calibration_cube.gcode"]


def test_filter_by_query_matches_description(tmp_db: Database, make_item) -> None:
    _seed_diverse_library(tmp_db, make_item)
    rows = tmp_db.list_items(query="bed mount")
    assert _names(rows) == ["a-bracket.stl"]


def test_filter_by_query_matches_tag_name(tmp_db: Database, make_item) -> None:
    _seed_diverse_library(tmp_db, make_item)
    rows = tmp_db.list_items(query="petg")
    assert _names(rows) == ["a-bracket.stl"]


def test_filter_by_file_type(tmp_db: Database, make_item) -> None:
    _seed_diverse_library(tmp_db, make_item)
    stl_rows = tmp_db.list_items(file_type="stl")
    assert sorted(_names(stl_rows)) == sorted(
        ["a-bracket.stl", "exhaust.stl", "extra.stl"]
    )
    gcode_rows = tmp_db.list_items(file_type="gcode")
    assert _names(gcode_rows) == ["calibration_cube.gcode"]


def test_filter_by_tag_uses_nocase(tmp_db: Database, make_item) -> None:
    _seed_diverse_library(tmp_db, make_item)
    # "VORON" should match "voron" because of COLLATE NOCASE.
    rows = tmp_db.list_items(tag="VORON")
    assert sorted(_names(rows)) == ["a-bracket.stl", "exhaust.stl"]


def test_filter_by_tag_excludes_untagged_items(tmp_db: Database, make_item) -> None:
    _seed_diverse_library(tmp_db, make_item)
    rows = tmp_db.list_items(tag="voron")
    assert "extra.stl" not in _names(rows)  # untagged item filtered out


def test_combined_filters_intersect(tmp_db: Database, make_item) -> None:
    _seed_diverse_library(tmp_db, make_item)
    # "voron" tag AND filename matching "exhaust"
    rows = tmp_db.list_items(query="exhaust", tag="voron", file_type="stl")
    assert _names(rows) == ["exhaust.stl"]


def test_sort_name_asc(tmp_db: Database, make_item) -> None:
    _seed_diverse_library(tmp_db, make_item)
    rows = tmp_db.list_items(file_type="stl", sort="name_asc")
    assert _names(rows) == ["a-bracket.stl", "exhaust.stl", "extra.stl"]


def test_sort_name_desc(tmp_db: Database, make_item) -> None:
    _seed_diverse_library(tmp_db, make_item)
    rows = tmp_db.list_items(file_type="stl", sort="name_desc")
    assert _names(rows) == ["extra.stl", "exhaust.stl", "a-bracket.stl"]


def test_sort_unknown_falls_back_to_default(tmp_db: Database, make_item) -> None:
    # A nonsense sort key must not crash or inject SQL — it should
    # silently fall back to the default mapping.
    _seed_diverse_library(tmp_db, make_item)
    rows = tmp_db.list_items(sort="; DROP TABLE items; --")
    assert len(rows) == 4  # still returns rows, no error


def test_list_items_returns_tags_in_nocase_order(tmp_db: Database, make_item) -> None:
    item_id = make_item()
    tmp_db.set_tags(item_id, ["Zebra", "alpha", "Mike"])
    rows = tmp_db.list_items()
    assert len(rows) == 1
    # GROUP_CONCAT subquery sorts names with COLLATE NOCASE.
    assert rows[0]["tags"] == ["alpha", "Mike", "Zebra"]


def test_list_items_handles_no_tags(tmp_db: Database, make_item) -> None:
    make_item()
    rows = tmp_db.list_items()
    assert rows[0]["tags"] == []


def test_get_item_aggregates_tags_in_single_query(tmp_db: Database, make_item) -> None:
    item_id = make_item()
    tmp_db.set_tags(item_id, ["foo", "bar"])
    item = tmp_db.get_item(item_id)
    assert item is not None
    assert sorted(item["tags"]) == ["bar", "foo"]


def test_get_item_unknown_returns_none(tmp_db: Database) -> None:
    assert tmp_db.get_item(9999) is None

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from printshelf.preview import (
    _STRATEGIES,
    GcodeEmbeddedThumbStrategy,
    GcodeToolpathStrategy,
    StlStrategy,
    generate_preview,
)


def _make_png_bytes(width: int = 32, height: int = 32) -> bytes:
    img = Image.new("RGBA", (width, height), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _embed_thumbnail_block(png_bytes: bytes, width: int, height: int) -> str:
    encoded = base64.b64encode(png_bytes).decode("ascii")
    chunk = 78
    lines = [
        f"; thumbnail begin {width}x{height} {len(encoded)}",
    ]
    for i in range(0, len(encoded), chunk):
        lines.append(f"; {encoded[i : i + chunk]}")
    lines.append("; thumbnail end")
    return "\n".join(lines) + "\n"


def _write_gcode(path: Path, *, with_thumbnail: bool, with_motion: bool) -> None:
    parts: list[str] = []
    if with_thumbnail:
        png = _make_png_bytes(32, 32)
        parts.append(_embed_thumbnail_block(png, 32, 32))
    if with_motion:
        parts.append(
            "G90\n"
            "G1 X0 Y0 Z0.2 E0\n"
            "G1 X10 Y0 Z0.2 E1\n"
            "G1 X10 Y10 Z0.2 E2\n"
            "G1 X0 Y10 Z0.2 E3\n"
            "G1 X0 Y0 Z0.2 E4\n"
        )
    path.write_text("".join(parts), encoding="utf-8")


def test_strategy_registry_has_expected_classes() -> None:
    types = [type(s).__name__ for s in _STRATEGIES]
    assert "StlStrategy" in types
    assert "GcodeEmbeddedThumbStrategy" in types
    assert "GcodeToolpathStrategy" in types
    # Embedded-thumb must come before toolpath fallback for gcode files.
    embed_idx = types.index("GcodeEmbeddedThumbStrategy")
    toolpath_idx = types.index("GcodeToolpathStrategy")
    assert embed_idx < toolpath_idx


def test_embedded_thumb_strategy_wins_when_png_present(tmp_path: Path) -> None:
    gcode_file = tmp_path / "with_thumb.gcode"
    _write_gcode(gcode_file, with_thumbnail=True, with_motion=True)
    preview_dir = tmp_path / "previews"

    name, source, indexed = generate_preview(gcode_file, preview_dir, modified_at=1)

    assert source == "embedded-png"
    assert indexed["preview_mode"] == "embedded-png"
    assert (preview_dir / name).exists()
    # The toolpath-only fields must NOT appear when the embedded path won.
    assert "segment_count_raw" not in indexed
    assert "extrusion_length_mm" not in indexed


def test_falls_back_to_toolpath_when_no_thumbnail(tmp_path: Path) -> None:
    gcode_file = tmp_path / "no_thumb.gcode"
    _write_gcode(gcode_file, with_thumbnail=False, with_motion=True)
    preview_dir = tmp_path / "previews"

    name, source, indexed = generate_preview(gcode_file, preview_dir, modified_at=1)

    assert source == "generated-toolpath"
    assert indexed["preview_mode"] == "generated-toolpath"
    assert indexed["segment_count_raw"] >= 1
    assert (preview_dir / name).exists()


def test_unsupported_extension_returns_placeholder(tmp_path: Path) -> None:
    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("hello", encoding="utf-8")
    preview_dir = tmp_path / "previews"

    name, source, indexed = generate_preview(txt_file, preview_dir, modified_at=1)

    assert source == "placeholder"
    assert indexed["preview_mode"] == "placeholder"
    assert indexed["file_extension"] == "txt"
    assert (preview_dir / name).exists()


def test_strategy_failure_writes_placeholder_error(tmp_path: Path) -> None:
    # A G-code file with neither a thumbnail nor any motion commands forces
    # the toolpath strategy to raise ("No printable extrusion moves found"),
    # which the registry should catch and convert to a placeholder-error.
    gcode_file = tmp_path / "empty.gcode"
    _write_gcode(gcode_file, with_thumbnail=False, with_motion=False)
    preview_dir = tmp_path / "previews"

    name, source, indexed = generate_preview(gcode_file, preview_dir, modified_at=1)

    assert source == "placeholder-error"
    assert indexed["preview_mode"] == "placeholder-error"
    assert "preview_error" in indexed
    assert (preview_dir / name).exists()


@pytest.mark.parametrize(
    "strategy_cls,extensions",
    [
        (StlStrategy, ("stl",)),
        (GcodeEmbeddedThumbStrategy, ("gcode",)),
        (GcodeToolpathStrategy, ("gcode",)),
    ],
)
def test_strategy_extensions_metadata(strategy_cls, extensions) -> None:
    instance = strategy_cls()
    assert instance.extensions == extensions
    assert instance.source != ""

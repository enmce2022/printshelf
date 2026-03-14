from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import trimesh
from PIL import Image, ImageDraw
from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
THUMB_START_RE = re.compile(
    r"^\s*;\s*(thumbnail(?:_[A-Za-z0-9]+)?)\s+begin\s+(\d+)x(\d+)\s+(\d+)",
    re.IGNORECASE,
)
THUMB_END_RE = re.compile(
    r"^\s*;\s*thumbnail(?:_[A-Za-z0-9]+)?\s+end\s*$",
    re.IGNORECASE,
)


def _preview_name(file_path: Path, modified_at: int) -> str:
    digest = hashlib.sha1(f"{file_path.resolve()}::{modified_at}".encode("utf-8")).hexdigest()
    return f"{digest}.png"


def _placeholder_preview(output_path: Path, title: str, subtitle: str = "") -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (640, 480), (245, 247, 250, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28, 28, 612, 452), radius=24, outline=(180, 186, 194, 255), width=3)
    draw.text((48, 72), title[:40], fill=(43, 51, 59, 255))
    if subtitle:
        draw.text((48, 128), subtitle[:120], fill=(89, 99, 110, 255))
    image.save(output_path)


def _set_equal_axes(ax, points: np.ndarray) -> None:
    mins = points.min(axis=0)
    maxs = points.max(axis=0)
    center = (mins + maxs) / 2.0
    span = np.max(maxs - mins)
    span = max(span, 1.0)
    radius = span / 2.0
    ax.set_xlim(center[0] - radius, center[0] + radius)
    ax.set_ylim(center[1] - radius, center[1] + radius)
    ax.set_zlim(center[2] - radius, center[2] + radius)


def _load_mesh(file_path: Path) -> trimesh.Trimesh:
    loaded = trimesh.load(file_path, force="mesh", process=True)
    if isinstance(loaded, trimesh.Scene):
        geometries = [
            geom for geom in loaded.geometry.values() if isinstance(geom, trimesh.Trimesh)
        ]
        if not geometries:
            raise ValueError("Scene contains no mesh geometry")
        mesh = trimesh.util.concatenate(geometries)
    elif isinstance(loaded, trimesh.Trimesh):
        mesh = loaded
    else:
        raise ValueError(f"Unsupported mesh type: {type(loaded)!r}")
    if len(mesh.faces) == 0:
        raise ValueError("Mesh has no faces")
    mesh = mesh.copy()
    mesh.remove_unreferenced_vertices()
    return mesh


def render_stl_preview(file_path: Path, output_path: Path) -> dict[str, Any]:
    mesh = _load_mesh(file_path)

    original_bounds = mesh.bounds.copy()

    if mesh.is_watertight:
        try:
            transforms, _ = trimesh.poses.compute_stable_poses(mesh, n_samples=1, threshold=0.0)
            if len(transforms):
                mesh.apply_transform(transforms[0])
        except Exception:
            pass

    mesh.apply_translation(-mesh.bounds.mean(axis=0))

    triangles = mesh.triangles
    normals = mesh.face_normals if len(mesh.face_normals) == len(mesh.faces) else np.zeros((len(mesh.faces), 3))
    light = np.array([0.4, -0.5, 1.0], dtype=float)
    light /= np.linalg.norm(light)
    intensity = np.clip(normals @ light, 0.18, 1.0)
    colors = plt.cm.Greys(0.25 + 0.55 * intensity)

    fig = plt.figure(figsize=(5.2, 5.2), dpi=120)
    ax = fig.add_subplot(111, projection="3d")
    collection = Poly3DCollection(triangles, linewidths=0.03)
    collection.set_facecolor(colors)
    collection.set_edgecolor((0.0, 0.0, 0.0, 0.03))
    ax.add_collection3d(collection)

    _set_equal_axes(ax, mesh.vertices)
    ax.view_init(elev=24, azim=-58)
    ax.set_axis_off()
    fig.patch.set_alpha(0)
    ax.patch.set_alpha(0)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, transparent=True, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)

    extents = original_bounds[1] - original_bounds[0]
    return {
        "preview_mode": "generated-mesh",
        "bounds_mm": [round(float(value), 3) for value in extents.tolist()],
        "vertex_count": int(len(mesh.vertices)),
        "face_count": int(len(mesh.faces)),
        "watertight": bool(mesh.is_watertight),
    }


def _extract_largest_png_thumbnail(file_path: Path) -> bytes | None:
    candidates: list[tuple[int, bytes]] = []
    current_kind: str | None = None
    current_width = 0
    current_height = 0
    current_lines: list[str] = []

    with file_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line_number, line in enumerate(handle):
            if line_number > 4000 and current_kind is None and candidates:
                break

            start = THUMB_START_RE.match(line)
            if start:
                current_kind = start.group(1).lower()
                current_width = int(start.group(2))
                current_height = int(start.group(3))
                current_lines = []
                continue

            if current_kind is not None:
                if THUMB_END_RE.match(line):
                    cleaned = "".join(
                        re.sub(r"^\s*;\s?", "", part).strip()
                        for part in current_lines
                    )
                    try:
                        raw = base64.b64decode(cleaned, validate=False)
                    except Exception:
                        raw = b""
                    if raw.startswith(PNG_SIGNATURE):
                        area = current_width * current_height
                        candidates.append((area, raw))
                    current_kind = None
                    current_lines = []
                else:
                    current_lines.append(line)

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def extract_gcode_thumbnail_preview(file_path: Path, output_path: Path) -> bool:
    raw = _extract_largest_png_thumbnail(file_path)
    if not raw:
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(io.BytesIO(raw))
    image.save(output_path)
    return True


def _parse_comment_metadata(comment: str, metadata: dict[str, Any]) -> None:
    text = comment.strip()
    if not text:
        return

    lower = text.lower()
    if lower.startswith("generated by") and "slicer" not in metadata:
        metadata["slicer"] = text
    elif lower.startswith("time:"):
        try:
            metadata["estimated_time_s"] = int(text.split(":", 1)[1].strip())
        except Exception:
            pass
    elif "estimated printing time" in lower and "estimated_time" not in metadata:
        metadata["estimated_time"] = text
    elif "filament used" in lower and "filament_used" not in metadata:
        metadata["filament_used"] = text
    elif "total layer number" in lower and "layer_count_header" not in metadata:
        digits = re.findall(r"\d+", text)
        if digits:
            metadata["layer_count_header"] = int(digits[-1])


def render_gcode_preview(file_path: Path, output_path: Path) -> dict[str, Any]:
    current = {"X": 0.0, "Y": 0.0, "Z": 0.0, "E": 0.0}
    absolute_axes = True
    e_override: bool | None = None
    extrusion_length = 0.0
    segments: list[tuple[tuple[float, float, float], tuple[float, float, float], float]] = []
    metadata: dict[str, Any] = {}
    unique_z: set[float] = set()

    with file_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            code, sep, comment = line.partition(";")
            if sep:
                _parse_comment_metadata(comment, metadata)
            code = code.strip()
            if not code:
                continue

            parts = code.split()
            command = parts[0].upper()
            params: dict[str, float] = {}

            for token in parts[1:]:
                if len(token) < 2:
                    continue
                key = token[0].upper()
                if key not in {"X", "Y", "Z", "E", "F"}:
                    continue
                try:
                    params[key] = float(token[1:])
                except ValueError:
                    continue

            if command == "G90":
                absolute_axes = True
                e_override = None
                continue
            if command == "G91":
                absolute_axes = False
                e_override = None
                continue
            if command == "M82":
                e_override = True
                continue
            if command == "M83":
                e_override = False
                continue
            if command == "G92":
                for axis in ("X", "Y", "Z", "E"):
                    if axis in params:
                        current[axis] = params[axis]
                continue

            if command not in {"G0", "G1"}:
                continue

            nxt = dict(current)
            for axis in ("X", "Y", "Z"):
                if axis in params:
                    nxt[axis] = params[axis] if absolute_axes else current[axis] + params[axis]
            absolute_e = absolute_axes if e_override is None else e_override
            if "E" in params:
                nxt["E"] = params["E"] if absolute_e else current["E"] + params["E"]

            delta_e = nxt["E"] - current["E"]
            moved = (nxt["X"], nxt["Y"], nxt["Z"]) != (current["X"], current["Y"], current["Z"])
            extruding = delta_e > 1e-6 and moved

            if extruding:
                start = (current["X"], current["Y"], current["Z"])
                end = (nxt["X"], nxt["Y"], nxt["Z"])
                segments.append((start, end, nxt["Z"]))
                extrusion_length += delta_e
                if len(unique_z) < 10000:
                    unique_z.add(round(float(nxt["Z"]), 3))

            current = nxt

    if not segments:
        raise ValueError("No printable extrusion moves found in G-code")

    raw_segment_count = len(segments)
    max_segments = 60000
    if len(segments) > max_segments:
        step = math.ceil(len(segments) / max_segments)
        segments = segments[::step]

    lines = [[seg[0], seg[1]] for seg in segments]
    z_values = np.array([seg[2] for seg in segments], dtype=float)
    points = np.array([point for seg in lines for point in seg], dtype=float)
    z_min = float(z_values.min())
    z_max = float(z_values.max())
    span = max(z_max - z_min, 1e-9)
    colors = plt.cm.viridis((z_values - z_min) / span)

    fig = plt.figure(figsize=(5.2, 5.2), dpi=120)
    ax = fig.add_subplot(111, projection="3d")
    collection = Line3DCollection(lines, colors=colors, linewidths=0.9, alpha=0.95)
    ax.add_collection3d(collection)

    _set_equal_axes(ax, points)
    ax.view_init(elev=26, azim=-58)
    ax.set_axis_off()
    fig.patch.set_alpha(0)
    ax.patch.set_alpha(0)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, transparent=True, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)

    metadata.update(
        {
            "preview_mode": "generated-toolpath",
            "segment_count_raw": raw_segment_count,
            "segment_count_previewed": len(segments),
            "layer_count_estimate": len(unique_z),
            "extrusion_length_mm": round(extrusion_length, 3),
            "toolpath_bounds_mm": [round(float(v), 3) for v in (points.max(axis=0) - points.min(axis=0)).tolist()],
        }
    )
    return metadata


def generate_preview(file_path: Path, preview_dir: Path, modified_at: int) -> tuple[str | None, str, dict[str, Any]]:
    preview_name = _preview_name(file_path, modified_at)
    output_path = preview_dir / preview_name
    file_type = file_path.suffix.lower().lstrip(".")
    indexed_meta: dict[str, Any] = {
        "file_extension": file_type,
    }

    try:
        if file_type == "stl":
            indexed_meta.update(render_stl_preview(file_path, output_path))
            return preview_name, "generated-mesh", indexed_meta

        if file_type == "gcode":
            if extract_gcode_thumbnail_preview(file_path, output_path):
                indexed_meta["preview_mode"] = "embedded-png"
                return preview_name, "embedded-png", indexed_meta
            indexed_meta.update(render_gcode_preview(file_path, output_path))
            return preview_name, "generated-toolpath", indexed_meta

        _placeholder_preview(output_path, file_type.upper(), "Unsupported preview type")
        indexed_meta["preview_mode"] = "placeholder"
        return preview_name, "placeholder", indexed_meta
    except Exception as exc:
        _placeholder_preview(output_path, file_type.upper(), str(exc))
        indexed_meta["preview_mode"] = "placeholder-error"
        indexed_meta["preview_error"] = str(exc)
        return preview_name, "placeholder-error", indexed_meta

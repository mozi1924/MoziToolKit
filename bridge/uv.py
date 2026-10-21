"""
MoziToolKit UV Bridge Module.

Accelerated 2D UV geometric operations backed strictly by Rust libmtk (libmtk_py).
"""

from __future__ import annotations

from typing import List, Optional, Tuple, Any

from .engine import get_libmtk, require_libmtk


def __getattr__(name: str) -> Any:
    if name == "mtk_py":
        return get_libmtk()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


import math


def calculate_uv_area(uvs: List[Tuple[float, float]]) -> float:
    """Calculate the 2D polygon area of UV coordinates via the Shoelace formula."""
    if len(uvs) < 3:
        return 0.0
    area = 0.0
    for i in range(len(uvs)):
        j = (i + 1) % len(uvs)
        area += uvs[i][0] * uvs[j][1] - uvs[j][0] * uvs[i][1]
    return abs(area) * 0.5


def get_uv_bounds(uvs: List[Tuple[float, float]]) -> Tuple[float, float, float, float, float, float]:
    """Calculate bounding box `(min_u, min_v, max_u, max_v, width, height)` of UV coordinates."""
    if not uvs:
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    min_u = min(p[0] for p in uvs)
    max_u = max(p[0] for p in uvs)
    min_v = min(p[1] for p in uvs)
    max_v = max(p[1] for p in uvs)
    return (min_u, min_v, max_u, max_v, max_u - min_u, max_v - min_v)


def get_uv_center(uvs: List[Tuple[float, float]]) -> Tuple[float, float]:
    """Calculate geometric center `(center_u, center_v)` of UV coordinates."""
    if not uvs:
        return (0.0, 0.0)
    return (sum(p[0] for p in uvs) / len(uvs), sum(p[1] for p in uvs) / len(uvs))


def is_uv_collapsed(
    uvs: List[Tuple[float, float]],
    area_threshold: Optional[float] = None,
    dist_threshold: Optional[float] = None,
    pixel_step: Optional[Tuple[float, float]] = None,
) -> bool:
    """Detect whether a UV face is degenerate or collapsed to a line/point."""
    _, _, _, _, w, h = get_uv_bounds(uvs)
    thresh = area_threshold if area_threshold is not None else 1e-4
    return (w * h) < thresh or calculate_uv_area(uvs) < thresh


def is_orthogonal_angle(angle_rad: float, tolerance: float = 1e-3) -> bool:
    """Check if rotation angle is a cardinal/orthogonal angle (multiple of 90 degrees)."""
    half_pi = math.pi * 0.5
    rem = abs(angle_rad) % half_pi
    return rem < tolerance or abs(rem - half_pi) < tolerance


def detect_uv_rotation(uvs: List[Tuple[float, float]], tolerance: float = 1e-3) -> float:
    """Detect planar rotation angle of an orthogonal or slanted UV quad."""
    if len(uvs) < 2:
        return 0.0
    return math.atan2(uvs[1][1] - uvs[0][1], uvs[1][0] - uvs[0][0])


def straighten_uv(
    uvs: List[Tuple[float, float]],
    angle: Optional[float] = None,
) -> Tuple[float, bool, List[Tuple[float, float]]]:
    """Straighten slanted UV polygon coordinates back to an axis-aligned grid."""
    rot = angle if angle is not None else detect_uv_rotation(uvs)
    if is_orthogonal_angle(rot):
        return (rot, False, list(uvs))
    cx, cy = get_uv_center(uvs)
    cos_a = math.cos(-rot)
    sin_a = math.sin(-rot)
    new_uvs = []
    for u, v in uvs:
        du, dv = u - cx, v - cy
        new_uvs.append((cx + du * cos_a - dv * sin_a, cy + du * sin_a + dv * cos_a))
    return (rot, True, new_uvs)


def scale_uv(uvs: List[Tuple[float, float]], scale_factor: float) -> List[Tuple[float, float]]:
    mtk = require_libmtk("scale_uv")
    return mtk.scale_uv(uvs, scale_factor)


def normalize_uv_for_atlas_tiling(
    uvs: List[Tuple[float, float]],
    epsilon: float = 1e-6,
) -> Tuple[List[Tuple[float, float]], Tuple[float, float, float], Tuple[float, float, float]]:
    """Normalize UV coordinates for atlas tiled mapping."""
    return (list(uvs), (1.0, 1.0, 1.0), (0.0, 0.0, 0.0))


def uv_requires_atlas_tiling(uvs: List[Tuple[float, float]], epsilon: float = 1e-4) -> bool:
    """Detect whether UV bounds exceed standard unit 0..1 range."""
    min_u, min_v, max_u, max_v, _, _ = get_uv_bounds(uvs)
    return min_u < -epsilon or min_v < -epsilon or max_u > 1.0 + epsilon or max_v > 1.0 + epsilon


def restore_atlas_tiling_uv(
    u: float,
    v: float,
    scale: Tuple[float, float, float] = (1.0, 1.0, 1.0),
    location: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: float = 0.0,
) -> Tuple[float, float]:
    """Restore normalized UV point into tiled coordinate space."""
    return (u * scale[0] + location[0], v * scale[1] + location[1])


def batch_repair_fluid_uv(
    verts_flat: Any,
    uvs_flat: Any,
    normals_flat: Optional[Any] = None,
    force: bool = False,
    min_slope_threshold: float = 0.005,
) -> Tuple[int, Any]:
    """
    Batch repair inverted fluid UVs across quad vertices and UVs.
    Supports zero-copy mutable buffers (numpy ndarray, array.array) and standard Python lists.
    """
    mtk = require_libmtk("batch_repair_fluid_uv")
    return mtk.batch_repair_fluid_uv(verts_flat, uvs_flat, normals_flat, force, min_slope_threshold)


def repair_quad_fluid_uv(
    verts: List[Tuple[float, float, float]],
    uvs: List[Tuple[float, float]],
    normal: Optional[Tuple[float, float, float]] = None,
    force: bool = False,
    min_slope_threshold: float = 0.005,
) -> Tuple[bool, List[Tuple[float, float]]]:
    """Repair inverted single quad fluid UVs via the batched engine."""
    flat_verts = [x for v in verts for x in v]
    flat_uvs = [x for u in uvs for x in u]
    flat_norms = [x for n in normal for x in n] if normal else None
    count, out_uvs = batch_repair_fluid_uv(flat_verts, flat_uvs, flat_norms, force, min_slope_threshold)
    repaired = count > 0
    res_uvs = [(out_uvs[i * 2], out_uvs[i * 2 + 1]) for i in range(len(uvs))]
    return (repaired, res_uvs)


def get_fluid_top_uvs(is_flowing: bool = True, rotation: float = 0.0) -> List[Tuple[float, float]]:
    """Generate fluid surface top face UV corners."""
    if is_flowing:
        base = [(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)]
    else:
        base = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    if abs(rotation) < 1e-4:
        return base
    cos_a = math.cos(rotation)
    sin_a = math.sin(rotation)
    return [(0.5 + (u - 0.5) * cos_a - (v - 0.5) * sin_a, 0.5 + (u - 0.5) * sin_a + (v - 0.5) * cos_a) for u, v in base]


def get_fluid_side_uvs(h_left_top: float, h_right_top: float) -> List[Tuple[float, float]]:
    """Generate fluid falling side wall UV corners."""
    u1 = 0.0
    u2 = 1.0
    v_top_l = (1.0 - h_left_top) * 0.5
    v_top_r = (1.0 - h_right_top) * 0.5
    v_bot = 0.5
    return [(u1, v_top_l), (u2, v_bot), (u2, v_bot), (u1, v_top_r)]


def repair_mesh_fluid_uv_inplace(
    positions: Any,
    loop_verts: Any,
    face_loop_starts: Any,
    face_loop_totals: Any,
    uvs: Any,
    face_indices: Optional[Any] = None,
    force: bool = False,
    min_slope_threshold: float = 0.005,
) -> int:
    """
    In-place vectorized batch repair for inverted fluid UVs directly on indexed mesh geometry.
    Modifies the uvs numpy ndarray buffer directly in-place.
    Returns the number of quad faces repaired.
    """
    mtk = require_libmtk("repair_mesh_fluid_uv_inplace")
    return mtk.repair_mesh_fluid_uv_inplace(
        positions,
        loop_verts,
        face_loop_starts,
        face_loop_totals,
        uvs,
        face_indices,
        force,
        min_slope_threshold,
    )

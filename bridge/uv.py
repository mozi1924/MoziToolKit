"""
MoziToolKit UV Bridge Module.

Accelerated 2D UV geometric operations backed by Rust libmtk (libmtk_py),
with robust pure-Python fallback implementations when libmtk_py is unavailable.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

try:
    import libmtk_py as mtk_py
except ImportError:
    try:
        import mtk_py
    except ImportError:
        mtk_py = None

HAS_LIBMTK_UV = mtk_py is not None and hasattr(mtk_py, "calculate_uv_area")


# ---------------------------------------------------------------------------
# Pure Python Fallbacks
# ---------------------------------------------------------------------------

def _py_calculate_uv_area(uvs: List[Tuple[float, float]]) -> float:
    n = len(uvs)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        u1, v1 = uvs[i]
        u2, v2 = uvs[(i + 1) % n]
        area += u1 * v2 - u2 * v1
    return 0.5 * abs(area)


def _py_get_uv_bounds(uvs: List[Tuple[float, float]]) -> Tuple[float, float, float, float, float, float]:
    if not uvs:
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    u_coords = [p[0] for p in uvs]
    v_coords = [p[1] for p in uvs]
    min_u, max_u = min(u_coords), max(u_coords)
    min_v, max_v = min(v_coords), max(v_coords)
    return (min_u, min_v, max_u, max_v, max_u - min_u, max_v - min_v)


def _py_get_uv_center(uvs: List[Tuple[float, float]]) -> Tuple[float, float]:
    if not uvs:
        return (0.0, 0.0)
    tot_u = sum(p[0] for p in uvs)
    tot_v = sum(p[1] for p in uvs)
    n = float(len(uvs))
    return (tot_u / n, tot_v / n)


def _py_is_uv_collapsed(
    uvs: List[Tuple[float, float]],
    area_threshold: Optional[float] = None,
    dist_threshold: Optional[float] = None,
    pixel_step: Optional[Tuple[float, float]] = None,
) -> bool:
    if len(uvs) < 3:
        return True

    if pixel_step is not None:
        step_u, step_v = pixel_step
        calc_area_threshold = area_threshold if area_threshold is not None else (step_u * step_v * 0.05)
        calc_dist_threshold = dist_threshold if dist_threshold is not None else (min(step_u, step_v) * 0.1)
    else:
        calc_area_threshold = area_threshold if area_threshold is not None else 1e-6
        calc_dist_threshold = dist_threshold if dist_threshold is not None else 1e-4

    if _py_calculate_uv_area(uvs) < calc_area_threshold:
        return True

    max_dist_sq = 0.0
    n = len(uvs)
    for i in range(n):
        for j in range(i + 1, n):
            du = uvs[i][0] - uvs[j][0]
            dv = uvs[i][1] - uvs[j][1]
            dist_sq = du * du + dv * dv
            if dist_sq > max_dist_sq:
                max_dist_sq = dist_sq

    return max_dist_sq < (calc_dist_threshold * calc_dist_threshold)


def _py_is_orthogonal_angle(angle_rad: float, tolerance: float = 1e-3) -> bool:
    half_pi = math.pi / 2.0
    rem = abs(angle_rad) % half_pi
    return rem < tolerance or abs(rem - half_pi) < tolerance


def _py_detect_uv_rotation(uvs: List[Tuple[float, float]], tolerance: float = 1e-3) -> float:
    n = len(uvs)
    if n < 3:
        return 0.0

    valid_edges = []
    for i in range(n):
        p_curr = uvs[i]
        p_next = uvs[(i + 1) % n]
        dx = p_next[0] - p_curr[0]
        dy = p_next[1] - p_curr[1]
        length = math.hypot(dx, dy)
        if length >= 1e-6:
            theta = math.atan2(dy, dx)
            while theta <= -math.pi:
                theta += 2.0 * math.pi
            while theta > math.pi:
                theta -= 2.0 * math.pi
            valid_edges.append(((dx, dy), theta))

    if not valid_edges:
        return 0.0

    for _edge, theta in valid_edges:
        if _py_is_orthogonal_angle(theta, tolerance):
            return 0.0

    primary_theta = valid_edges[0][1]
    if _py_is_orthogonal_angle(primary_theta, tolerance):
        return 0.0

    return primary_theta


def _py_straighten_uv(
    uvs: List[Tuple[float, float]],
    angle: Optional[float] = None,
) -> Tuple[float, bool, List[Tuple[float, float]]]:
    if len(uvs) < 3:
        return (0.0, False, list(uvs))

    if angle is None:
        angle = _py_detect_uv_rotation(uvs)

    if abs(angle) < 1e-4:
        return (0.0, False, list(uvs))

    center_u, center_v = _py_get_uv_center(uvs)
    cos_t = math.cos(-angle)
    sin_t = math.sin(-angle)

    straightened = []
    for u, v in uvs:
        du = u - center_u
        dv = v - center_v
        new_u = center_u + (du * cos_t - dv * sin_t)
        new_v = center_v + (du * sin_t + dv * cos_t)
        straightened.append((new_u, new_v))

    return (angle, True, straightened)


def _py_scale_uv(uvs: List[Tuple[float, float]], scale_factor: float) -> List[Tuple[float, float]]:
    if not uvs:
        return []
    center_u, center_v = _py_get_uv_center(uvs)
    return [
        (center_u + (u - center_u) * scale_factor, center_v + (v - center_v) * scale_factor)
        for u, v in uvs
    ]


def _py_normalize_uv_for_atlas_tiling(
    uvs: List[Tuple[float, float]],
    epsilon: float = 1e-6,
) -> Tuple[List[Tuple[float, float]], Tuple[float, float, float], Tuple[float, float, float]]:
    if not uvs:
        return ([], (1.0, 1.0, 1.0), (0.0, 0.0, 0.0))

    min_u, min_v, max_u, max_v, span_u, span_v = _py_get_uv_bounds(uvs)
    safe_span_u = span_u if span_u > epsilon else 1.0
    safe_span_v = span_v if span_v > epsilon else 1.0

    normalized = [
        (
            (u - min_u) / safe_span_u if span_u > epsilon else 0.0,
            (v - min_v) / safe_span_v if span_v > epsilon else 0.0,
        )
        for u, v in uvs
    ]

    scale = (safe_span_u, safe_span_v, 1.0)
    location = (
        min_u + (safe_span_u - 1.0) * 0.5,
        min_v + (safe_span_v - 1.0) * 0.5,
        0.0,
    )
    return (normalized, scale, location)


def _py_uv_requires_atlas_tiling(uvs: List[Tuple[float, float]], epsilon: float = 1e-4) -> bool:
    if not uvs:
        return False
    min_u, min_v, max_u, max_v, _, _ = _py_get_uv_bounds(uvs)
    return min_u < -epsilon or max_u > 1.0 + epsilon or min_v < -epsilon or max_v > 1.0 + epsilon


def _py_restore_atlas_tiling_uv(
    u: float,
    v: float,
    scale: Tuple[float, float, float] = (1.0, 1.0, 1.0),
    location: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: float = 0.0,
) -> Tuple[float, float]:
    sx, sy = float(scale[0]), float(scale[1])
    lx, ly = float(location[0]), float(location[1])
    x = sx * (float(u) - 0.5)
    y = sy * (float(v) - 0.5)
    if abs(rotation) > 1e-8:
        cos_t = math.cos(rotation)
        sin_t = math.sin(rotation)
        x, y = x * cos_t - y * sin_t, x * sin_t + y * cos_t
    return x + lx + 0.5, y + ly + 0.5


# ---------------------------------------------------------------------------
# Public Bridge Functions (delegating to Rust libmtk_py when available)
# ---------------------------------------------------------------------------

def calculate_uv_area(uvs: List[Tuple[float, float]]) -> float:
    if HAS_LIBMTK_UV:
        return mtk_py.calculate_uv_area(uvs)
    return _py_calculate_uv_area(uvs)


def get_uv_bounds(uvs: List[Tuple[float, float]]) -> Tuple[float, float, float, float, float, float]:
    if HAS_LIBMTK_UV:
        return mtk_py.get_uv_bounds(uvs)
    return _py_get_uv_bounds(uvs)


def get_uv_center(uvs: List[Tuple[float, float]]) -> Tuple[float, float]:
    if HAS_LIBMTK_UV:
        return mtk_py.get_uv_center(uvs)
    return _py_get_uv_center(uvs)


def is_uv_collapsed(
    uvs: List[Tuple[float, float]],
    area_threshold: Optional[float] = None,
    dist_threshold: Optional[float] = None,
    pixel_step: Optional[Tuple[float, float]] = None,
) -> bool:
    if HAS_LIBMTK_UV:
        return mtk_py.is_uv_collapsed(uvs, area_threshold, dist_threshold, pixel_step)
    return _py_is_uv_collapsed(uvs, area_threshold, dist_threshold, pixel_step)


def is_orthogonal_angle(angle_rad: float, tolerance: float = 1e-3) -> bool:
    if HAS_LIBMTK_UV:
        return mtk_py.is_orthogonal_angle(angle_rad, tolerance)
    return _py_is_orthogonal_angle(angle_rad, tolerance)


def detect_uv_rotation(uvs: List[Tuple[float, float]], tolerance: float = 1e-3) -> float:
    if HAS_LIBMTK_UV:
        return mtk_py.detect_uv_rotation(uvs, tolerance)
    return _py_detect_uv_rotation(uvs, tolerance)


def straighten_uv(
    uvs: List[Tuple[float, float]],
    angle: Optional[float] = None,
) -> Tuple[float, bool, List[Tuple[float, float]]]:
    if HAS_LIBMTK_UV:
        return mtk_py.straighten_uv(uvs, angle)
    return _py_straighten_uv(uvs, angle)


def scale_uv(uvs: List[Tuple[float, float]], scale_factor: float) -> List[Tuple[float, float]]:
    if HAS_LIBMTK_UV:
        return mtk_py.scale_uv(uvs, scale_factor)
    return _py_scale_uv(uvs, scale_factor)


def normalize_uv_for_atlas_tiling(
    uvs: List[Tuple[float, float]],
    epsilon: float = 1e-6,
) -> Tuple[List[Tuple[float, float]], Tuple[float, float, float], Tuple[float, float, float]]:
    if HAS_LIBMTK_UV:
        return mtk_py.normalize_uv_for_atlas_tiling(uvs, epsilon)
    return _py_normalize_uv_for_atlas_tiling(uvs, epsilon)


def uv_requires_atlas_tiling(uvs: List[Tuple[float, float]], epsilon: float = 1e-4) -> bool:
    if HAS_LIBMTK_UV:
        return mtk_py.uv_requires_atlas_tiling(uvs, epsilon)
    return _py_uv_requires_atlas_tiling(uvs, epsilon)


def restore_atlas_tiling_uv(
    u: float,
    v: float,
    scale: Tuple[float, float, float] = (1.0, 1.0, 1.0),
    location: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: float = 0.0,
) -> Tuple[float, float]:
    if HAS_LIBMTK_UV:
        return mtk_py.restore_atlas_tiling_uv(u, v, scale, location, rotation)
    return _py_restore_atlas_tiling_uv(u, v, scale, location, rotation)

"""
MoziToolKit UV Bridge Module.

Accelerated 2D UV geometric operations backed strictly by Rust libmtk (libmtk_py).
"""

from __future__ import annotations

from typing import List, Optional, Tuple

try:
    import libmtk_py as mtk_py
except ImportError:
    try:
        import mtk_py
    except ImportError:
        mtk_py = None

def _ensure_mtk():
    if mtk_py is None:
        raise RuntimeError(
            "libmtk_py native extension is missing. Please install or compile the extension wheel."
        )


def calculate_uv_area(uvs: List[Tuple[float, float]]) -> float:
    _ensure_mtk()
    return mtk_py.calculate_uv_area(uvs)


def get_uv_bounds(uvs: List[Tuple[float, float]]) -> Tuple[float, float, float, float, float, float]:
    _ensure_mtk()
    return mtk_py.get_uv_bounds(uvs)


def get_uv_center(uvs: List[Tuple[float, float]]) -> Tuple[float, float]:
    _ensure_mtk()
    return mtk_py.get_uv_center(uvs)


def is_uv_collapsed(
    uvs: List[Tuple[float, float]],
    area_threshold: Optional[float] = None,
    dist_threshold: Optional[float] = None,
    pixel_step: Optional[Tuple[float, float]] = None,
) -> bool:
    _ensure_mtk()
    return mtk_py.is_uv_collapsed(uvs, area_threshold, dist_threshold, pixel_step)


def is_orthogonal_angle(angle_rad: float, tolerance: float = 1e-3) -> bool:
    _ensure_mtk()
    return mtk_py.is_orthogonal_angle(angle_rad, tolerance)


def detect_uv_rotation(uvs: List[Tuple[float, float]], tolerance: float = 1e-3) -> float:
    _ensure_mtk()
    return mtk_py.detect_uv_rotation(uvs, tolerance)


def straighten_uv(
    uvs: List[Tuple[float, float]],
    angle: Optional[float] = None,
) -> Tuple[float, bool, List[Tuple[float, float]]]:
    _ensure_mtk()
    return mtk_py.straighten_uv(uvs, angle)


def scale_uv(uvs: List[Tuple[float, float]], scale_factor: float) -> List[Tuple[float, float]]:
    _ensure_mtk()
    return mtk_py.scale_uv(uvs, scale_factor)


def normalize_uv_for_atlas_tiling(
    uvs: List[Tuple[float, float]],
    epsilon: float = 1e-6,
) -> Tuple[List[Tuple[float, float]], Tuple[float, float, float], Tuple[float, float, float]]:
    _ensure_mtk()
    return mtk_py.normalize_uv_for_atlas_tiling(uvs, epsilon)


def uv_requires_atlas_tiling(uvs: List[Tuple[float, float]], epsilon: float = 1e-4) -> bool:
    _ensure_mtk()
    return mtk_py.uv_requires_atlas_tiling(uvs, epsilon)


def restore_atlas_tiling_uv(
    u: float,
    v: float,
    scale: Tuple[float, float, float] = (1.0, 1.0, 1.0),
    location: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: float = 0.0,
) -> Tuple[float, float]:
    _ensure_mtk()
    return mtk_py.restore_atlas_tiling_uv(u, v, scale, location, rotation)


def repair_quad_fluid_uv(
    verts: List[Tuple[float, float, float]],
    uvs: List[Tuple[float, float]],
    normal: Optional[Tuple[float, float, float]] = None,
    force: bool = False,
    min_slope_threshold: float = 0.005,
) -> Tuple[bool, List[Tuple[float, float]]]:
    _ensure_mtk()
    return mtk_py.repair_quad_fluid_uv(verts, uvs, normal, force, min_slope_threshold)


def batch_repair_fluid_uv(
    verts_flat: List[float],
    uvs_flat: List[float],
    normals_flat: Optional[List[float]] = None,
    force: bool = False,
    min_slope_threshold: float = 0.005,
) -> Tuple[int, List[float]]:
    _ensure_mtk()
    return mtk_py.batch_repair_fluid_uv(verts_flat, uvs_flat, normals_flat, force, min_slope_threshold)


def get_fluid_top_uvs(is_flowing: bool = True, rotation: float = 0.0) -> List[Tuple[float, float]]:
    _ensure_mtk()
    return mtk_py.get_fluid_top_uvs(is_flowing, rotation)


def get_fluid_side_uvs(h_left_top: float, h_right_top: float) -> List[Tuple[float, float]]:
    _ensure_mtk()
    return mtk_py.get_fluid_side_uvs(h_left_top, h_right_top)

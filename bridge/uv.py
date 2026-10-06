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


def calculate_uv_area(uvs: List[Tuple[float, float]]) -> float:
    mtk = require_libmtk("calculate_uv_area")
    return mtk.calculate_uv_area(uvs)


def get_uv_bounds(uvs: List[Tuple[float, float]]) -> Tuple[float, float, float, float, float, float]:
    mtk = require_libmtk("get_uv_bounds")
    return mtk.get_uv_bounds(uvs)


def get_uv_center(uvs: List[Tuple[float, float]]) -> Tuple[float, float]:
    mtk = require_libmtk("get_uv_center")
    return mtk.get_uv_center(uvs)


def is_uv_collapsed(
    uvs: List[Tuple[float, float]],
    area_threshold: Optional[float] = None,
    dist_threshold: Optional[float] = None,
    pixel_step: Optional[Tuple[float, float]] = None,
) -> bool:
    mtk = require_libmtk("is_uv_collapsed")
    return mtk.is_uv_collapsed(uvs, area_threshold, dist_threshold, pixel_step)


def is_orthogonal_angle(angle_rad: float, tolerance: float = 1e-3) -> bool:
    mtk = require_libmtk("is_orthogonal_angle")
    return mtk.is_orthogonal_angle(angle_rad, tolerance)


def detect_uv_rotation(uvs: List[Tuple[float, float]], tolerance: float = 1e-3) -> float:
    mtk = require_libmtk("detect_uv_rotation")
    return mtk.detect_uv_rotation(uvs, tolerance)


def straighten_uv(
    uvs: List[Tuple[float, float]],
    angle: Optional[float] = None,
) -> Tuple[float, bool, List[Tuple[float, float]]]:
    mtk = require_libmtk("straighten_uv")
    return mtk.straighten_uv(uvs, angle)


def scale_uv(uvs: List[Tuple[float, float]], scale_factor: float) -> List[Tuple[float, float]]:
    mtk = require_libmtk("scale_uv")
    return mtk.scale_uv(uvs, scale_factor)


def normalize_uv_for_atlas_tiling(
    uvs: List[Tuple[float, float]],
    epsilon: float = 1e-6,
) -> Tuple[List[Tuple[float, float]], Tuple[float, float, float], Tuple[float, float, float]]:
    mtk = require_libmtk("normalize_uv_for_atlas_tiling")
    return mtk.normalize_uv_for_atlas_tiling(uvs, epsilon)


def uv_requires_atlas_tiling(uvs: List[Tuple[float, float]], epsilon: float = 1e-4) -> bool:
    mtk = require_libmtk("uv_requires_atlas_tiling")
    return mtk.uv_requires_atlas_tiling(uvs, epsilon)


def restore_atlas_tiling_uv(
    u: float,
    v: float,
    scale: Tuple[float, float, float] = (1.0, 1.0, 1.0),
    location: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: float = 0.0,
) -> Tuple[float, float]:
    mtk = require_libmtk("restore_atlas_tiling_uv")
    return mtk.restore_atlas_tiling_uv(u, v, scale, location, rotation)


def repair_quad_fluid_uv(
    verts: List[Tuple[float, float, float]],
    uvs: List[Tuple[float, float]],
    normal: Optional[Tuple[float, float, float]] = None,
    force: bool = False,
    min_slope_threshold: float = 0.005,
) -> Tuple[bool, List[Tuple[float, float]]]:
    mtk = require_libmtk("repair_quad_fluid_uv")
    return mtk.repair_quad_fluid_uv(verts, uvs, normal, force, min_slope_threshold)


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


def get_fluid_top_uvs(is_flowing: bool = True, rotation: float = 0.0) -> List[Tuple[float, float]]:
    mtk = require_libmtk("get_fluid_top_uvs")
    return mtk.get_fluid_top_uvs(is_flowing, rotation)


def get_fluid_side_uvs(h_left_top: float, h_right_top: float) -> List[Tuple[float, float]]:
    mtk = require_libmtk("get_fluid_side_uvs")
    return mtk.get_fluid_side_uvs(h_left_top, h_right_top)

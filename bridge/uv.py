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


def scale_uv(uvs: List[Tuple[float, float]], scale_factor: float) -> List[Tuple[float, float]]:
    mtk = require_libmtk("scale_uv")
    return mtk.scale_uv(uvs, scale_factor)


def get_fluid_top_uvs(is_flowing: bool = True, rotation: float = 0.0) -> List[Tuple[float, float]]:
    mtk = require_libmtk("get_fluid_top_uvs")
    return mtk.get_fluid_top_uvs(is_flowing, rotation)


def get_fluid_side_uvs(h_left_top: float, h_right_top: float) -> List[Tuple[float, float]]:
    mtk = require_libmtk("get_fluid_side_uvs")
    return mtk.get_fluid_side_uvs(h_left_top, h_right_top)


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

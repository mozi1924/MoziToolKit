"""
MoziToolKit Subdivide & Pixel Split Bridge Module.

Accelerated quad face pixel-grid subdivision and bilinear attribute interpolation
backed strictly by Rust libmtk (libmtk_py).
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple, Any

from .engine import get_libmtk, require_libmtk


def __getattr__(name: str) -> Any:
    if name == "mtk_py":
        return get_libmtk()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def calculate_face_target_grid(
    uvs: Sequence[Tuple[float, float]],
    tex_w: int,
    tex_h: int,
    pixels_per_face: float = 1.0,
    max_subdivisions: int = 64,
) -> Tuple[int, int]:
    """Calculate target (cols, rows) subdivisions based on UV span and texture pixel density."""
    mtk = require_libmtk("calculate_face_target_grid")
    if not uvs:
        return (1, 1)
    return mtk.unstable.testing.calculate_face_target_grid(
        [tuple(p) for p in uvs], tex_w, tex_h, pixels_per_face, max_subdivisions
    )


def calculate_pixel_grid_cut_factors(
    uvs: Sequence[Tuple[float, float]],
    tex_w: int,
    tex_h: int,
    pixels_per_face: float = 1.0,
    max_subdivisions: int = 64,
) -> Tuple[List[float], List[float]]:
    """Calculate non-uniform cut factors [0, 1] snapping strictly to integer pixel grid lines."""
    mtk = require_libmtk("calculate_pixel_grid_cut_factors")
    if not uvs:
        return ([], [])
    return mtk.unstable.testing.calculate_pixel_grid_cut_factors(
        [tuple(p) for p in uvs], tex_w, tex_h, pixels_per_face, max_subdivisions
    )


def slice_face_by_pixel_grid(
    positions: Sequence[Tuple[float, float, float]],
    uvs: Sequence[Tuple[float, float]],
    tex_w: int,
    tex_h: int,
    pixels_per_face: float = 1.0,
    max_subdivisions: int = 64,
) -> Tuple[List[Tuple[float, float, float]], List[Tuple[float, float]], List[List[int]], List[Tuple[float, float]]]:
    """Slice a 3D/2D polygon strictly along the 2D texture pixel grid lines."""
    mtk = require_libmtk("slice_face_by_pixel_grid")
    pos_list = [list(p) for p in positions]
    uv_list = [list(u) for u in uvs]
    return mtk.unstable.testing.slice_face_by_pixel_grid(
        pos_list, uv_list, tex_w, tex_h, pixels_per_face, max_subdivisions
    )


def adaptive_pixel_split_mesh(
    mesh_data: Any,
    face_resolutions: Optional[List[Optional[Tuple[int, int]]]] = None,
    default_resolution: Tuple[int, int] = (16, 16),
    pixels_per_face: float = 1.0,
    max_subdivisions: int = 64,
    weld_dist: float = 1e-4,
) -> Any:
    """Subdivide quad faces in MeshData according to texture pixel density with full attribute interpolation."""
    mtk = require_libmtk("adaptive_pixel_split_mesh")
    result = mtk.adaptive_pixel_split_mesh(
        mesh_data,
        face_resolutions,
        default_resolution,
        pixels_per_face,
        max_subdivisions,
        weld_dist,
    )
    if getattr(result, "profile", None) is not None:
        from .diagnostics import record_operation_profile

        record_operation_profile("Adaptive Pixel Split", result.profile)
    return result

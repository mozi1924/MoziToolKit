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
    mtk = get_libmtk()
    if mtk and hasattr(mtk, "calculate_face_target_grid") and uvs:
        try:
            return mtk.calculate_face_target_grid(
                [tuple(p) for p in uvs], tex_w, tex_h, pixels_per_face, max_subdivisions
            )
        except Exception:
            pass

    if not uvs:
        return (1, 1)
    min_u = min(p[0] for p in uvs)
    max_u = max(p[0] for p in uvs)
    min_v = min(p[1] for p in uvs)
    max_v = max(p[1] for p in uvs)
    du = max(1e-6, max_u - min_u)
    dv = max(1e-6, max_v - min_v)

    is_vertical_anim = (tex_h >= 2 * tex_w) and (tex_h % tex_w == 0) and (dv > 0.9)
    effective_h = tex_w if is_vertical_anim else tex_h
    effective_w = tex_w

    cols = max(1, min(max_subdivisions, int(round(du * effective_w / pixels_per_face))))
    rows = max(1, min(max_subdivisions, int(round(dv * effective_h / pixels_per_face))))
    return (cols, rows)


def calculate_pixel_grid_cut_factors(
    uvs: Sequence[Tuple[float, float]],
    tex_w: int,
    tex_h: int,
    pixels_per_face: float = 1.0,
    max_subdivisions: int = 64,
) -> Tuple[List[float], List[float]]:
    """Calculate non-uniform cut factors [0, 1] snapping strictly to integer pixel grid lines."""
    mtk = get_libmtk()
    if mtk and hasattr(mtk, "calculate_pixel_grid_cut_factors") and uvs:
        try:
            return mtk.calculate_pixel_grid_cut_factors(
                [tuple(p) for p in uvs], tex_w, tex_h, pixels_per_face, max_subdivisions
            )
        except Exception:
            pass
    cols, rows = calculate_face_target_grid(uvs, tex_w, tex_h, pixels_per_face, max_subdivisions)
    u_factors = [i / cols for i in range(1, cols)]
    v_factors = [i / rows for i in range(1, rows)]
    return (u_factors, v_factors)


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
    return mtk.slice_face_by_pixel_grid(
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

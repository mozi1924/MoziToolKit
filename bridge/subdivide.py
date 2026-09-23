"""
MoziToolKit Subdivide & Pixel Split Bridge Module.

Accelerated quad face pixel-grid subdivision and bilinear attribute interpolation
backed strictly by Rust libmtk (libmtk_py).
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

try:
    import libmtk_py as mtk_py
except ImportError:
    try:
        import mtk_py
    except ImportError:
        mtk_py = None

if mtk_py is None:
    raise ImportError(
        "libmtk_py native extension is missing. Please install the compiled extension wheel."
    )


def calculate_face_target_grid(
    uvs: Sequence[Tuple[float, float]],
    tex_w: int,
    tex_h: int,
    pixels_per_face: float = 1.0,
    max_subdivisions: int = 64,
) -> Tuple[int, int]:
    """Calculate target (cols, rows) subdivisions based on UV span and texture pixel density."""
    uv_list = [tuple(p) for p in uvs]
    return mtk_py.calculate_face_target_grid(
        uv_list, tex_w, tex_h, pixels_per_face, max_subdivisions
    )


def adaptive_pixel_split_mesh(
    mesh_data: mtk_py.MeshData,
    face_resolutions: Optional[List[Optional[Tuple[int, int]]]] = None,
    default_resolution: Tuple[int, int] = (16, 16),
    pixels_per_face: float = 1.0,
    max_subdivisions: int = 64,
    weld_dist: float = 1e-4,
) -> mtk_py.MeshData:
    """Subdivide quad faces in MeshData according to texture pixel density with full attribute interpolation."""
    return mtk_py.adaptive_pixel_split_mesh(
        mesh_data,
        face_resolutions,
        default_resolution,
        pixels_per_face,
        max_subdivisions,
        weld_dist,
    )

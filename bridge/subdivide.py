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

"""
MoziToolKit Texture and Image Bridge Module.

Accelerated texture alpha sampling and transparent face analysis backed strictly by Rust libmtk (libmtk_py).
"""

from __future__ import annotations

from typing import List, Sequence, Tuple, Any

import numpy as np

from .engine import get_libmtk, require_libmtk


def __getattr__(name: str) -> Any:
    if name == "mtk_py":
        return get_libmtk()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def _as_pixel_buffer(pixels: Any) -> Any:
    return pixels if isinstance(pixels, (list, np.ndarray)) else list(pixels)


def batch_analyze_transparent_faces(
    faces_uvs: Sequence[Sequence[Tuple[float, float]]],
    width: int,
    height: int,
    pixels: Sequence[float],
    mode: str = "CENTER",
    threshold: float = 0.01,
    invert_y: bool = False,
) -> List[bool]:
    """Batch evaluate transparency for multiple faces against an RGBA pixel buffer."""
    if not faces_uvs:
        return []
    mtk = require_libmtk("batch_analyze_transparent_faces")
    uvs_nested = [[tuple(p) for p in face] for face in faces_uvs]
    return mtk.batch_analyze_transparent_faces_f32(
        uvs_nested, width, height, _as_pixel_buffer(pixels), mode, threshold, invert_y
    )

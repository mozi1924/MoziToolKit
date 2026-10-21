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


def sample_uv_alpha(
    u: float,
    v: float,
    width: int,
    height: int,
    pixels: Sequence[float],
    invert_y: bool = False,
) -> float:
    """Sample alpha value [0.0, 1.0] at normalized UV coordinate."""
    x = max(0, min(width - 1, int(u * width)))
    y = max(0, min(height - 1, int((1.0 - v if invert_y else v) * height)))
    idx = (y * width + x) * 4 + 3
    return float(pixels[idx]) if idx < len(pixels) else 1.0


def is_face_transparent(
    face_uvs: Sequence[Tuple[float, float]],
    width: int,
    height: int,
    pixels: Sequence[float],
    mode: str = "CENTER",
    threshold: float = 0.01,
    invert_y: bool = False,
) -> bool:
    """Check if a single face is transparent against texture pixels."""
    res = batch_analyze_transparent_faces(
        [face_uvs], width, height, pixels, mode, threshold, invert_y
    )
    return bool(res[0]) if res else False


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

"""
MoziToolKit Texture and Image Bridge Module.

Accelerated texture alpha sampling and transparent face analysis backed strictly by Rust libmtk (libmtk_py).
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

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


def sample_uv_alpha(
    u: float,
    v: float,
    width: int,
    height: int,
    pixels: Sequence[float],
    invert_y: bool = False,
) -> float:
    """Sample alpha value [0.0, 1.0] at normalized UV coordinate."""
    pix_list = list(pixels) if not isinstance(pixels, list) else pixels
    return mtk_py.sample_uv_alpha_f32(u, v, width, height, pix_list, invert_y)


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
    pix_list = list(pixels) if not isinstance(pixels, list) else pixels
    uv_list = [tuple(p) for p in face_uvs]
    return mtk_py.is_face_transparent_f32(uv_list, width, height, pix_list, mode, threshold, invert_y)


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
    pix_list = list(pixels) if not isinstance(pixels, list) else pixels
    uvs_nested = [[tuple(p) for p in face] for face in faces_uvs]
    return mtk_py.batch_analyze_transparent_faces_f32(
        uvs_nested, width, height, pix_list, mode, threshold, invert_y
    )

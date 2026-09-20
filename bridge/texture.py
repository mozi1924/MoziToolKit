"""
MoziToolKit Texture and Image Bridge Module.

Accelerated texture alpha sampling and transparent face analysis backed by Rust libmtk (libmtk_py),
with robust pure-Python fallback implementations when libmtk_py is unavailable.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple, Union

try:
    import libmtk_py as mtk_py
except ImportError:
    try:
        import mtk_py
    except ImportError:
        mtk_py = None

HAS_LIBMTK_ALPHA = mtk_py is not None and hasattr(mtk_py, "batch_analyze_transparent_faces_f32")


# ---------------------------------------------------------------------------
# Pure Python Fallbacks
# ---------------------------------------------------------------------------

def _py_uv_to_pixel_coord(u: float, v: float, width: int, height: int, invert_y: bool = False) -> Tuple[int, int]:
    w = float(width)
    h = float(height)
    px = int(math_floor(u * w)) % width
    target_v = (1.0 - v) if invert_y else v
    py = int(math_floor(target_v * h)) % height
    return px, py


def math_floor(x: float) -> int:
    import math
    return math.floor(x)


def _py_sample_alpha_f32(width: int, height: int, pixels: Sequence[float], u: float, v: float, invert_y: bool = False) -> float:
    if width <= 0 or height <= 0 or len(pixels) < width * height * 4:
        return 1.0
    x, y = _py_uv_to_pixel_coord(u, v, width, height, invert_y)
    idx = (y * width + x) * 4 + 3
    if idx < len(pixels):
        return float(pixels[idx])
    return 1.0


def _py_is_face_transparent_f32(
    face_uvs: Sequence[Tuple[float, float]],
    width: int,
    height: int,
    pixels: Sequence[float],
    mode: str = "CENTER",
    threshold: float = 0.01,
    invert_y: bool = False,
) -> bool:
    if not face_uvs:
        return False

    center_u = sum(p[0] for p in face_uvs) / float(len(face_uvs))
    center_v = sum(p[1] for p in face_uvs) / float(len(face_uvs))
    mode_upper = mode.upper()

    if mode_upper == "CENTER":
        alpha = _py_sample_alpha_f32(width, height, pixels, center_u, center_v, invert_y)
        return alpha <= threshold
    elif mode_upper in ("ALL_CORNERS", "ALLCORNERS", "CORNERS"):
        center_alpha = _py_sample_alpha_f32(width, height, pixels, center_u, center_v, invert_y)
        if center_alpha > threshold:
            return False
        return all(
            _py_sample_alpha_f32(width, height, pixels, u, v, invert_y) <= threshold
            for u, v in face_uvs
        )
    elif mode_upper in ("AVERAGE", "AVG"):
        alphas = [_py_sample_alpha_f32(width, height, pixels, u, v, invert_y) for u, v in face_uvs]
        alphas.append(_py_sample_alpha_f32(width, height, pixels, center_u, center_v, invert_y))
        avg = sum(alphas) / float(len(alphas))
        return avg <= threshold
    else:
        alpha = _py_sample_alpha_f32(width, height, pixels, center_u, center_v, invert_y)
        return alpha <= threshold


def _py_batch_analyze_transparent_faces_f32(
    faces_uvs: Sequence[Sequence[Tuple[float, float]]],
    width: int,
    height: int,
    pixels: Sequence[float],
    mode: str = "CENTER",
    threshold: float = 0.01,
    invert_y: bool = False,
) -> List[bool]:
    return [
        _py_is_face_transparent_f32(uvs, width, height, pixels, mode, threshold, invert_y)
        for uvs in faces_uvs
    ]


# ---------------------------------------------------------------------------
# Public Bridge Functions
# ---------------------------------------------------------------------------

def sample_uv_alpha(
    u: float,
    v: float,
    width: int,
    height: int,
    pixels: Sequence[float],
    invert_y: bool = False,
) -> float:
    """Sample alpha value [0.0, 1.0] at normalized UV coordinate."""
    if HAS_LIBMTK_ALPHA:
        # Convert to list if needed
        pix_list = list(pixels) if not isinstance(pixels, list) else pixels
        return mtk_py.sample_uv_alpha_f32(u, v, width, height, pix_list, invert_y)
    return _py_sample_alpha_f32(width, height, pixels, u, v, invert_y)


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
    if HAS_LIBMTK_ALPHA:
        pix_list = list(pixels) if not isinstance(pixels, list) else pixels
        uv_list = [tuple(p) for p in face_uvs]
        return mtk_py.is_face_transparent_f32(uv_list, width, height, pix_list, mode, threshold, invert_y)
    return _py_is_face_transparent_f32(face_uvs, width, height, pixels, mode, threshold, invert_y)


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

    if HAS_LIBMTK_ALPHA:
        pix_list = list(pixels) if not isinstance(pixels, list) else pixels
        uvs_nested = [[tuple(p) for p in face] for face in faces_uvs]
        return mtk_py.batch_analyze_transparent_faces_f32(
            uvs_nested, width, height, pix_list, mode, threshold, invert_y
        )
    return _py_batch_analyze_transparent_faces_f32(faces_uvs, width, height, pixels, mode, threshold, invert_y)

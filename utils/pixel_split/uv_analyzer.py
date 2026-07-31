from typing import Tuple
from .types import TargetGrid
from ..uv import get_face_uv_bounds, get_image_from_face


def get_texture_resolution_for_face(face, obj, context, default_res: Tuple[int, int] = (64, 64)) -> Tuple[int, int]:
    """Retrieve texture width and height associated with a face's material."""
    img = get_image_from_face(face, obj, context)
    if img and img.size[0] > 0 and img.size[1] > 0:
        return (int(img.size[0]), int(img.size[1]))
    return default_res


def calculate_face_target_grid(
    face,
    uv_layer,
    tex_w: int,
    tex_h: int,
    pixels_per_face: int = 1
) -> TargetGrid:
    """Determine horizontal and vertical subdivision counts to match texture pixel resolution."""
    if len(face.loops) == 4:
        uv0 = face.loops[0][uv_layer].uv
        uv1 = face.loops[1][uv_layer].uv
        uv3 = face.loops[3][uv_layer].uv

        len_01 = ((abs(uv1.x - uv0.x) * tex_w) ** 2 + (abs(uv1.y - uv0.y) * tex_h) ** 2) ** 0.5
        len_03 = ((abs(uv3.x - uv0.x) * tex_w) ** 2 + (abs(uv3.y - uv0.y) * tex_h) ** 2) ** 0.5

        cols = max(1, int(round(len_01 / max(1, pixels_per_face))))
        rows = max(1, int(round(len_03 / max(1, pixels_per_face))))
    else:
        bounds = get_face_uv_bounds(face, uv_layer)
        cols = max(1, int(round((bounds.width * tex_w) / max(1, pixels_per_face))))
        rows = max(1, int(round((bounds.height * tex_h) / max(1, pixels_per_face))))

    return TargetGrid(cols=cols, rows=rows, tex_w=tex_w, tex_h=tex_h)


from typing import Tuple
from .types import UVBounds, TargetGrid
from ..uv import get_image_from_face


def get_face_uv_bounds(face, uv_layer) -> UVBounds:
    """Calculate min/max UV coordinates for a face."""
    if not face.loops:
        return UVBounds(0.0, 0.0, 0.0, 0.0)

    u_coords = [loop[uv_layer].uv.x for loop in face.loops]
    v_coords = [loop[uv_layer].uv.y for loop in face.loops]

    return UVBounds(
        min_u=min(u_coords),
        max_u=max(u_coords),
        min_v=min(v_coords),
        max_v=max(v_coords),
    )


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
    bounds = get_face_uv_bounds(face, uv_layer)

    cols = max(1, int(round((bounds.width * tex_w) / max(1, pixels_per_face))))
    rows = max(1, int(round((bounds.height * tex_h) / max(1, pixels_per_face))))

    return TargetGrid(cols=cols, rows=rows, tex_w=tex_w, tex_h=tex_h)

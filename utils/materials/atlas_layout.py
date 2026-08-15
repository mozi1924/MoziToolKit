"""
Shared coordinate rules for baked-UV and shader atlas paths.
"""

from __future__ import annotations
from .constants import FACE_ORDER


def face_index_from_normal(normal) -> int:
    """Return the atlas face index for a Blender object-space face normal.

    Minecraft's vertical Y axis corresponds to Blender Z. The fallback is
    +X, matching the shader node group and making the result deterministic for
    degenerate/smoothed faces.
    """
    if normal.x < -0.5:
        return 1
    if normal.z > 0.5:
        return 2
    if normal.z < -0.5:
        return 3
    if normal.y > 0.5:
        return 4
    if normal.y < -0.5:
        return 5
    return 0


def static_cell(material_id: int, face_index: int, material_columns: int) -> tuple[int, int]:
    """Return the atlas tile column and top-origin row for a static face."""
    material_columns = max(1, int(material_columns))
    material_id = max(0, int(material_id))
    return ((material_id % material_columns) * 6 + int(face_index),
            material_id // material_columns)


def chunk_cell(texture_id: int, tiles_per_row: int) -> tuple[int, int]:
    """Return the tile column and top-origin row inside one atlas chunk."""
    tiles_per_row = max(1, int(tiles_per_row))
    texture_id = max(0, int(texture_id))
    return texture_id % tiles_per_row, texture_id // tiles_per_row


def atlas_uv_from_local(
    u: float,
    v: float,
    *,
    tile_column: int,
    tile_row: int,
    tile_size: float,
    atlas_width: float,
    atlas_height: float,
) -> tuple[float, float]:
    """Map a source texture UV directly into one top-origin atlas cell.

    This deliberately does not apply ``fract``: a quad's 0..1 UV span must
    remain continuous after it is written back to the mesh. The shader path
    uses ``fract`` separately so procedural UVs can repeat inside one cell.
    """
    return (
        (tile_column + u) * tile_size / atlas_width,
        1.0 - (tile_row + 1.0 - v) * tile_size / atlas_height,
    )


def atlas_uv_from_rect(
    u: float,
    v: float,
    *,
    pixel_x: float,
    pixel_y: float,
    rect_width: float,
    rect_height: float,
    atlas_width: float,
    atlas_height: float,
) -> tuple[float, float]:
    """Map UVs into an arbitrary top-origin atlas rectangle.

    Animation chunks use this for their first frame: each source animation is
    a full-height vertical strip, but preview samples only its top frame.
    """
    return (
        (pixel_x + u * rect_width) / atlas_width,
        1.0 - (pixel_y + (1.0 - v) * rect_height) / atlas_height,
    )


def local_uv_from_atlas(
    u_atlas: float,
    v_atlas: float,
    *,
    tile_column: int,
    tile_row: int,
    tile_size: float,
    atlas_width: float,
    atlas_height: float,
) -> tuple[float, float]:
    """Convert an atlas UV coordinate back to its local 0..1 texture UV space.

    Inverts ``atlas_uv_from_local`` precisely.
    """
    if tile_size <= 0.0 or atlas_width <= 0.0 or atlas_height <= 0.0:
        return u_atlas, v_atlas
    u = (u_atlas * atlas_width) / tile_size - float(tile_column)
    v = 1.0 - (((1.0 - v_atlas) * atlas_height) / tile_size - float(tile_row))
    return u, v


def local_uv_from_rect(
    u_atlas: float,
    v_atlas: float,
    *,
    pixel_x: float,
    pixel_y: float,
    rect_width: float,
    rect_height: float,
    atlas_width: float,
    atlas_height: float,
) -> tuple[float, float]:
    """Convert an atlas rectangle UV coordinate back to its local 0..1 UV space.

    Inverts ``atlas_uv_from_rect`` precisely.
    """
    if rect_width <= 0.0 or rect_height <= 0.0 or atlas_width <= 0.0 or atlas_height <= 0.0:
        return u_atlas, v_atlas
    u = (u_atlas * atlas_width - float(pixel_x)) / float(rect_width)
    v = 1.0 - ((1.0 - v_atlas) * atlas_height - float(pixel_y)) / float(rect_height)
    return u, v


def find_texture_id_from_atlas_uv(
    u_atlas: float,
    v_atlas: float,
    chunk: dict,
    animations_in_chunk: list[dict] | None = None,
) -> int:
    """Determine the texture_id in a chunk from a representative atlas UV coordinate.

    Useful for recovering texture identity on meshes where custom face attributes were stripped.
    """
    kind = chunk.get("kind", "static")
    atlas_w = float(chunk.get("width", 16))
    atlas_h = float(chunk.get("height", 16))

    if kind == "animation":
        if animations_in_chunk:
            for anim in animations_in_chunk:
                px = float(anim.get("pixel_x", 0))
                pw = float(anim.get("frame_width", 16))
                u_min = px / atlas_w
                u_max = (px + pw) / atlas_w
                if u_min - 1e-5 <= u_atlas <= u_max + 1e-5:
                    return int(anim.get("texture_id", 0))
        return 0

    tile_size = float(chunk.get("tile_size", 16))
    tiles_per_row = max(1, int(chunk.get("tiles_per_row", 1)))
    col = max(0, min(tiles_per_row - 1, int(u_atlas * atlas_w // tile_size)))
    row = max(0, int((1.0 - v_atlas) * atlas_h // tile_size))
    return row * tiles_per_row + col

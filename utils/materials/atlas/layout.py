"""
Shared coordinate rules for baked-UV and shader atlas paths.
"""

from __future__ import annotations
from typing import Optional, Tuple
from ..constants import FACE_ORDER


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


def remap_uv_to_local(
    u: float,
    v: float,
    orig_mode: str,
    old_loc: Optional[dict] = None,
    old_chunk: Optional[dict] = None,
    old_anim_info: Optional[dict] = None,
) -> tuple[float, float]:
    """Invert an incoming UV coordinate from Atlas or Standalone Animation space back to local [0, 1]."""
    if orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_chunk:
        packing = old_loc.get("packing") or old_chunk.get("packing", "grid")
        if old_loc.get("kind") == "animation" or packing in ("rect_bin_pack", "rect") or "pixel_x" in old_loc:
            rect_w = float(old_loc.get("rect_width") or old_loc.get("frame_width") or old_loc.get("tile_size", 16))
            rect_h = float(old_loc.get("rect_height") or old_loc.get("frame_height") or old_loc.get("tile_size", 16))
            return local_uv_from_rect(
                u, v,
                pixel_x=float(old_loc.get("pixel_x", 0)),
                pixel_y=float(old_loc.get("pixel_y", 0)),
                rect_width=rect_w,
                rect_height=rect_h,
                atlas_width=float(old_chunk.get("width", 16)),
                atlas_height=float(old_chunk.get("height", 16)),
            )
        else:
            return local_uv_from_atlas(
                u, v,
                tile_column=int(old_loc.get("tile_column", 0)),
                tile_row=int(old_loc.get("tile_row", 0)),
                tile_size=float(old_chunk.get("tile_size", 16)),
                atlas_width=float(old_chunk.get("width", 16)),
                atlas_height=float(old_chunk.get("height", 16)),
            )
    elif orig_mode == "MINEWAYS_ATLAS" and old_loc:
        from ..matching.mineways_atlas import remap_mineways_atlas_uv_to_local
        img_w = int(old_loc.get("width", 1024))
        img_h = int(old_loc.get("height", 1024))
        return remap_mineways_atlas_uv_to_local(u, v, image_width=img_w, image_height=img_h)
    elif old_anim_info:
        return local_uv_from_rect(
            u, v,
            pixel_x=0.0,
            pixel_y=0.0,
            rect_width=float(old_anim_info["frame_width"]),
            rect_height=float(old_anim_info["frame_height"]),
            atlas_width=float(old_anim_info["img_width"]),
            atlas_height=float(old_anim_info["img_height"]),
        )
    return u, v


def remap_local_to_target_uv(
    u_local: float,
    v_local: float,
    target_location: Optional[dict] = None,
    target_chunk: Optional[dict] = None,
    target_anim_info: Optional[dict] = None,
) -> tuple[float, float]:
    """Project a local [0, 1] UV coordinate to target Atlas Chunk or Standalone Animation Frame 0 space."""
    if target_location and target_chunk:
        packing = target_location.get("packing") or target_chunk.get("packing", "grid")
        if target_location.get("kind") == "animation" or packing in ("rect_bin_pack", "rect") or "pixel_x" in target_location:
            rect_w = float(target_location.get("rect_width") or target_location.get("frame_width") or target_location.get("tile_size", 16))
            rect_h = float(target_location.get("rect_height") or target_location.get("frame_height") or target_location.get("tile_size", 16))
            return atlas_uv_from_rect(
                u_local, v_local,
                pixel_x=float(target_location.get("pixel_x", 0)),
                pixel_y=float(target_location.get("pixel_y", 0)),
                rect_width=rect_w,
                rect_height=rect_h,
                atlas_width=float(target_chunk.get("width", 16)),
                atlas_height=float(target_chunk.get("height", 16)),
            )
        else:
            return atlas_uv_from_local(
                u_local, v_local,
                tile_column=int(target_location.get("tile_column", 0)),
                tile_row=int(target_location.get("tile_row", 0)),
                tile_size=float(target_chunk.get("tile_size", 16)),
                atlas_width=float(target_chunk.get("width", 16)),
                atlas_height=float(target_chunk.get("height", 16)),
            )
    elif target_anim_info:
        return atlas_uv_from_rect(
            u_local, v_local,
            pixel_x=0.0,
            pixel_y=0.0,
            rect_width=float(target_anim_info["frame_width"]),
            rect_height=float(target_anim_info["frame_height"]),
            atlas_width=float(target_anim_info["img_width"]),
            atlas_height=float(target_anim_info["img_height"]),
        )
    return u_local, v_local


def remap_uv_coordinate(
    u: float,
    v: float,
    orig_mode: str,
    old_loc: Optional[dict] = None,
    old_chunk: Optional[dict] = None,
    old_anim_info: Optional[dict] = None,
    target_location: Optional[dict] = None,
    target_chunk: Optional[dict] = None,
    target_anim_info: Optional[dict] = None,
) -> tuple[float, float]:
    """Unified two-way UV remapping: incoming UV -> local [0, 1] -> target UV space."""
    u_loc, v_loc = remap_uv_to_local(
        u, v,
        orig_mode=orig_mode,
        old_loc=old_loc,
        old_chunk=old_chunk,
        old_anim_info=old_anim_info,
    )
    return remap_local_to_target_uv(
        u_loc, v_loc,
        target_location=target_location,
        target_chunk=target_chunk,
        target_anim_info=target_anim_info,
    )

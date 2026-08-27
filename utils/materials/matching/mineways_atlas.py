"""
Mineways Texture Atlas decoder, tile table, and UV un-scrambler.
Decodes Mineways merged terrain atlas (e.g. terrainRGB.png, <name>-RGB.png, <name>-RGBA.png)
to canonical Minecraft texture names and restores local [0, 1] UVs.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple, List, Dict

try:
    import bpy
except ImportError:
    bpy = None

from ..pipeline.provenance import without_blender_suffix
from .mineways_table import (
    MINEWAYS_ATLAS_NAME_PATTERNS,
    MINEWAYS_ATLAS_SUFFIX_PATTERNS,
    MINEWAYS_TILES_TABLE,
)

__all__ = [
    "MINEWAYS_ATLAS_NAME_PATTERNS",
    "MINEWAYS_ATLAS_SUFFIX_PATTERNS",
    "MINEWAYS_TILES_TABLE",
    "is_mineways_atlas_image",
    "find_mineways_atlas_image",
    "is_mineways_atlas_material",
    "decode_mineways_face_uv",
    "remap_mineways_atlas_uv_to_local",
]


def is_mineways_atlas_image(image: bpy.types.Image | None) -> bool:
    """Check if an image datablock corresponds to a Mineways exported texture atlas."""
    if not image:
        return False
    raw_name = (image.name or "").strip().lower()
    filepath = (image.filepath or "").replace("\\", "/").strip().lower()
    
    # Strip extensions and blender suffixes
    clean_name = without_blender_suffix(raw_name).removesuffix(".png").removesuffix(".jpg")
    fp_stem = without_blender_suffix(filepath.split("/")[-1]).removesuffix(".png").removesuffix(".jpg") if filepath else ""
    
    for candidate in (clean_name, fp_stem):
        if not candidate:
            continue
        if any(candidate == pat or candidate.startswith(pat) for pat in MINEWAYS_ATLAS_NAME_PATTERNS):
            return True
        if any(candidate.endswith(suf) for suf in MINEWAYS_ATLAS_SUFFIX_PATTERNS):
            return True
    return False


def find_mineways_atlas_image(mat: bpy.types.Material | None) -> bpy.types.Image | None:
    """Find the Mineways atlas image node inside a material."""
    if not mat or not mat.use_nodes or not mat.node_tree:
        return None
    for node in mat.node_tree.nodes:
        if node.type == "TEX_IMAGE" and node.image:
            if is_mineways_atlas_image(node.image):
                return node.image
    return None


def is_mineways_atlas_material(mat: bpy.types.Material | None) -> bool:
    """Return True if the material uses a Mineways terrain texture atlas."""
    if not mat:
        return False
    if mat.get("mtk:source_importer") == "mineways" and find_mineways_atlas_image(mat):
        return True
    return find_mineways_atlas_image(mat) is not None


def decode_mineways_face_uv(
    polygon: bpy.types.MeshPolygon,
    uv_layer: bpy.types.MeshUVLoopLayer,
    image: bpy.types.Image | None = None,
    image_size: Optional[Tuple[int, int]] = None,
) -> Tuple[Optional[str], Optional[str], List[Tuple[float, float]]]:
    """
    Decode a polygon mapped to a Mineways texture atlas.
    Returns (primary_texture_name, alt_texture_name, local_uvs_list).
    """
    if not polygon or not uv_layer or not polygon.loop_indices:
        return None, None, []

    tex_w, tex_h = 1024, 1024
    if image and image.size[0] > 0 and image.size[1] > 0:
        tex_w, tex_h = int(image.size[0]), int(image.size[1])
    elif image_size and image_size[0] > 0 and image_size[1] > 0:
        tex_w, tex_h = int(image_size[0]), int(image_size[1])

    u_coords = [uv_layer.data[li].uv.x for li in polygon.loop_indices]
    v_coords = [uv_layer.data[li].uv.y for li in polygon.loop_indices]
    u_center = sum(u_coords) / len(u_coords)
    v_center = sum(v_coords) / len(v_coords)

    # Standard Mineways tile calculation (swatchSize = 18 for 16x16 tile with 1px border)
    swatch_size = 18
    tile_size = 16.0
    border = 1.0
    swatches_per_row = max(1, tex_w // swatch_size)

    px = u_center * float(tex_w)
    py = (1.0 - v_center) * float(tex_h)

    atlas_col = int(px) // swatch_size
    atlas_row = int(py) // swatch_size
    swatch_id = atlas_col + atlas_row * swatches_per_row

    tile_entry = MINEWAYS_TILES_TABLE.get(swatch_id)
    primary_name = None
    alt_name = None
    if tile_entry:
        _tx, _ty, primary_name, alt_name = tile_entry
        # Strip leading MWO_ or MW_ internal prefixes
        if primary_name.startswith("MWO_"):
            primary_name = primary_name[4:]
        elif primary_name.startswith("MW_"):
            primary_name = primary_name[3:]
        if alt_name and alt_name.startswith("MWO_"):
            alt_name = alt_name[4:]
        elif alt_name and alt_name.startswith("MW_"):
            alt_name = alt_name[3:]

    local_uvs = []
    for li in polygon.loop_indices:
        u = uv_layer.data[li].uv.x
        v = uv_layer.data[li].uv.y
        lu = (u * float(tex_w) - (atlas_col * swatch_size + border)) / tile_size
        lv = 1.0 - (((1.0 - v) * float(tex_h) - (atlas_row * swatch_size + border)) / tile_size)
        local_uvs.append((lu, lv))

    return primary_name, alt_name, local_uvs


def remap_mineways_atlas_uv_to_local(
    u: float,
    v: float,
    image_width: int = 1024,
    image_height: int = 1024,
) -> Tuple[float, float]:
    """Convert a single Mineways Atlas UV coordinate to its local [0, 1] swatch coordinate."""
    swatch_size = 18
    tile_size = 16.0
    border = 1.0
    swatches_per_row = max(1, image_width // swatch_size)

    px = u * float(image_width)
    py = (1.0 - v) * float(image_height)

    atlas_col = int(px) // swatch_size
    atlas_row = int(py) // swatch_size

    lu = (u * float(image_width) - (atlas_col * swatch_size + border)) / tile_size
    lv = 1.0 - (((1.0 - v) * float(image_height) - (atlas_row * swatch_size + border)) / tile_size)
    return lu, lv

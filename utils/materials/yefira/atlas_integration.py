"""
MoziToolKit Atlas Material integration and Shader setup for Yefira Blender Plugin.
Manages master Atlas material shader node trees, slot assignment, and parameter extraction.
"""

from __future__ import annotations

import json
import logging
from typing import Optional, Any

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from .face_lut import (
    FACE_ORDER,
    HARDCODED_TINT_BLOCKS,
    _fallback_texture_location,
    _atlas_name_aliases,
    _atlas_short_name,
    _build_block_face_location_lut,
    resolve_block_state_face_locations,
    build_block_face_lut,
    build_block_face_atlas_ids,
    build_block_face_tint_lut,
    build_block_face_anim_lut,
    build_block_face_uv_rot_lut,
    build_block_face_uv_bounds_lut,
)

__all__ = [
    "MASTER_MATERIAL_NAME",
    "FALLBACK_MATERIAL_NAME",
    "FACE_ORDER",
    "HARDCODED_TINT_BLOCKS",
    "_fallback_texture_location",
    "_atlas_name_aliases",
    "_atlas_short_name",
    "_build_block_face_location_lut",
    "resolve_block_state_face_locations",
    "build_block_face_lut",
    "build_block_face_atlas_ids",
    "build_block_face_tint_lut",
    "build_block_face_anim_lut",
    "build_block_face_uv_rot_lut",
    "build_block_face_uv_bounds_lut",
    "find_active_atlas_material",
    "find_bound_atlas_material",
    "parse_atlas_mapping",
    "extract_atlas_parameters",
    "get_or_create_atlas_material",
    "find_all_atlas_chunk_materials",
    "setup_material_slots_for_object",
]

logger = logging.getLogger("Yefira")

MASTER_MATERIAL_NAME = "Yefira_Atlas_Master"
FALLBACK_MATERIAL_NAME = "Yefira_Fallback_PBR"

def find_active_atlas_material() -> Optional[bpy.types.Material]:
    """Find the best active Atlas material in Blender scene."""
    if not HAS_BPY:
        return None

    for mat in bpy.data.materials:
        if not mat:
            continue
        if (
            "mtk:atlas_chunk_id" in mat
            or "mtk_atlas_chunk_id" in mat
            or (mat.name.startswith("mtk:") and ("_chunk_" in mat.name or "chunk_" in mat.name or "atlas_chunk" in mat.name))
        ):
            return mat

    # 2. Second priority: Materials with explicit atlas width/mapping properties
    for mat in bpy.data.materials:
        if not mat:
            continue
        if "mtk_atlas_width" in mat or "mtk:atlas_mapping" in mat or "mtk_atlas_mapping" in mat:
            return mat
        if mat.node_tree and ("mtk:atlas_mapping" in mat.node_tree or "mtk_atlas_mapping" in mat.node_tree):
            return mat

    # 3. Explicit named master materials
    for name in ("MTK_Atlas_Master", "MC_Atlas_Material"):
        if name in bpy.data.materials:
            return bpy.data.materials[name]

    # 4. Fallback to Yefira_Atlas_Master
    if MASTER_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[MASTER_MATERIAL_NAME]

    return None


def find_bound_atlas_material(obj: Optional[bpy.types.Object]) -> Optional[bpy.types.Material]:
    """Return the Atlas material deliberately assigned to a Yefira object.

    ``bpy.data.materials`` is global and iteration order is not a material
    selection policy.  Looking there during every live update could replace a
    freshly applied MoziToolKit atlas with an unrelated chunk from another
    scene/object.  Slot zero is the primary chunk and the authoritative
    source for this world object's dimensions.
    """
    if not obj or not getattr(obj, "data", None):
        return None
    for mat in obj.data.materials:
        if not mat:
            continue
        if (
            "mtk:atlas_mapping" in mat
            or "mtk_atlas_mapping" in mat
            or "mtk:atlas_chunk_id" in mat
            or "mtk_atlas_chunk_id" in mat
        ):
            return mat
    return None


def parse_atlas_mapping(mat: Optional[bpy.types.Material]) -> Optional[dict]:
    """Extract and parse atlas mapping JSON from a material or its node tree."""
    if not mat:
        return None
    raw = None
    for key in ("mtk_atlas_mapping", "mtk:atlas_mapping"):
        if key in mat:
            raw = mat[key]
            break
        if mat.node_tree and key in mat.node_tree:
            raw = mat.node_tree[key]
            break

    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Failed to parse atlas mapping JSON: {e}")
        return None



from ...live_sync.constants import (
    DEFAULT_ATLAS_WIDTH,
    DEFAULT_ATLAS_HEIGHT,
    DEFAULT_TILE_SIZE,
    DEFAULT_TILES_PER_ROW,
    DEFAULT_ANIM_ATLAS_WIDTH,
    DEFAULT_ANIM_ATLAS_HEIGHT,
    DEFAULT_ANIM_FRAME_WIDTH,
    DEFAULT_ANIM_FRAME_HEIGHT,
)


def extract_atlas_parameters(
    mat: Optional[bpy.types.Material] = None,
    pack_stack: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Extract complete Atlas parameters: width, height, tile_size, tiles_per_row, chunk dimensions and LUTs.
    Prioritizes loading authoritative mapping from the active Resource Pack Stack baked cache.
    """
    from ..pipeline.provenance import get_effective_pack_hash, is_material_hash_valid

    if mat is None:
        mat = find_active_atlas_material()

    target_pack_hash = ""
    if pack_stack is None:
        try:
            from ..pack.pack_stack import get_configured_pack_stack
            pack_stack = get_configured_pack_stack()
        except Exception:
            pack_stack = None

    if pack_stack:
        target_pack_hash = get_effective_pack_hash(pack_stack)

    # 1. Authoritative mapping lookup from active precompiled cache directory
    mapping = None
    if pack_stack and target_pack_hash:
        baked_atlas_dir = None
        try:
            from ..pack.resource_pack import get_cache_dir
            cache_root = get_cache_dir()
            for cand in (
                cache_root / target_pack_hash / "yefira_world",
                cache_root / target_pack_hash / "full_scene",
                cache_root / target_pack_hash,
            ):
                if cand.exists() and (cand / "atlas_mapping.json").exists():
                    baked_atlas_dir = cand
                    break
        except Exception:
            pass

        if baked_atlas_dir:
            try:
                with open(baked_atlas_dir / "atlas_mapping.json", "r", encoding="utf-8") as f:
                    mapping = json.load(f)
            except Exception:
                mapping = None

    if mapping is None and mat:
        mapping = parse_atlas_mapping(mat)

    res = {
        "material": mat,
        "pack_hash": target_pack_hash or (get_effective_pack_hash(mat) if mat else ""),
        "width": DEFAULT_ATLAS_WIDTH,
        "height": DEFAULT_ATLAS_HEIGHT,
        "tile_size": DEFAULT_TILE_SIZE,
        "tiles_per_row": DEFAULT_TILES_PER_ROW,
        "chunk_0_width": DEFAULT_ATLAS_WIDTH,
        "chunk_0_height": DEFAULT_ATLAS_HEIGHT,
        "chunk_0_tile_size": DEFAULT_TILE_SIZE,
        "chunk_0_tiles_per_row": float(DEFAULT_TILES_PER_ROW),
        "chunk_1_width": DEFAULT_ANIM_ATLAS_WIDTH,
        "chunk_1_height": DEFAULT_ANIM_ATLAS_HEIGHT,
        "chunk_1_tile_size": DEFAULT_ANIM_FRAME_WIDTH,
        "anim_atlas_width": DEFAULT_ANIM_ATLAS_WIDTH,
        "anim_atlas_height": DEFAULT_ANIM_ATLAS_HEIGHT,
        "anim_frame_width": DEFAULT_ANIM_FRAME_WIDTH,
        "anim_frame_height": DEFAULT_ANIM_FRAME_HEIGHT,
        "mapping": mapping,
        "block_face_lut": {},
        "block_face_chunk_lut": {},
        "block_face_texture_lut": {},
        "block_face_tint_lut": {},
        "block_face_anim_timing_lut": {},
        "block_face_anim_frame_size_lut": {},
        "material_id_map": {},
    }

    if not mat and not mapping:
        return res

    if mat:
        if "mtk_atlas_width" in mat:
            res["width"] = float(mat["mtk_atlas_width"])
        if "mtk_atlas_height" in mat:
            res["height"] = float(mat["mtk_atlas_height"])
        if "mtk_tile_size" in mat:
            res["tile_size"] = float(mat["mtk_tile_size"])
        if "mtk_tiles_per_row" in mat:
            res["tiles_per_row"] = int(mat["mtk_tiles_per_row"])

    if mapping:
        if "tile_size" in mapping and "mtk_tile_size" not in mat:
            res["tile_size"] = float(mapping["tile_size"])
        chunks = mapping.get("chunks", [])
        chunks_by_id = {c.get("chunk_id", i): c for i, c in enumerate(chunks)}

        # Dynamically find the primary static chunk (prefer category == "blocks", else any static chunk, else chunk 0)
        static_chunks = [c for c in chunks if c.get("kind") == "static"]
        block_static = next((c for c in static_chunks if c.get("category") == "blocks"), None)
        if not block_static and static_chunks:
            block_static = static_chunks[0]
        elif not block_static and 0 in chunks_by_id:
            block_static = chunks_by_id[0]

        if block_static:
            res["chunk_0_width"] = float(block_static.get("width", res["width"]))
            res["chunk_0_height"] = float(block_static.get("height", res["height"]))
            res["chunk_0_tile_size"] = float(block_static.get("tile_size", res["tile_size"]))
            res["chunk_0_tiles_per_row"] = float(block_static.get("tiles_per_row", res["tiles_per_row"]))
            res["width"] = res["chunk_0_width"]
            res["height"] = res["chunk_0_height"]
            res["tile_size"] = res["chunk_0_tile_size"]
            res["tiles_per_row"] = int(res["chunk_0_tiles_per_row"])

        # Dynamically find animation chunk (kind == "animation")
        anim_chunk = next((c for c in chunks if c.get("kind") == "animation"), None)
        if not anim_chunk and 1 in chunks_by_id and chunks_by_id[1].get("kind") == "animation":
            anim_chunk = chunks_by_id[1]

        if anim_chunk:
            res["anim_atlas_width"] = float(anim_chunk.get("width", 896.0))
            res["anim_atlas_height"] = float(anim_chunk.get("height", 1024.0))
            res["anim_frame_width"] = float(anim_chunk.get("tile_size", res["tile_size"]))
            res["anim_frame_height"] = float(anim_chunk.get("tile_size", res["tile_size"]))
            # Also keep chunk_1 for backward compat
            res["chunk_1_width"] = res["anim_atlas_width"]
            res["chunk_1_height"] = res["anim_atlas_height"]
            res["chunk_1_tile_size"] = res["anim_frame_width"]
        elif 1 in chunks_by_id:
            c1 = chunks_by_id[1]
            res["chunk_1_width"] = float(c1.get("width", 896.0))
            res["chunk_1_height"] = float(c1.get("height", 1024.0))
            res["chunk_1_tile_size"] = float(c1.get("tile_size", 16.0))

        face_lut, mat_id_map = build_block_face_lut(mapping)
        face_chunk_lut, face_texture_lut = build_block_face_atlas_ids(mapping)
        face_tint_lut = build_block_face_tint_lut(mapping)
        anim_timing_lut, anim_frame_size_lut = build_block_face_anim_lut(mapping)
        face_uv_rot_lut = build_block_face_uv_rot_lut(mapping)
        face_uv_bounds_lut = build_block_face_uv_bounds_lut(mapping)

        res["block_face_lut"] = face_lut
        res["block_face_chunk_lut"] = face_chunk_lut
        res["block_face_texture_lut"] = face_texture_lut
        res["block_face_tint_lut"] = face_tint_lut
        res["block_face_anim_timing_lut"] = anim_timing_lut
        res["block_face_anim_frame_size_lut"] = anim_frame_size_lut
        res["block_face_uv_rot_lut"] = face_uv_rot_lut
        res["block_face_uv_bounds_lut"] = face_uv_bounds_lut
        res["material_id_map"] = mat_id_map

    return res


def get_or_create_atlas_material() -> Optional[bpy.types.Material]:
    """
    Get existing active Atlas Master Material or create a unified Yefira Atlas Master.
    """
    if not HAS_BPY:
        return None

    active = find_active_atlas_material()
    if active:
        return active

    if MASTER_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[MASTER_MATERIAL_NAME]

    # Build default unified Atlas Master material
    mat = bpy.data.materials.new(name=MASTER_MATERIAL_NAME)
    mat.use_nodes = True
    mat.use_fake_user = False
    mat["mtk_atlas_width"] = 1024.0
    mat["mtk_atlas_height"] = 1024.0
    mat["mtk_tile_size"] = 16.0
    mat["mtk_tiles_per_row"] = 64

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Output Node
    output_node = nodes.new(type='ShaderNodeOutputMaterial')
    output_node.location = (600, 0)

    # Principled BSDF
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.location = (300, 0)
    links.new(bsdf.outputs['BSDF'], output_node.inputs['Surface'])

    if 'Roughness' in bsdf.inputs:
        bsdf.inputs['Roughness'].default_value = 0.8

    # Shared Texture Coordinate Node
    tex_coord = nodes.new(type='ShaderNodeTexCoord')
    tex_coord.location = (-600, 100)

    # Albedo Image Texture Node
    tex_image = nodes.new(type='ShaderNodeTexImage')
    tex_image.name = "Atlas Albedo"
    tex_image.interpolation = "Closest"
    tex_image.extension = "CLIP"
    tex_image.location = (-350, 200)
    links.new(tex_coord.outputs['UV'], tex_image.inputs['Vector'])

    # Auto-bind existing atlas image from blender data if available
    atlas_img = None
    for img in bpy.data.images:
        if "atlas_chunk" in img.name and "albedo" in img.name:
            atlas_img = img
            break
        elif "atlas_albedo" in img.name:
            atlas_img = img
            break
    if atlas_img:
        tex_image.image = atlas_img

    # Attribute Node: Biome Tint Color
    attr_tint = nodes.new(type='ShaderNodeAttribute')
    attr_tint.name = "Attr Biome Tint Color"
    attr_tint.attribute_name = "mtk_biome_tint_color"
    attr_tint.location = (-350, -50)

    # Attribute Node: Biome Tint Data
    attr_data = nodes.new(type='ShaderNodeAttribute')
    attr_data.name = "Attr Biome Tint Data"
    attr_data.attribute_name = "mtk_biome_tint_data"
    attr_data.location = (-350, -250)

    # Mix Color Node (Multiply Tint with Base)
    mix_node = nodes.new(type='ShaderNodeMix')
    mix_node.data_type = 'RGBA'
    mix_node.blend_type = 'MULTIPLY'
    mix_node.inputs[0].default_value = 1.0  # Factor
    mix_node.location = (-50, 100)

    links.new(tex_image.outputs['Color'], mix_node.inputs[6]) # Color A
    links.new(attr_tint.outputs['Color'], mix_node.inputs[7]) # Color B

    links.new(mix_node.outputs[2], bsdf.inputs['Base Color'])
    links.new(tex_image.outputs['Alpha'], bsdf.inputs['Alpha'])

    for n in nodes:
        n.select = False
    nodes.active = tex_image
    tex_image.select = True

    return mat


def find_all_atlas_chunk_materials(
    mapping: Optional[dict] = None,
    bound_material: Optional[bpy.types.Material] = None,
    obj: Optional[bpy.types.Object] = None,
) -> dict[int, bpy.types.Material]:
    """Find all Atlas chunk materials in Blender data, keyed by chunk_id.

    Prioritizes materials matching the bound material's pack hash / mapping
    or currently assigned to obj.data.materials to prevent stale materials from
    previous replacements polluting the material dispatcher.
    """
    if not HAS_BPY:
        return {}

    from ..pipeline.provenance import get_effective_pack_hash, is_material_hash_valid

    chunk_materials: dict[int, bpy.types.Material] = {}

    if bound_material is None and obj is not None:
        bound_material = find_bound_atlas_material(obj)

    target_pack_hash = None
    target_uv_source = None
    if bound_material:
        target_pack_hash = get_effective_pack_hash(bound_material)
        target_uv_source = bound_material.get("mtk:atlas_uv_source")
        # Direct chunk 0 binding if valid
        for key in ("mtk:atlas_chunk_id", "mtk_atlas_chunk_id"):
            if key in bound_material:
                try:
                    cid0 = int(bound_material[key])
                    if not target_pack_hash or is_material_hash_valid(bound_material, target_pack_hash):
                        chunk_materials[cid0] = bound_material
                    break
                except (ValueError, TypeError):
                    pass
        if not chunk_materials and (not target_pack_hash or is_material_hash_valid(bound_material, target_pack_hash)):
            chunk_materials[0] = bound_material

    # 1. First priority: Check materials already assigned to object material slots
    if obj and getattr(obj, "data", None) and hasattr(obj.data, "materials"):
        for slot_idx, slot_mat in enumerate(obj.data.materials):
            if not slot_mat:
                continue
            if target_pack_hash and not is_material_hash_valid(slot_mat, target_pack_hash):
                continue
            slot_cid = None
            for key in ("mtk:atlas_chunk_id", "mtk_atlas_chunk_id"):
                if key in slot_mat:
                    try:
                        slot_cid = int(slot_mat[key])
                        break
                    except (ValueError, TypeError):
                        pass
            if slot_cid is None and ("_chunk_" in slot_mat.name or "atlas_chunk_" in slot_mat.name):
                import re
                m = re.search(r"(?:atlas_)?(?:[a-z_]+_)?chunk_(\d+)", slot_mat.name)
                if m:
                    slot_cid = int(m.group(1))

            if slot_cid is not None:
                if slot_cid not in chunk_materials:
                    chunk_materials[slot_cid] = slot_mat

    # Sort materials to prefer ones specialized with :attr:UVMap or :attr:
    mats_sorted = sorted(
        [m for m in bpy.data.materials if m],
        key=lambda m: (
            0 if ":attr:UVMap" in m.name else (1 if ":attr:" in m.name else 2)
        )
    )

    # 2. Match materials in bpy.data.materials filtering by target pack hash & UV source
    for mat in mats_sorted:
        mat_hash = get_effective_pack_hash(mat)
        mat_uv = mat.get("mtk:atlas_uv_source")

        # Skip materials from a different resource pack hash or invalid node tree
        if target_pack_hash and not is_material_hash_valid(mat, target_pack_hash):
            continue
        # Skip materials with different UV source when target UV source is specified
        if target_uv_source and mat_uv and mat_uv != target_uv_source:
            continue

        cid = None
        for key in ("mtk:atlas_chunk_id", "mtk_atlas_chunk_id"):
            if key in mat:
                try:
                    cid = int(mat[key])
                    break
                except (ValueError, TypeError):
                    pass

        if cid is None and ("_chunk_" in mat.name or "atlas_chunk_" in mat.name):
            import re
            m = re.search(r"(?:atlas_)?(?:[a-z_]+_)?chunk_(\d+)", mat.name)
            if m:
                cid = int(m.group(1))

        if cid is not None and cid not in chunk_materials:
            chunk_materials[cid] = mat

    # 3. Check mapping chunks metadata fallback
    if mapping and "chunks" in mapping:
        for chunk in mapping["chunks"]:
            cid = int(chunk.get("chunk_id", 0))
            if cid not in chunk_materials:
                if cid == 0:
                    active = bound_material or find_active_atlas_material()
                    if active:
                        chunk_materials[0] = active

    if not chunk_materials:
        active = bound_material or find_active_atlas_material() or get_or_create_atlas_material()
        if active:
            chunk_materials[0] = active

    return chunk_materials


def setup_material_slots_for_object(
    obj: bpy.types.Object,
    mat: Optional[bpy.types.Material] = None,
    mapping: Optional[dict] = None,
):
    """Ensure object has all chunk materials assigned to slots 0..N in order.

    Slot index directly corresponds to mtk_atlas_chunk_id, enabling Geometry Nodes
    to use Set Material Index without overwriting via a single Set Material node.
    """
    if not obj or not getattr(obj, "data", None) or not HAS_BPY:
        return

    if mat is None:
        mat = find_bound_atlas_material(obj) or find_active_atlas_material() or get_or_create_atlas_material()

    if mapping is None and mat:
        mapping = parse_atlas_mapping(mat)

    chunk_materials = find_all_atlas_chunk_materials(mapping=mapping, bound_material=mat, obj=obj)
    if not chunk_materials and mat:
        chunk_materials[0] = mat

    max_chunk_id = max(chunk_materials.keys()) if chunk_materials else 0
    needed_slots = max(1, max_chunk_id + 1)

    while len(obj.data.materials) < needed_slots:
        obj.data.materials.append(None)

    for cid in range(needed_slots):
        target_mat = chunk_materials.get(cid) or mat
        obj.data.materials[cid] = target_mat

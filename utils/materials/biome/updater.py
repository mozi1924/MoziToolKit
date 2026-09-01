"""
Instant Biome Updater for Atlas and Standalone Material Modes.
Updates mesh face attributes or material shader nodes in < 1ms without rerunning the texture replacement pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Any
import bpy

from ..constants import (
    ATTR_ATLAS_CHUNK_ID,
    ATTR_ATLAS_TEXTURE_ID,
    ATTR_BIOME_TINT_DATA,
    ATTR_BIOME_TINT_COLOR,
    ATTR_COLORMAP_UV,
    ATTR_SOURCE_TEXTURE_KEY,
    PROP_CREATED_BY,
    PROP_ATLAS_MAPPING,
    PROP_PACK_HASH,
)
from .biome import (
    get_biome_colors,
    BiomeResolver,
    TINT_TYPE_NONE,
    TINT_TYPE_GRASS,
    TINT_TYPE_FOLIAGE,
    TINT_TYPE_WATER,
    TINT_TYPE_HARDCODED,
    TINT_TYPE_DRY_FOLIAGE,
)


def is_mtk_object(obj: Optional[bpy.types.Object]) -> bool:
    """Check if the given object has MoziToolKit materials or face metadata."""
    if not obj or obj.type != "MESH" or not obj.data:
        return False
    if obj.get("mtk:provenance_schema_version") is not None or obj.get("mtk:biome_preset") is not None:
        return True
    mesh = obj.data
    attrs = mesh.attributes
    if any(name in attrs for name in (ATTR_SOURCE_TEXTURE_KEY, ATTR_BIOME_TINT_DATA, ATTR_BIOME_TINT_COLOR, ATTR_ATLAS_CHUNK_ID, ATTR_COLORMAP_UV)):
        return True
    for slot in obj.material_slots:
        mat = slot.material
        if mat and (mat.name.startswith("mtk:") or mat.get("mozi_created_by") or PROP_ATLAS_MAPPING in mat or mat.name.startswith("MC_Atlas")):
            return True
    return False


def detect_object_material_mode(obj: bpy.types.Object) -> str:
    """Determine whether an object is currently configured in Atlas or Standalone mode."""
    if not obj or obj.type != "MESH" or not obj.data:
        return "UNKNOWN"
    mesh = obj.data
    if ATTR_ATLAS_CHUNK_ID in mesh.attributes or ATTR_BIOME_TINT_DATA in mesh.attributes:
        return "ATLAS"
    for slot in obj.material_slots:
        mat = slot.material
        if mat and (PROP_ATLAS_MAPPING in mat or mat.name.startswith("MC_Atlas")):
            return "ATLAS"
        if mat and mat.name.startswith("mtk:"):
            return "STANDALONE"
    return "GENERIC"


def update_object_biome(
    obj: bpy.types.Object,
    biome_name: str,
    pack_stack: Any = None,
) -> bool:
    """
    Instantly update an object's biome colors and colormap UVs without rerunning the texture replacement pipeline.
    Supports both Atlas mode (mesh face attributes) and Standalone mode (material shader node trees).
    """
    if not is_mtk_object(obj):
        return False

    mesh = obj.data
    mode = detect_object_material_mode(obj)
    biome_colors = get_biome_colors(biome_name, pack_stack=pack_stack)
    effective_stack = pack_stack
    if effective_stack is None:
        try:
            from ..pack.pack_stack import get_configured_pack_stack
            effective_stack = get_configured_pack_stack()
        except Exception:
            effective_stack = None

    if mode == "ATLAS" and hasattr(mesh, "polygons") and len(mesh.polygons) > 0:
        # Atlas mode: fast update mesh face attributes
        from ..pipeline.mesh_attributes import (
            compute_biome_tint_attributes,
            apply_biome_tint_attributes,
            read_face_string_attribute,
        )
        num_polys = len(mesh.polygons)
        poly_tint_map: dict[int, dict] = {}
        source_keys = read_face_string_attribute(mesh, ATTR_SOURCE_TEXTURE_KEY)

        biome_resolver = BiomeResolver()
        if effective_stack:
            biome_resolver.load_from_pack_stack(effective_stack)

        existing_tint_data = mesh.attributes.get(ATTR_BIOME_TINT_DATA)

        for poly_idx in range(num_polys):
            raw_key = source_keys[poly_idx] if poly_idx < len(source_keys) else ""
            if raw_key:
                clean_key = raw_key.split(":")[-1].split("/")[-1]
                poly_tint_map[poly_idx] = biome_resolver.get_tint_info(clean_key)
            elif existing_tint_data and poly_idx < len(existing_tint_data.data):
                c = existing_tint_data.data[poly_idx].color
                base_w, overlay_w, tint_w, tint_type = c[0], c[1], c[2], int(round(c[3]))
                poly_tint_map[poly_idx] = {
                    "tint_type": tint_type,
                    "tint_weight": tint_w,
                    "base_tint_weight": base_w,
                    "overlay_tint_weight": overlay_w,
                }

        packed_tint_data, tint_colors, colormap_uvs = compute_biome_tint_attributes(
            num_polys, poly_tint_map, biome_preset=biome_name
        )
        apply_biome_tint_attributes(mesh, packed_tint_data, tint_colors, colormap_uvs)

    # Standalone mode & any direct materials: update shader node inputs
    updated_materials = set()
    for slot in obj.material_slots:
        mat = slot.material
        if not mat or not mat.node_tree or mat.name in updated_materials:
            continue
        updated_materials.add(mat.name)
        nt = mat.node_tree
        biome_tint_node = nt.nodes.get("MC Biome Tint")
        if not biome_tint_node:
            continue

        sampler_node = nt.nodes.get("MC Biome Colormap Sampler")
        tex_colormap = None
        for n in nt.nodes:
            if n.type == "TEX_IMAGE" and n.name.startswith("Colormap "):
                tex_colormap = n
                break

        # Determine tint channel type from colormap node or material name
        colormap_name = None
        has_custom = False
        resolved_col = (1.0, 1.0, 1.0, 1.0)

        if tex_colormap and "Grass" in tex_colormap.name:
            colormap_name = "grass"
            has_custom = bool(biome_colors.get("has_custom_grass", False))
            resolved_col = biome_colors["grass_linear"]
        elif tex_colormap and "Foliage" in tex_colormap.name:
            colormap_name = "foliage"
            has_custom = bool(biome_colors.get("has_custom_foliage", False))
            resolved_col = biome_colors["foliage_linear"]
        elif tex_colormap and "Dry Foliage" in tex_colormap.name:
            colormap_name = "dry_foliage"
            has_custom = bool(biome_colors.get("has_custom_dry_foliage", False))
            resolved_col = biome_colors["dry_foliage_linear"]
        elif "water" in mat.name.lower():
            has_custom = True
            resolved_col = biome_colors["water_linear"]
        elif "grass" in mat.name.lower():
            colormap_name = "grass"
            has_custom = bool(biome_colors.get("has_custom_grass", False))
            resolved_col = biome_colors["grass_linear"]
        elif "leave" in mat.name.lower() or "foliage" in mat.name.lower():
            colormap_name = "foliage"
            has_custom = bool(biome_colors.get("has_custom_foliage", False))
            resolved_col = biome_colors["foliage_linear"]

        # 1. Update Sampler node temperature/humidity
        if sampler_node:
            sampler_node.inputs["Temperature"].default_value = float(biome_colors.get("temperature", 0.8))
            sampler_node.inputs["Humidity"].default_value = float(biome_colors.get("humidity", 0.4))

        # 2. Update Tint Color socket
        biome_tint_node.inputs["Tint Color"].default_value = tuple(resolved_col)

        # 3. Route links: custom biomes disconnect sampler so default_value is used
        tint_input = biome_tint_node.inputs["Tint Color"]
        if has_custom and tex_colormap:
            for l in list(nt.links):
                if l.to_socket == tint_input:
                    nt.links.remove(l)
        elif not has_custom and tex_colormap:
            has_link = any(l.to_socket == tint_input and l.from_node == tex_colormap for l in nt.links)
            if not has_link:
                nt.links.new(tex_colormap.outputs["Color"], tint_input)

    obj["mtk:biome_preset"] = biome_name
    return True

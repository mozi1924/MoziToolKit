"""
Instant Biome Updater for Atlas and Standalone Material Modes.
Updates mesh face attributes or material shader nodes in < 1ms without rerunning the texture replacement pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Any
import bpy

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

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
        if mat:
            name_lower = mat.name.lower()
            if (
                name_lower.startswith(("mtk:", "mtk_", "mc_atlas"))
                or mat.get("mozi_created_by")
                or mat.get("mtk_material_mode")
                or PROP_ATLAS_MAPPING in mat
            ):
                return True
    return False


def detect_object_material_mode(obj: bpy.types.Object) -> str:
    """Determine whether an object is currently configured in Atlas or Standalone mode."""
    if not obj or obj.type != "MESH" or not obj.data:
        return "UNKNOWN"

    # 1. Authoritative check on material slots first
    has_atlas_mat = False
    has_standalone_mat = False
    for slot in obj.material_slots:
        mat = slot.material
        if not mat:
            continue
        mode_prop = mat.get("mtk_material_mode")
        if mode_prop == "ATLAS":
            return "ATLAS"
        elif mode_prop == "STANDALONE":
            return "STANDALONE"

        name_lower = mat.name.lower()
        if (
            name_lower.startswith(("mtk:atlas:", "mtk_atlas_", "mc_atlas"))
            or PROP_ATLAS_MAPPING in mat
        ):
            has_atlas_mat = True
        elif name_lower.startswith(("mtk:", "mtk_")) or mat.get("mtk:material_id"):
            has_standalone_mat = True

    if has_atlas_mat:
        return "ATLAS"
    if has_standalone_mat:
        return "STANDALONE"

    # 2. Check mesh-level provenance attributes if material slots are generic/empty
    mesh = obj.data
    if ATTR_ATLAS_CHUNK_ID in mesh.attributes:
        return "ATLAS"
    if ATTR_BIOME_TINT_DATA in mesh.attributes or ATTR_SOURCE_TEXTURE_KEY in mesh.attributes:
        return "ATLAS"

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

    # Read custom biome parameters if configured on the object
    is_custom = biome_name.upper() == "CUSTOM"
    if is_custom:
        custom_temp = float(getattr(obj, "mtk_biome_temp", obj.get("mtk_biome_temp", 0.8) if hasattr(obj, "get") else 0.8))
        custom_humidity = float(getattr(obj, "mtk_biome_humidity", obj.get("mtk_biome_humidity", 0.4) if hasattr(obj, "get") else 0.4))
        has_custom_grass = bool(getattr(obj, "mtk_biome_use_custom_grass", obj.get("mtk_biome_use_custom_grass", False) if hasattr(obj, "get") else False))
        has_custom_foliage = bool(getattr(obj, "mtk_biome_use_custom_foliage", obj.get("mtk_biome_use_custom_foliage", False) if hasattr(obj, "get") else False))
        has_custom_dry_foliage = bool(getattr(obj, "mtk_biome_use_custom_dry_foliage", obj.get("mtk_biome_use_custom_dry_foliage", False) if hasattr(obj, "get") else False))
        custom_grass = list(getattr(obj, "mtk_biome_grass_color", obj.get("mtk_biome_grass_color", (0.28, 0.51, 0.10, 1.0)) if hasattr(obj, "get") else (0.28, 0.51, 0.10, 1.0)))
        custom_foliage = list(getattr(obj, "mtk_biome_foliage_color", obj.get("mtk_biome_foliage_color", (0.18, 0.41, 0.03, 1.0)) if hasattr(obj, "get") else (0.18, 0.41, 0.03, 1.0)))
        custom_dry_foliage = list(getattr(obj, "mtk_biome_dry_foliage_color", obj.get("mtk_biome_dry_foliage_color", (0.37, 0.18, 0.06, 1.0)) if hasattr(obj, "get") else (0.37, 0.18, 0.06, 1.0)))
        custom_water = list(getattr(obj, "mtk_biome_water_color", obj.get("mtk_biome_water_color", (0.05, 0.18, 0.78, 1.0)) if hasattr(obj, "get") else (0.05, 0.18, 0.78, 1.0)))
    else:
        custom_temp = None
        custom_humidity = None
        has_custom_grass = False
        has_custom_foliage = False
        has_custom_dry_foliage = False
        custom_grass = None
        custom_foliage = None
        custom_dry_foliage = None
        custom_water = None

    biome_colors = get_biome_colors(
        biome_name,
        pack_stack=pack_stack,
        custom_temp=custom_temp,
        custom_humidity=custom_humidity,
        custom_grass=custom_grass,
        custom_foliage=custom_foliage,
        custom_dry_foliage=custom_dry_foliage,
        custom_water=custom_water,
        has_custom_grass=has_custom_grass,
        has_custom_foliage=has_custom_foliage,
        has_custom_dry_foliage=has_custom_dry_foliage,
    )
    effective_stack = pack_stack
    if effective_stack is None:
        try:
            from bridge.assets import get_configured_pack_stack
            effective_stack = get_configured_pack_stack()
        except Exception:
            effective_stack = None

    # 1. Update mesh face attributes (Both ATLAS and STANDALONE modes use attribute drivers)
    num_polys = len(mesh.polygons) if hasattr(mesh, "polygons") else 0
    if num_polys > 0:
        from .biome import (
            compute_biome_tint_attributes,
            apply_biome_tint_attributes,
            read_face_string_attribute,
            get_or_load_biome_resolver,
        )

        source_keys = []
        if ATTR_SOURCE_TEXTURE_KEY in mesh.attributes:
            source_keys = read_face_string_attribute(mesh, ATTR_SOURCE_TEXTURE_KEY)

        if any(source_keys):
            biome_resolver = get_or_load_biome_resolver(pack_stack=effective_stack)
            packed_tint_data, tint_colors, colormap_uvs = compute_biome_tint_attributes(
                source_keys,
                biome_preset=biome_name,
                resolver=biome_resolver,
                custom_temp=custom_temp,
                custom_humidity=custom_humidity,
                custom_grass=custom_grass,
                custom_foliage=custom_foliage,
                custom_dry_foliage=custom_dry_foliage,
                custom_water=custom_water,
                has_custom_grass=has_custom_grass,
                has_custom_foliage=has_custom_foliage,
                has_custom_dry_foliage=has_custom_dry_foliage,
            )
            apply_biome_tint_attributes(mesh, packed_tint_data, tint_colors, colormap_uvs)
        elif ATTR_BIOME_TINT_DATA in mesh.attributes:
            # Fast in-place update for Live Sync / Voxel World meshes where mtk_biome_tint_data is present
            tint_data_attr = mesh.attributes.get(ATTR_BIOME_TINT_DATA)
            if tint_data_attr and len(tint_data_attr.data) == num_polys:
                grass_col = biome_colors.get("grass_linear", [0.28, 0.51, 0.10, 1.0])
                foliage_col = biome_colors.get("foliage_linear", [0.18, 0.41, 0.03, 1.0])
                water_col = biome_colors.get("water_linear", [0.05, 0.18, 0.78, 1.0])
                dry_foliage_col = biome_colors.get("dry_foliage_linear", [0.37, 0.18, 0.06, 1.0])
                cm_uv = biome_colors.get("colormap_uv", [0.2, 0.32])
                base_uv_3 = [float(cm_uv[0]), float(cm_uv[1]), 0.0]

                vectorized_done = False
                if HAS_NUMPY and hasattr(tint_data_attr.data, "foreach_get"):
                    try:
                        raw_data = np.empty(num_polys * 4, dtype=np.float32)
                        tint_data_attr.data.foreach_get("color", raw_data)
                        raw_data_2d = raw_data.reshape(num_polys, 4)

                        tt = np.round(raw_data_2d[:, 3]).astype(np.int32)
                        new_tint_colors = np.ones((num_polys, 4), dtype=np.float32)

                        new_tint_colors[tt == TINT_TYPE_GRASS] = grass_col
                        new_tint_colors[tt == TINT_TYPE_FOLIAGE] = foliage_col
                        new_tint_colors[tt == TINT_TYPE_WATER] = water_col
                        new_tint_colors[tt == TINT_TYPE_DRY_FOLIAGE] = dry_foliage_col

                        if ATTR_BIOME_TINT_COLOR in mesh.attributes:
                            old_attr = mesh.attributes.get(ATTR_BIOME_TINT_COLOR)
                            if old_attr and len(old_attr.data) == num_polys and hasattr(old_attr.data, "foreach_get"):
                                old_cols_arr = np.empty(num_polys * 4, dtype=np.float32)
                                old_attr.data.foreach_get("color", old_cols_arr)
                                old_cols_2d = old_cols_arr.reshape(num_polys, 4)
                                hc_mask = (tt == TINT_TYPE_HARDCODED)
                                new_tint_colors[hc_mask] = old_cols_2d[hc_mask]

                        new_cm_uvs = np.empty((num_polys, 3), dtype=np.float32)
                        new_cm_uvs[:] = base_uv_3

                        new_packed_data = raw_data_2d.copy()
                        new_packed_data[:, 3] = tt.astype(np.float32)

                        apply_biome_tint_attributes(mesh, new_packed_data, new_tint_colors, new_cm_uvs)
                        vectorized_done = True
                    except Exception:
                        vectorized_done = False

                if not vectorized_done:
                    # Preserve existing hardcoded colors if available
                    old_cols = None
                    if ATTR_BIOME_TINT_COLOR in mesh.attributes:
                        old_attr = mesh.attributes.get(ATTR_BIOME_TINT_COLOR)
                        if old_attr and len(old_attr.data) == num_polys:
                            old_cols = [list(d.color) for d in old_attr.data]

                    new_tint_colors = []
                    new_cm_uvs = []
                    new_packed_data = []

                    for idx, d in enumerate(tint_data_attr.data):
                        c = d.color
                        base_w = float(c[0])
                        overlay_w = float(c[1])
                        tw = float(c[2])
                        tt = int(round(c[3]))

                        if tt == TINT_TYPE_GRASS:
                            final_col = grass_col
                        elif tt == TINT_TYPE_FOLIAGE:
                            final_col = foliage_col
                        elif tt == TINT_TYPE_WATER:
                            final_col = water_col
                        elif tt == TINT_TYPE_DRY_FOLIAGE:
                            final_col = dry_foliage_col
                        elif tt == TINT_TYPE_HARDCODED:
                            if old_cols and idx < len(old_cols):
                                final_col = old_cols[idx]
                            else:
                                final_col = [1.0, 1.0, 1.0, 1.0]
                        else:
                            final_col = [1.0, 1.0, 1.0, 1.0]

                        new_tint_colors.append(final_col)
                        new_cm_uvs.append(base_uv_3)
                        new_packed_data.append([base_w, overlay_w, tw, float(tt)])

                    apply_biome_tint_attributes(mesh, new_packed_data, new_tint_colors, new_cm_uvs)
        elif len(obj.material_slots) > 0:
            # Standalone mesh without face attributes: infer keys from material slot identities
            derived_keys = []
            for poly in mesh.polygons:
                m_idx = poly.material_index
                mat = obj.material_slots[m_idx].material if m_idx < len(obj.material_slots) else None
                key = (mat.get("mtk_source_texture_key") or mat.get("mtk:material_id") or (mat.name if mat else "")) if mat else ""
                derived_keys.append(str(key))

            if any(derived_keys):
                try:
                    from bridge.mesh import inject_face_attribute_string
                    inject_face_attribute_string(mesh, ATTR_SOURCE_TEXTURE_KEY, derived_keys)
                except Exception:
                    pass
                biome_resolver = get_or_load_biome_resolver(pack_stack=effective_stack)
                packed_tint_data, tint_colors, colormap_uvs = compute_biome_tint_attributes(
                    derived_keys,
                    biome_preset=biome_name,
                    resolver=biome_resolver,
                    custom_temp=custom_temp,
                    custom_humidity=custom_humidity,
                    custom_grass=custom_grass,
                    custom_foliage=custom_foliage,
                    custom_dry_foliage=custom_dry_foliage,
                    custom_water=custom_water,
                    has_custom_grass=has_custom_grass,
                    has_custom_foliage=has_custom_foliage,
                    has_custom_dry_foliage=has_custom_dry_foliage,
                )
                apply_biome_tint_attributes(mesh, packed_tint_data, tint_colors, colormap_uvs)

    # 2. Shader node trees update (Fallback / Direct node compatibility)
    updated_materials = set()
    for slot in obj.material_slots:
        mat = slot.material
        if not mat or not mat.node_tree or mat.name in updated_materials:
            continue
        updated_materials.add(mat.name)
        nt = mat.node_tree
        biome_tint_node = nt.nodes.get("MC Biome Tint") or nt.nodes.get("Biome Tint")
        if not biome_tint_node:
            continue

        # Determine tint channel type from material identity or legacy colormap node
        mat_lower = mat.name.lower()
        key = str(mat.get("mtk_source_texture_key") or mat.get("mtk:material_id") or "").lower()
        check_name = f"{mat_lower} {key}"

        has_custom = False
        resolved_col = (1.0, 1.0, 1.0, 1.0)

        if "water" in check_name:
            has_custom = True
            resolved_col = biome_colors["water_linear"]
        elif "dry_foliage" in check_name:
            has_custom = bool(biome_colors.get("has_custom_dry_foliage", False))
            resolved_col = biome_colors["dry_foliage_linear"]
        elif any(w in check_name for w in ("leave", "foliage", "vine", "lily_pad", "bush")):
            has_custom = bool(biome_colors.get("has_custom_foliage", False))
            resolved_col = biome_colors["foliage_linear"]
        elif any(w in check_name for w in ("grass", "fern", "sugar_cane")):
            has_custom = bool(biome_colors.get("has_custom_grass", False))
            resolved_col = biome_colors["grass_linear"]
        else:
            # Fallback check for single colormap node in legacy materials
            cm_nodes = [n for n in nt.nodes if n.type == "TEX_IMAGE" and n.name.startswith("Colormap ")]
            if len(cm_nodes) == 1:
                tex_cm = cm_nodes[0]
                if "Grass" in tex_cm.name:
                    has_custom = bool(biome_colors.get("has_custom_grass", False))
                    resolved_col = biome_colors["grass_linear"]
                elif "Foliage" in tex_cm.name:
                    has_custom = bool(biome_colors.get("has_custom_foliage", False))
                    resolved_col = biome_colors["foliage_linear"]
                elif "Dry Foliage" in tex_cm.name:
                    has_custom = bool(biome_colors.get("has_custom_dry_foliage", False))
                    resolved_col = biome_colors["dry_foliage_linear"]

        # 1. Update Sampler node temperature/humidity if present
        sampler_node = nt.nodes.get("MC Biome Colormap Sampler")
        if sampler_node:
            sampler_node.inputs["Temperature"].default_value = float(biome_colors.get("temperature", 0.8))
            sampler_node.inputs["Humidity"].default_value = float(biome_colors.get("humidity", 0.4))

        # 2. Update Tint Color socket default value
        if "Tint Color" in biome_tint_node.inputs:
            biome_tint_node.inputs["Tint Color"].default_value = tuple(resolved_col)

        # 3. Route links:
        colormap_decoder = nt.nodes.get("MC Biome Colormap Decoder")
        tint_input = biome_tint_node.inputs.get("Tint Color")
        if colormap_decoder and tint_input:
            # Modern attribute-driven architecture: ensure decoder is properly linked to tint node
            if not any(l.to_socket == tint_input and l.from_node == colormap_decoder for l in nt.links):
                for l in list(nt.links):
                    if l.to_socket == tint_input:
                        nt.links.remove(l)
                nt.links.new(colormap_decoder.outputs["Color"], tint_input)
        elif tint_input:
            # Legacy direct colormap graph: disconnect when custom override is active
            cm_nodes = [n for n in nt.nodes if n.type == "TEX_IMAGE" and n.name.startswith("Colormap ")]
            tex_colormap = cm_nodes[0] if len(cm_nodes) == 1 else None
            if has_custom and tex_colormap:
                for l in list(nt.links):
                    if l.to_socket == tint_input:
                        nt.links.remove(l)
            elif not has_custom and tex_colormap:
                has_link = any(l.to_socket == tint_input and l.from_node == tex_colormap for l in nt.links)
                if not has_link:
                    nt.links.new(tex_colormap.outputs["Color"], tint_input)

    obj["mtk:biome_preset"] = biome_name
    if hasattr(mesh, "update"):
        mesh.update()
    return True

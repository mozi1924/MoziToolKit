"""
Yefira Procedural Point-Cloud Material and Geometry Nodes Integration Module.

Provides object detection, attribute mapping, atlas slot configuration,
and Geometry Nodes notification for Yefira-based procedural Minecraft worlds.
"""

from __future__ import annotations

import logging
import sys
from typing import Iterable, Optional
import bpy

logger = logging.getLogger("MoziToolKit.Materials")

from ..constants import (
    ATTR_UV_ROTATION,
    ATTR_UV_TILING_TRANSFORM,
    PROP_CREATED_BY,
    PROP_PACK_HASH,
)
from pathlib import Path
from ...mc_baker import (
    StateBaker,
    get_shared_state_baker,
    refresh_shared_baker_sources,
    clear_shared_baker_cache,
    EMISSIVE_BLOCKS,
    is_block_emissive as _mc_is_block_emissive,
)
from ...live_sync.constants import (
    BLOCK_STATE,
    MC_POSITION,
    BLOCK_TYPE,
    TEMPLATE_INDEX,
    INSTANCE_ROTATION,
    DIRECTIONAL_FACE_V_FLIP,
    MTK_BIOME_TINT_COLOR,
    MTK_BIOME_TINT_DATA,
    TEMPLATE_COLLECTION_NAME,
    DEFAULT_WORLD_OBJECT_NAME,
    WORLD_MODIFIER_NAME,
    is_contract_compatible,
    get_attribute_contract_version,
)
from ...live_sync.classifier import (
    parse_and_classify,
    BlockTypeEnum,
    ParsedBlock,
    atlas_lookup_keys,
)
from ...live_sync.template_catalog import get_template_index_map
from ...live_sync.point_cloud import _resolve_template_index


def refresh_baker_sources() -> None:
    """Synchronize StateBaker resource loaders with the configured Resource Pack Stack."""
    refresh_shared_baker_sources()


from ..constants import BLOCK_TO_TEXTURE_ALIASES

EMISSIVE_BLOCK_NAMES = EMISSIVE_BLOCKS
HARDCODED_TINT_BLOCKS = {
    "spruce_leaves": (1.0, 1.0, 1.0, 1.0),
    "birch_leaves": (1.0, 1.0, 1.0, 1.0),
    "lily_pad": (1.0, 1.0, 1.0, 1.0),
    "redstone_wire": (1.0, 1.0, 1.0, 1.0),
}


def parse_block_state_str(state: str) -> tuple[str, dict[str, str]]:
    """Parse a serialized block state string into clean block name and properties dict."""
    state_clean = state.strip()
    bracket_idx = state_clean.find("[")
    if bracket_idx == -1:
        block_name = state_clean
        props = {}
    else:
        block_name = state_clean[:bracket_idx]
        props_str = state_clean[bracket_idx + 1:].rstrip("]")
        props = {}
        if props_str:
            for pair in props_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    props[k.strip()] = v.strip()
    block_name = block_name.removeprefix("minecraft:").removeprefix("block/")
    return block_name, props


def is_block_emissive(block_name: str, props: Optional[dict[str, str]] = None) -> int:
    """Return 1 if block/state is emissive (light emitting), else 0."""
    return 1 if _mc_is_block_emissive(block_name, props) else 0


def is_yefira_object(obj: Optional[bpy.types.Object]) -> bool:
    """Identify whether a Blender object is a Yefira procedural point-cloud world.

    An object is recognized as Yefira if:
    1. Its mesh data contains a point-domain 'yefira_block_state' or 'yefira_mc_position' attribute (or legacy names), or
    2. It has a Geometry Nodes modifier named 'Yefira_WorldModifier' or containing 'yefira', or
    3. It is a MESH object named 'Yefira_World'.
    """
    if not obj or getattr(obj, "type", None) != 'MESH' or not getattr(obj, "data", None):
        return False
    mesh = obj.data
    if hasattr(mesh, "attributes"):
        state_attr = mesh.attributes.get(BLOCK_STATE) or mesh.attributes.get("block_state")
        if state_attr and state_attr.domain == 'POINT':
            return True
        if (
            MC_POSITION in mesh.attributes
            or "mc_pos" in mesh.attributes
            or "mc_position" in mesh.attributes
        ):
            return True
    if hasattr(obj, "modifiers") and any(
        mod.type == 'NODES' and (mod.name == WORLD_MODIFIER_NAME or "yefira" in mod.name.lower())
        for mod in obj.modifiers
    ):
        return True
    if obj.name == DEFAULT_WORLD_OBJECT_NAME:
        return True
    return False


def has_yefira_objects(objects: Iterable[Optional[bpy.types.Object]]) -> bool:
    """Return True if any object in the given collection is a Yefira world."""
    return any(is_yefira_object(obj) for obj in objects if obj)


def write_yefira_point_atlas_attributes(mesh: bpy.types.Mesh, mapping: dict) -> None:
    """Fill Yefira's 6-direction face atlas attributes directly from Mozi's mapping.

    Writes the following POINT domain attributes:
    - ``mtk_material_id`` (INT)
    - ``mtk_is_opaque`` (INT)
    - ``is_opaque`` (INT)
    - ``mtk_emissive`` (INT)
    - ``mtk_tile_{face}`` (FLOAT_VECTOR for east, west, top, bottom, south, north)
    - ``mtk_chunk_{face}`` (INT)
    - ``mtk_texture_{face}`` (INT)
    - ``mtk_is_opaque_{face}`` (INT)
    - ``mtk_tint_data_{face}`` (FLOAT_COLOR: base_weight, overlay_weight, tint_weight, is_hardcoded)
    - ``mtk_anim_timing_{face}`` (FLOAT_COLOR: frame_count, frametime, interpolate, 0)
    - ``mtk_anim_frame_size_{face}`` (FLOAT_COLOR: frame_width, frame_height, 0, 0)
    - ``mtk_uv_rot_{face}`` (FLOAT)
    - ``mtk_uv_bounds_{face}`` (FLOAT_COLOR: u_min, v_min, u_max, v_max)
    - ``yefira_instance_rotation`` (FLOAT_VECTOR)
    - ``yefira_block_type`` (INT)
    - ``yefira_template_index`` (INT)
    - ``yefira_directional_face_v_flip`` (INT)
    - ``mtk_biome_tint_color`` (FLOAT_COLOR)
    - ``mtk_biome_tint_data`` (FLOAT_COLOR)
    """
    state_attr = mesh.attributes.get(BLOCK_STATE) or mesh.attributes.get("block_state")
    if not state_attr or state_attr.domain != 'POINT':
        return

    refresh_baker_sources()

    template_col = bpy.data.collections.get(TEMPLATE_COLLECTION_NAME)
    template_indices = get_template_index_map(template_col) if template_col else {}

    by_name = {
        str(entry.get("name", "")).removeprefix("minecraft:").removeprefix("block/"): entry
        for entry in mapping.get("materials", [])
        if entry.get("name")
    }
    texture_locations = mapping.get("textures", {})

    def texture_location(block_name: str) -> dict:
        """Find a flat texture entry when a block model has no face table."""
        if not block_name:
            return {}
        clean_name = str(block_name).split(":", 1)[-1].removeprefix("block/")
        for key in (block_name, f"minecraft:{block_name}", f"minecraft:block/{block_name}", clean_name, f"minecraft:{clean_name}", f"minecraft:block/{clean_name}"):
            location = texture_locations.get(key)
            if isinstance(location, dict):
                return location
        if clean_name in BLOCK_TO_TEXTURE_ALIASES:
            for stem in BLOCK_TO_TEXTURE_ALIASES[clean_name]:
                for key in (stem, f"minecraft:{stem}", f"minecraft:block/{stem}"):
                    location = texture_locations.get(key)
                    if isinstance(location, dict):
                        return location
        return {}

    def texture_only_faces(block_name: str, props: dict[str, str]) -> dict:
        """Derive standard cube faces from StateBaker baked face textures and atlas locations."""
        state_query = f"minecraft:{block_name}"
        if props:
            p_str = ",".join(f"{k}={v}" for k, v in sorted(props.items()))
            state_query = f"{state_query}[{p_str}]"
        baked_faces = get_shared_state_baker().bake_block_state(state_query).faces
        result = {}
        dir_to_key = {"east": "+X", "west": "-X", "up": "+Y", "down": "-Y", "south": "+Z", "north": "-Z"}
        for f in baked_faces:
            loc = texture_location(f.texture)
            if not loc:
                short = f.texture.split(":", 1)[-1].removeprefix("block/")
                loc = texture_location(short)
            if loc:
                result[dir_to_key.get(f.direction, f.direction)] = loc
        return result

    def mapping_names(state_or_parsed: Any) -> tuple[str, ...]:
        """Resolve stateful generated models before generic texture fallback."""
        return atlas_lookup_keys(state_or_parsed)

    face_specs = (
        ("east", "+X"), ("west", "-X"), ("top", "+Y"),
        ("bottom", "-Y"), ("south", "+Z"), ("north", "-Z"),
    )
    values = {
        name: {
            "tile": [],
            "chunk": [],
            "texture": [],
            "tint_data": [],
            "is_opaque": [],
            "anim_timing": [],
            "anim_frame_size": [],
            "uv_rot": [],
            "uv_bounds": [],
        }
        for name, _ in face_specs
    }
    material_ids = []
    is_opaque_list = []
    emissive_list = []
    rotations = []
    block_types = []
    template_indices_list = []
    directional_flips = []
    tint_colors = []
    tint_datas = []

    import json

    for item in state_attr.data:
        state = item.value.decode("utf-8", errors="replace") if isinstance(item.value, bytes) else str(item.value)
        raw_state = state
        json_obj = None
        if state and state.startswith("{") and state.endswith("}"):
            try:
                json_obj = json.loads(state)
                if isinstance(json_obj, dict):
                    raw_state = json_obj.get("state", state)
            except Exception:
                json_obj = None

        block_name, props = parse_block_state_str(raw_state)
        parsed: ParsedBlock = parse_and_classify(raw_state)
        if json_obj and isinstance(json_obj, dict):
            if "type" in json_obj:
                parsed.block_type = int(json_obj["type"])
            if "opaque" in json_obj:
                parsed.is_opaque = int(json_obj["opaque"])
            if "emissive" in json_obj:
                parsed.is_emissive = int(json_obj["emissive"])
            if "emissive_level" in json_obj:
                parsed.emissive_level = float(json_obj["emissive_level"])
            if "rot" in json_obj:
                r = json_obj["rot"]
                if isinstance(r, (list, tuple)) and len(r) == 3:
                    parsed.rot_euler = (float(r[0]), float(r[1]), float(r[2]))
            elif "rotation" in json_obj:
                r = json_obj["rotation"]
                if isinstance(r, (list, tuple)) and len(r) == 3:
                    parsed.rot_euler = (float(r[0]), float(r[1]), float(r[2]))
            elif "instance_rotation" in json_obj:
                r = json_obj["instance_rotation"]
                if isinstance(r, (list, tuple)) and len(r) == 3:
                    parsed.rot_euler = (float(r[0]), float(r[1]), float(r[2]))

        names = mapping_names(parsed)
        entry = next((by_name[name] for name in names if name in by_name), None)
        mat_id = int(entry.get("material_id", 0)) if entry else 0
        material_ids.append(mat_id)
        faces_dict = entry.get("faces", {}) if entry else {}

        fallback_location = next((texture_location(name) for name in names if texture_location(name)), {})
        if not fallback_location:
            for name in names:
                if name in BLOCK_TO_TEXTURE_ALIASES:
                    for stem in BLOCK_TO_TEXTURE_ALIASES[name]:
                        loc = texture_location(stem)
                        if loc:
                            fallback_location = loc
                            break
                    if fallback_location:
                        break

        block_state_entry = mapping.get("block_states", {}).get(raw_state)
        if not block_state_entry and mapping.get("block_states"):
            short_state = raw_state.removeprefix("minecraft:")
            block_state_entry = mapping["block_states"].get(short_state)
            if not block_state_entry:
                try:
                    resolved_matches = get_shared_state_baker().state_resolver.resolve_state(raw_state)
                    if resolved_matches:
                        for match in resolved_matches:
                            if match.variant_props:
                                var_str = ",".join(f"{k}={v}" for k, v in sorted(match.variant_props.items()))
                                for cand in (f"{block_name}[{var_str}]", f"minecraft:{block_name}[{var_str}]"):
                                    if cand in mapping["block_states"]:
                                        block_state_entry = mapping["block_states"][cand]
                                        break
                            if block_state_entry:
                                break
                except Exception:
                    pass

        json_faces = json_obj.get("faces") if (json_obj and isinstance(json_obj, dict) and isinstance(json_obj.get("faces"), dict)) else None
        baked = get_shared_state_baker().bake_block_state(raw_state) if not json_faces else None

        if json_obj and "opaque" in json_obj:
            is_opaque_list.append(int(json_obj["opaque"]))
        elif block_state_entry:
            is_opaque_list.append(1 if block_state_entry.get("is_opaque", True) else 0)
        elif baked:
            is_opaque_list.append(int(baked.is_opaque) if entry is None or "is_opaque" not in entry else (1 if entry.get("is_opaque", True) else 0))
        else:
            is_opaque_list.append(parsed.is_opaque)

        if json_obj and "emissive" in json_obj:
            emissive_list.append(int(json_obj["emissive"]))
        elif block_state_entry:
            emissive_list.append(1 if block_state_entry.get("is_emissive", False) or is_block_emissive(block_name, props) else 0)
        elif baked:
            emissive_list.append(1 if is_block_emissive(block_name, props) or baked.is_emissive else 0)
        else:
            emissive_list.append(parsed.is_emissive)

        tmpl_idx = _resolve_template_index(template_indices, parsed.template_name)
        rotations.append(parsed.rot_euler)
        block_types.append(parsed.block_type)
        template_indices_list.append(tmpl_idx)
        directional_flips.append(int(parsed.name in ("command_block", "chain_command_block", "repeating_command_block")))
        tint_colors.append(parsed.tint_color)
        tint_datas.append(parsed.tint_data)

        derived_faces = texture_only_faces(block_name, props) if not json_faces else {}

        is_snowy_top = props.get("snowy") == "true" and block_name in ("grass_block", "podzol", "mycelium")
        is_hardcoded_block = block_name in HARDCODED_TINT_BLOCKS

        for face_idx, (attr_face, mapping_face) in enumerate(face_specs):
            json_face = None
            if json_faces:
                json_face = (
                    json_faces.get(attr_face)
                    or json_faces.get(mapping_face)
                    or (json_faces.get("up") if attr_face == "top" else None)
                    or (json_faces.get("down") if attr_face == "bottom" else None)
                )

            baked_face = baked.faces[face_idx] if (baked and face_idx < len(baked.faces)) else None
            state_face_entry = block_state_entry.get("faces", {}).get(mapping_face) if block_state_entry else None

            if json_face:
                tex_name = json_face.get("tex", json_face.get("texture", ""))
                uv_r = float(json_face.get("rot", json_face.get("uv_rotation", 0.0)))
                uv_b = tuple(json_face.get("uv", json_face.get("uv_bounds", [0.0, 0.0, 1.0, 1.0])))
                tint_idx = int(json_face.get("tint", json_face.get("tint_index", -1)))
            elif state_face_entry:
                tex_name = state_face_entry.get("texture_key", state_face_entry.get("texture", ""))
                uv_r = float(state_face_entry.get("uv_rotation", 0.0))
                uv_b = tuple(state_face_entry.get("uv_bounds", [
                    state_face_entry.get("u_min", 0.0),
                    state_face_entry.get("v_min", 0.0),
                    state_face_entry.get("u_max", 1.0),
                    state_face_entry.get("v_max", 1.0),
                ]))
                tint_idx = int(state_face_entry.get("tint_index", -1))
            elif baked_face:
                tex_name = baked_face.texture
                uv_r = float(baked_face.uv_rot)
                uv_b = tuple(baked_face.uv_bounds)
                tint_idx = int(baked_face.tint_index)
            else:
                tex_name = ""
                uv_r = 0.0
                uv_b = (0.0, 0.0, 1.0, 1.0)
                tint_idx = -1

            f_mapping = faces_dict.get(mapping_face, {}) if isinstance(faces_dict, dict) else {}
            tex_stem = f_mapping.get("texture", "") if isinstance(f_mapping, dict) else ""

            short_n = tex_name.split(":", 1)[-1]
            if short_n.startswith("block/"):
                short_n = short_n[6:]

            cur_state_loc = state_face_entry if (not json_face and isinstance(state_face_entry, dict) and ("tile_column" in state_face_entry or "pixel_x" in state_face_entry or "chunk_id" in state_face_entry)) else None

            location = (
                cur_state_loc
                or texture_location(tex_name)
                or texture_location(short_n)
                or texture_location(f"minecraft:{short_n}")
                or texture_location(f"minecraft:block/{short_n}")
                or texture_location(tex_stem)
                or (f_mapping if isinstance(f_mapping, dict) and ("tile_column" in f_mapping or "kind" in f_mapping or "chunk_id" in f_mapping) else None)
                or derived_faces.get(mapping_face)
                or fallback_location
                or {}
            )

            if location.get("kind") == "animation":
                px = int(location.get("pixel_x", 0))
                fw = max(1, int(location.get("frame_width", 16)))
                tile_col = float(px // fw)
                tile_row = 0.0
            else:
                tile_col = float(location.get("tile_column", 0))
                tile_row = float(location.get("tile_row", 0))

            values[attr_face]["tile"].append((tile_col, tile_row, 0.0))
            values[attr_face]["chunk"].append(int(location.get("chunk_id", 0)))
            values[attr_face]["texture"].append(int(location.get("texture_id", mat_id)))
            values[attr_face]["is_opaque"].append(1 if location.get("is_opaque", True) else 0)

            if is_snowy_top and attr_face == "top":
                values[attr_face]["tint_data"].append((0.0, 0.0, 0.0, 0.0))
            elif is_hardcoded_block:
                values[attr_face]["tint_data"].append((1.0, 1.0, 1.0, 1.0))
            elif isinstance(f_mapping, dict) and ("default_tint_weight" in f_mapping or "default_overlay_tint_weight" in f_mapping or "default_base_tint_weight" in f_mapping):
                values[attr_face]["tint_data"].append((
                    float(f_mapping.get("default_base_tint_weight", 0.0)),
                    float(f_mapping.get("default_overlay_tint_weight", 0.0)),
                    float(f_mapping.get("default_tint_weight", 0.0)),
                    1.0 if f_mapping.get("is_hardcoded", False) else 0.0,
                ))
            elif location.get("default_tint_weight", 0.0) > 0 or location.get("default_overlay_tint_weight", 0.0) > 0 or tint_idx >= 0:
                values[attr_face]["tint_data"].append((
                    float(location.get("default_base_tint_weight", 1.0 if tint_idx >= 0 else 0.0)),
                    float(location.get("default_overlay_tint_weight", 0.0)),
                    float(location.get("default_tint_weight", 1.0 if tint_idx >= 0 else 0.0)),
                    1.0 if location.get("is_hardcoded", False) else 0.0,
                ))
            else:
                values[attr_face]["tint_data"].append((0.0, 0.0, 0.0, 0.0))

            frame_count = float(location.get("frame_count", 1))
            frametime = float(location.get("frametime", 1))
            interpolate = 1.0 if location.get("interpolate", False) else 0.0
            values[attr_face]["anim_timing"].append((frame_count, frametime, interpolate, 0.0))

            fw = float(location.get("frame_width", location.get("tile_size", 16)))
            fh = float(location.get("frame_height", location.get("tile_size", 16)))
            values[attr_face]["anim_frame_size"].append((fw, fh, 0.0, 0.0))

            values[attr_face]["uv_rot"].append(uv_r)
            values[attr_face]["uv_bounds"].append((float(uv_b[0]), float(uv_b[1]), float(uv_b[2]), float(uv_b[3])))

    def point_attr(name: str, data_type: str):
        attr = mesh.attributes.get(name)
        if attr and (attr.domain != 'POINT' or attr.data_type != data_type or len(attr.data) != len(state_attr.data)):
            mesh.attributes.remove(attr)
            attr = None
        return attr or mesh.attributes.new(name=name, type=data_type, domain='POINT')

    point_attr("mtk_material_id", 'INT').data.foreach_set('value', material_ids)
    point_attr("mtk_is_opaque", 'INT').data.foreach_set('value', is_opaque_list)
    point_attr("is_opaque", 'INT').data.foreach_set('value', is_opaque_list)
    point_attr("mtk_emissive", 'INT').data.foreach_set('value', emissive_list)
    for face, _ in face_specs:
        tile_attr = point_attr(f"mtk_tile_{face}", 'FLOAT_VECTOR')
        tile_attr.data.foreach_set('vector', [component for tile in values[face]["tile"] for component in tile])
        point_attr(f"mtk_chunk_{face}", 'INT').data.foreach_set('value', values[face]["chunk"])
        point_attr(f"mtk_texture_{face}", 'INT').data.foreach_set('value', values[face]["texture"])
        point_attr(f"mtk_is_opaque_{face}", 'INT').data.foreach_set('value', values[face]["is_opaque"])
        tint_attr = point_attr(f"mtk_tint_data_{face}", 'FLOAT_COLOR')
        tint_attr.data.foreach_set('color', [component for value in values[face]["tint_data"] for component in value])
        anim_timing_attr = point_attr(f"mtk_anim_timing_{face}", 'FLOAT_COLOR')
        anim_timing_attr.data.foreach_set('color', [component for value in values[face]["anim_timing"] for component in value])
        anim_frame_size_attr = point_attr(f"mtk_anim_frame_size_{face}", 'FLOAT_COLOR')
        anim_frame_size_attr.data.foreach_set('color', [component for value in values[face]["anim_frame_size"] for component in value])
        rot_attr = point_attr(f"mtk_uv_rot_{face}", 'FLOAT')
        rot_attr.data.foreach_set('value', values[face]["uv_rot"])
        bounds_attr = point_attr(f"mtk_uv_bounds_{face}", 'FLOAT_COLOR')
        bounds_attr.data.foreach_set('color', [component for value in values[face]["uv_bounds"] for component in value])

    point_attr(INSTANCE_ROTATION, 'FLOAT_VECTOR').data.foreach_set('vector', [component for rot in rotations for component in rot])
    point_attr(BLOCK_TYPE, 'INT').data.foreach_set('value', block_types)
    point_attr(TEMPLATE_INDEX, 'INT').data.foreach_set('value', template_indices_list)
    point_attr(DIRECTIONAL_FACE_V_FLIP, 'INT').data.foreach_set('value', directional_flips)
    point_attr(MTK_BIOME_TINT_COLOR, 'FLOAT_COLOR').data.foreach_set('color', [component for col in tint_colors for component in col])
    point_attr(MTK_BIOME_TINT_DATA, 'FLOAT_COLOR').data.foreach_set('color', [component for d in tint_datas for component in d])


def setup_yefira_point_cloud_attributes(
    mesh: bpy.types.Mesh,
    mapping_data: dict,
    primary_mat: Optional[bpy.types.Material] = None,
    chunk_0: Optional[dict] = None,
    chunk_1: Optional[dict] = None,
) -> None:
    """Initialize tiling, rotation, atlas dimensions, and 6-direction attributes on a point-cloud mesh."""
    if len(mesh.vertices) == 0:
        return

    num_verts = len(mesh.vertices)

    # 1. Ensure ATTR_UV_TILING_TRANSFORM exists
    tiling_attr = mesh.attributes.get(ATTR_UV_TILING_TRANSFORM)
    if not tiling_attr or tiling_attr.data_type != 'FLOAT_COLOR' or tiling_attr.domain != 'POINT' or len(tiling_attr.data) != num_verts:
        if tiling_attr:
            mesh.attributes.remove(tiling_attr)
        tiling_attr = mesh.attributes.new(name=ATTR_UV_TILING_TRANSFORM, type='FLOAT_COLOR', domain='POINT')
    flat_colors = [c for _ in range(num_verts) for c in (1.0, 1.0, 0.0, 0.0)]
    tiling_attr.data.foreach_set('color', flat_colors)

    # 2. Ensure ATTR_UV_ROTATION exists
    rot_attr = mesh.attributes.get(ATTR_UV_ROTATION)
    if not rot_attr or rot_attr.data_type != 'FLOAT' or rot_attr.domain != 'POINT' or len(rot_attr.data) != num_verts:
        if rot_attr:
            mesh.attributes.remove(rot_attr)
        rot_attr = mesh.attributes.new(name=ATTR_UV_ROTATION, type='FLOAT', domain='POINT')
    rot_attr.data.foreach_set('value', [0.0] * num_verts)

    # 3. Write atlas metadata attributes to point domain
    chunks = mapping_data.get("chunks", []) if isinstance(mapping_data, dict) else []
    chunks_by_id = {c.get("chunk_id", i): c for i, c in enumerate(chunks)} if isinstance(chunks, list) else {}
    chunk_0 = chunk_0 or chunks_by_id.get(0, {})
    chunk_1 = chunk_1 or chunks_by_id.get(1, {})

    mat_props = primary_mat or {}
    atlas_metadata = {
        "mtk_atlas_width": float(chunk_0.get("width", mat_props.get("mtk_atlas_width", 1024.0))),
        "mtk_atlas_height": float(chunk_0.get("height", mat_props.get("mtk_atlas_height", 1024.0))),
        "mtk_tile_size": float(chunk_0.get("tile_size", mat_props.get("mtk_tile_size", 16.0))),
        "mtk_tiles_per_row": float(chunk_0.get("tiles_per_row", mat_props.get("mtk_tiles_per_row", 64))),
        "mtk_anim_atlas_width": float(chunk_1.get("width", 896.0)),
        "mtk_anim_atlas_height": float(chunk_1.get("height", 1024.0)),
        "mtk_anim_frame_width": float(chunk_1.get("tile_size", 16.0)),
        "mtk_anim_frame_height": float(chunk_1.get("tile_size", 16.0)),
    }
    for attr_name, attr_value in atlas_metadata.items():
        attr = mesh.attributes.get(attr_name)
        if not attr or attr.data_type != 'FLOAT' or attr.domain != 'POINT' or len(attr.data) != num_verts:
            if attr:
                mesh.attributes.remove(attr)
            attr = mesh.attributes.new(name=attr_name, type='FLOAT', domain='POINT')
        attr.data.foreach_set('value', [attr_value] * num_verts)

    # 4. Fill 6-direction face attributes
    write_yefira_point_atlas_attributes(mesh, mapping_data)


def rebuild_or_update_yefira_material_dispatcher(
    atlas_materials: dict[int, bpy.types.Material],
) -> Optional[bpy.types.GeometryNodeTree]:
    """Ensure Yefira_Material_Dispatcher node group contains the complete multi-chunk Set Material chain."""
    from ...geometry_nodes.groups.material_dispatcher import get_or_create_material_dispatcher_group
    return get_or_create_material_dispatcher_group(atlas_materials)


def _update_yefira_geometry_node_materials(
    obj: bpy.types.Object,
    atlas_materials: dict[int, bpy.types.Material],
) -> None:
    """Traverse all Geometry Nodes modifier trees and nested sub-groups on a Yefira object,
    updating Set Material nodes and rebuilding the multi-chunk Material Dispatcher."""
    primary_mat = atlas_materials.get(0) or next(iter(atlas_materials.values()), None)
    if not primary_mat:
        return

    import re

    disp_tree = rebuild_or_update_yefira_material_dispatcher(atlas_materials)
    visited_groups = {disp_tree} if disp_tree else set()

    def update_node_group(group: Optional[bpy.types.NodeTree]) -> None:
        if not group or group in visited_groups or not hasattr(group, "nodes"):
            return
        visited_groups.add(group)

        for n in group.nodes:
            if n.type == 'SET_MATERIAL' and "Material" in n.inputs:
                m = re.search(r"Chunk (\d+)", n.name)
                if m:
                    cid = int(m.group(1))
                    n.inputs["Material"].default_value = atlas_materials.get(cid, primary_mat)
                else:
                    n.inputs["Material"].default_value = primary_mat
            elif n.type == 'GROUP' and getattr(n, "node_tree", None):
                if n.name == "Material Dispatcher" and disp_tree:
                    n.node_tree = disp_tree
                else:
                    update_node_group(n.node_tree)

    for mod in obj.modifiers:
        if mod.type == 'NODES' and mod.node_group:
            update_node_group(mod.node_group)


def _release_replaced_yefira_atlas_resources(
    old_materials: Iterable[Optional[bpy.types.Material]],
    current_materials: Iterable[Optional[bpy.types.Material]],
) -> None:
    """Release unused UVMap atlas data blocks left by a prior Yefira replacement.

    Atlas materials deliberately use fake users while assigned.  Without
    explicitly releasing superseded UVMap variants, replacing a world with
    several packs accumulates packed 4K atlas images for the entire Blender
    session.  That looks like a memory leak and becomes severe after a few
    test iterations.
    """
    current_ids = {
        mat.as_pointer() if hasattr(mat, "as_pointer") else id(mat)
        for mat in current_materials if mat
    }
    for mat in old_materials:
        mat_id = mat.as_pointer() if mat and hasattr(mat, "as_pointer") else id(mat)
        if (
            not mat
            or mat_id in current_ids
            or mat.get(PROP_CREATED_BY) != "MoziToolKit"
            or mat.get("mtk:atlas_uv_source", "") != "UVMap"
        ):
            continue
        mat.use_fake_user = False
        if mat.users == 0:
            bpy.data.materials.remove(mat)

    # Images are shared by materials, so remove only Mozi-managed images with
    # no remaining users.  This keeps images used by ordinary mesh materials.
    for image in list(bpy.data.images):
        if image.users == 0 and image.get(PROP_PACK_HASH):
            bpy.data.images.remove(image)


def notify_yefira_update(obj: Optional[bpy.types.Object] = None) -> None:
    """Notify Geometry Nodes world engine to refresh point cloud modifier and node tree."""
    if obj and is_yefira_object(obj):
        try:
            from ...geometry_nodes.world_tree import setup_world_geometry_nodes
            setup_world_geometry_nodes(obj)
        except Exception as e:
            logger.debug(f"Could not refresh Geometry Nodes on {obj.name}: {e}")


from .atlas_integration import (
    extract_atlas_parameters,
    find_active_atlas_material,
    find_all_atlas_chunk_materials,
    find_bound_atlas_material,
    get_or_create_atlas_material,
    parse_atlas_mapping,
    setup_material_slots_for_object,
)


def apply_yefira_atlas_materials(
    obj: bpy.types.Object,
    yefira_atlas_materials: dict[int, bpy.types.Material],
    mapping_data: dict,
    chunks_by_id: Optional[dict[int, dict]] = None,
) -> bool:
    """Apply Atlas materials and point cloud attributes to a Yefira procedural world object.

    Configures dense material slot indices (0..max_chunk_id),
    updates all Set Material nodes across Geometry Node trees and Material Dispatcher,
    populates directional and dimension point attributes, and signals Yefira to refresh.
    """
    if not yefira_atlas_materials:
        return False

    primary_mat = yefira_atlas_materials.get(0) or next(iter(yefira_atlas_materials.values()), None)
    if not primary_mat:
        return False

    # Chunk IDs are the Geometry Nodes material indices. Give the point-cloud
    # a dense, deterministic slot table matching chunk IDs 0..max_chunk_id.
    old_materials = list(obj.data.materials)
    obj.data.materials.clear()
    max_chunk_id = max(yefira_atlas_materials.keys())
    for chunk_id in range(max_chunk_id + 1):
        chunk_material = yefira_atlas_materials.get(chunk_id)
        if chunk_material is None:
            raise RuntimeError(f"Atlas mapping is missing material chunk {chunk_id}")
        # The mesh slot plus Geometry Nodes Set Material node are real users.
        # Do not force a fake user: it prevents Blender's normal orphan purge
        # from reclaiming old Yefira atlas materials and images.
        chunk_material.use_fake_user = False
        obj.data.materials.append(chunk_material)

    # Update modifier Set Material node and nested Material Dispatcher sub-groups
    _update_yefira_geometry_node_materials(obj, yefira_atlas_materials)
    _release_replaced_yefira_atlas_resources(old_materials, yefira_atlas_materials.values())

    # Configure mesh point-cloud attributes
    chunk_0 = (chunks_by_id or {}).get(0, {})
    chunk_1 = (chunks_by_id or {}).get(1, {})
    setup_yefira_point_cloud_attributes(
        mesh=obj.data,
        mapping_data=mapping_data,
        primary_mat=primary_mat,
        chunk_0=chunk_0,
        chunk_1=chunk_1,
    )

    # The dispatcher above already updates an existing world tree.  Re-running
    # full world-tree setup here dirties the entire Geometry Nodes graph a
    # second time and often evaluates only after the progress UI reached 100%.
    # Setup is only needed for an imported/legacy object without the modifier.
    world_modifier = obj.modifiers.get(WORLD_MODIFIER_NAME)
    if not world_modifier or not world_modifier.node_group:
        notify_yefira_update(obj)

    return True

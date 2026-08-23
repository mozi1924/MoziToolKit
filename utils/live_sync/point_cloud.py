"""
Ultra-fast Point Cloud Builder for MoziToolKit Live Sync and Yefira.
Emits pure point vertices and attributes for Blender native Geometry Nodes execution.
Zero face generation in Python -> 100% crash-free, sub-millisecond updates.
"""

from __future__ import annotations
import bpy
import logging
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, Union

from .storage import VoxelStorage, block_key
from .classifier import parse_and_classify, BlockTypeEnum, ParsedBlock, atlas_lookup_keys, _atlas_lookup_keys
from .template_catalog import get_or_create_template_collection, get_template_index_map
from .constants import (
    BLOCK_CENTER, BLOCK_KEY, BLOCK_STATE, BLOCK_TYPE, CONTRACT_VERSION,
    DIRECTIONAL_FACE_V_FLIP,
    FACES, INSTANCE_ROTATION, MC_POSITION, MTK_ANIM_ATLAS_HEIGHT,
    MTK_ANIM_ATLAS_WIDTH, MTK_ANIM_FRAME_HEIGHT, MTK_ANIM_FRAME_WIDTH,
    MTK_ATLAS_HEIGHT, MTK_ATLAS_WIDTH, MTK_BIOME_TINT_COLOR,
    MTK_BIOME_TINT_DATA, MTK_EMISSIVE, MTK_IS_OPAQUE, MTK_MATERIAL_ID,
    MTK_TILE_SIZE, MTK_TILES_PER_ROW, TEMPLATE_INDEX, clear_point_attributes,
    face_attribute,
)
from ..mc_baker import StateBaker

DEFAULT_CLIENT_JAR = "/Users/jaxlocke/26.2-Fabric.jar"

_GLOBAL_STATE_BAKER = StateBaker(
    jar_path=DEFAULT_CLIENT_JAR if Path(DEFAULT_CLIENT_JAR).exists() else None
)


def set_baker_resource_source(source_path: str | Path) -> None:
    """Configure or update the resource pack/JAR source for DCC-side blockstate baking."""
    _GLOBAL_STATE_BAKER.set_resource_source(source_path)


logger = logging.getLogger("MoziToolKit.LiveSync")


class PointCloudBuildResult(NamedTuple):
    world_obj: Optional[bpy.types.Object]
    point_count: int
    cubes_count: int
    props_count: int
    fluids_count: int


def _resolve_template_index(template_indices: dict[str, int], name: str) -> int:
    """Resolve a block template name to a Collection index with prefix/suffix fallback."""
    if not name or not template_indices:
        return 0
    if name in template_indices:
        return template_indices[name]
    low = name.lower()
    if low in template_indices:
        return template_indices[low]

    for key, idx in template_indices.items():
        if low.endswith(key) or key.endswith(low):
            return idx
        if "bed_head" in low and "bed_head" in key:
            return idx
        if "bed_foot" in low and "bed_foot" in key:
            return idx
        if "door" in low and "lower" in low and "door_lower" in key:
            return idx
        if "door" in low and "upper" in low and "door_upper" in key:
            return idx
        if "stairs" in low and "stairs" in key:
            return idx
        if "slab" in low and "slab" in key:
            return idx
        if "chest" in low and "chest" in key:
            return idx
        if "torch" in low and "torch" in key:
            return idx
        if "plant" in low and "plant" in key:
            return idx
        if "carpet" in low and "carpet" in key:
            return idx
    return 0


def update_world_point_cloud(
    context: bpy.types.Context,
    storage: VoxelStorage,
    filter_air: bool = True,
    atlas_mapping_dict: Optional[dict[str, Any]] = None,
    block_face_lut: Optional[dict[str, list[tuple[int, int]]]] = None,
    block_face_chunk_lut: Optional[dict[str, list[int]]] = None,
    block_face_texture_lut: Optional[dict[str, list[int]]] = None,
    block_face_tint_lut: Optional[dict[str, list[tuple[float, float, float, float]]]] = None,
    block_face_anim_timing_lut: Optional[dict[str, list[tuple[float, float, float, float]]]] = None,
    block_face_anim_frame_size_lut: Optional[dict[str, list[tuple[float, float, float, float]]]] = None,
    block_face_uv_rot_lut: Optional[dict[str, list[float]]] = None,
    block_face_uv_bounds_lut: Optional[dict[str, list[tuple[float, float, float, float]]]] = None,
    atlas_mapping_textures: Optional[dict[str, Any]] = None,
    atlas_width: float = 1024.0,
    atlas_height: float = 1024.0,
    tile_size: float = 16.0,
    tiles_per_row: int = 64,
    anim_atlas_width: float = 896.0,
    anim_atlas_height: float = 1024.0,
    anim_frame_width: float = 16.0,
    anim_frame_height: float = 16.0,
) -> PointCloudBuildResult:
    """
    Constructs or updates the Yefira_World mesh object from storage voxels in Blender C++.
    Writes structured attributes including 6-face Atlas tile coordinates, UV rotations, and animation metadata.
    """
    if storage.size_x == 0 or storage.size_y == 0 or storage.size_z == 0:
        return PointCloudBuildResult(None, 0, 0, 0, 0)

    min_x, min_y, min_z = storage.min_x, storage.min_y, storage.min_z
    size_x, size_y, size_z = storage.size_x, storage.size_y, storage.size_z
    block_map = storage.block_map

    # Ensure template collection exists and fetch instance index map
    template_col = get_or_create_template_collection(context)
    template_indices = get_template_index_map(template_col)

    # Object and Mesh Setup
    obj_name = "Yefira_World"
    mesh_name = "Yefira_World_Mesh"

    if obj_name in bpy.data.objects:
        obj = bpy.data.objects[obj_name]
        mesh = obj.data
    else:
        mesh = bpy.data.meshes.new(mesh_name)
        obj = bpy.data.objects.new(obj_name, mesh)
        obj.location = (0.0, 0.0, 0.0)
        context.collection.objects.link(obj)

    # Attribute Data Lists
    vertices = []
    block_states = []
    block_keys = []
    block_types = []
    instance_indices = []
    rotations = []
    directional_face_v_flips = []
    material_ids = []
    is_opaque_list = []
    emissive_list = []
    tint_colors = []
    tint_datas = []
    mc_positions = []

    # 6-face Atlas tile coordinates (col, row, 0.0)
    tile_east = []
    tile_west = []
    tile_top = []
    tile_bottom = []
    tile_south = []
    tile_north = []
    face_chunks = [[] for _ in range(6)]
    face_textures = [[] for _ in range(6)]
    face_tint_data = [[] for _ in range(6)]
    face_anim_timing = [[] for _ in range(6)]
    face_anim_frame_size = [[] for _ in range(6)]
    face_uv_rot = [[] for _ in range(6)]
    face_uv_bounds = [[] for _ in range(6)]

    palette_mat_cache = {}
    cubes_count = 0
    props_count = 0
    fluids_count = 0

    import json

    # Fast iteration over voxel map
    for (abs_x, abs_y, abs_z), state_str in block_map.items():
        json_obj = None
        if state_str and state_str.startswith("{") and state_str.endswith("}"):
            try:
                json_obj = json.loads(state_str)
            except Exception:
                json_obj = None

        if json_obj and isinstance(json_obj, dict):
            raw_state = json_obj.get("state", state_str)
            parsed: ParsedBlock = parse_and_classify(raw_state)
            if "type" in json_obj:
                parsed.block_type = int(json_obj["type"])
            if "opaque" in json_obj:
                parsed.is_opaque = int(json_obj["opaque"])
            if "emissive" in json_obj:
                parsed.is_emissive = int(json_obj["emissive"])
            if "emissive_level" in json_obj:
                parsed.emissive_level = float(json_obj["emissive_level"])
        else:
            parsed: ParsedBlock = parse_and_classify(state_str)

        if filter_air and parsed.block_type == BlockTypeEnum.AIR:
            continue

        # Metric 1:1 Scale & Centering
        # Standard right-handed transform (det = +1, Rx(-90)):
        # Blender X = MC X (East = +X, West = -X)
        # Blender Y = -MC Z (North = +Y, South = -Y)
        # Blender Z = MC Y (Up = +Z, Down = -Z)
        vx = (abs_x - min_x) - size_x / 2.0 + 0.5
        vy = -((abs_z - min_z) - size_z / 2.0 + 0.5)
        vz = (abs_y - min_y) + 0.5

        vertices.append((vx, vy, vz))
        block_states.append(parsed.full_state)
        # Do not use a point index as a block address. This value survives
        # point-cloud rebuilds and is the canonical DCC-facing identity.
        block_keys.append(block_key(abs_x, abs_y, abs_z))
        block_types.append(parsed.block_type)

        # Template Index for Collection Info Pick Instance
        tmpl_idx = _resolve_template_index(template_indices, parsed.template_name)
        instance_indices.append(tmpl_idx)

        rotations.append(parsed.rot_euler)
        directional_face_v_flips.append(int(parsed.name in (
            "command_block", "chain_command_block", "repeating_command_block",
        )))
        tint_colors.append(parsed.tint_color)
        tint_datas.append(parsed.tint_data)
        mc_positions.append((float(abs_x), float(abs_y), float(abs_z)))
        is_opaque_list.append(int(parsed.is_opaque))
        emissive_list.append(int(parsed.is_emissive))

        atlas_keys = _atlas_lookup_keys(parsed)

        # Material ID resolution (Atlas mapping or palette hash)
        mat_id = None
        if atlas_mapping_dict:
            mat_id = next((atlas_mapping_dict[key] for key in atlas_keys if key in atlas_mapping_dict), None)
        if mat_id is None:
            if parsed.name not in palette_mat_cache:
                palette_mat_cache[parsed.name] = len(palette_mat_cache)
            mat_id = palette_mat_cache[parsed.name]
        material_ids.append(mat_id)

        # Primary DCC-side resolution using StateBaker (computes exact UV rotations, models, and textures)
        baked_model = _GLOBAL_STATE_BAKER.bake_block_state(parsed.full_state)
        for face_idx, face_name in enumerate(FACES):
            baked_face = baked_model.faces[face_idx]
            tex_name = baked_face.texture
            uv_r = float(baked_face.uv_rot)
            uv_b = tuple(baked_face.uv_bounds)
            tint_idx = int(baked_face.tint_index)

            # Match texture with Atlas mapping dict
            loc = None
            if atlas_mapping_textures:
                if tex_name:
                    short_tex = tex_name.split(":", 1)[-1].removeprefix("block/")
                    loc = atlas_mapping_textures.get(tex_name) or atlas_mapping_textures.get(short_tex)
                if loc is None and parsed.name in atlas_mapping_textures:
                    loc = atlas_mapping_textures.get(parsed.name)

            if loc and loc.get("kind") == "animation":
                px = int(loc.get("pixel_x", 0))
                fw = max(1, int(loc.get("frame_width", 16)))
                col = px // fw
                row = 0
                cid = int(loc.get("chunk_id", 1))
                tid = int(loc.get("texture_id", 0))
            elif loc:
                col = int(loc.get("tile_column", 0))
                row = int(loc.get("tile_row", 0))
                cid = int(loc.get("chunk_id", 0))
                tid = int(loc.get("texture_id", 0))
            else:
                # Fallback to LUT tables
                face_coords = _resolve_face_values(block_face_lut, parsed, (0, 0), is_coord=True)
                col, row = face_coords[face_idx]
                cid = int(_resolve_face_values(block_face_chunk_lut, parsed, 0)[face_idx])
                tid = int(_resolve_face_values(block_face_texture_lut, parsed, 0)[face_idx])

            # If baked texture name resolved a valid texture in LUT
            if loc is None and tex_name and block_face_chunk_lut and block_face_texture_lut:
                c_lut = (
                    block_face_chunk_lut.get(tex_name.split(":", 1)[-1].removeprefix("block/"))
                    or block_face_chunk_lut.get(tex_name)
                    or block_face_chunk_lut.get(parsed.name)
                    or block_face_chunk_lut.get(parsed.full_state)
                )
                if c_lut and len(c_lut) > face_idx:
                    cid = int(c_lut[face_idx])

                t_lut = (
                    block_face_texture_lut.get(tex_name.split(":", 1)[-1].removeprefix("block/"))
                    or block_face_texture_lut.get(tex_name)
                    or block_face_texture_lut.get(parsed.name)
                    or block_face_texture_lut.get(parsed.full_state)
                )
                if t_lut and len(t_lut) > face_idx:
                    tid = int(t_lut[face_idx])

            if face_idx == 0: tile_east.append((col, row, 0.0))
            elif face_idx == 1: tile_west.append((col, row, 0.0))
            elif face_idx == 2: tile_top.append((col, row, 0.0))
            elif face_idx == 3: tile_bottom.append((col, row, 0.0))
            elif face_idx == 4: tile_south.append((col, row, 0.0))
            elif face_idx == 5: tile_north.append((col, row, 0.0))

            face_chunks[face_idx].append(cid)
            face_textures[face_idx].append(tid)

            if tint_idx >= 0 or (loc and loc.get("default_tint_weight", 0.0) > 0):
                base_w = float(loc.get("default_base_tint_weight", 1.0)) if loc else 1.0
                over_w = float(loc.get("default_overlay_tint_weight", 0.0)) if loc else 0.0
                tint_w = float(loc.get("default_tint_weight", 1.0)) if loc else 1.0
                is_h = 1.0 if loc and loc.get("is_hardcoded", False) else 0.0
                face_tint_data[face_idx].append((base_w, over_w, tint_w, is_h))
            elif loc is None and block_face_tint_lut:
                tint_lut = block_face_tint_lut.get(parsed.name) or block_face_tint_lut.get(parsed.full_state)
                if tint_lut and len(tint_lut) > face_idx:
                    face_tint_data[face_idx].append(tint_lut[face_idx])
                else:
                    face_tint_data[face_idx].append((0.0, 0.0, 0.0, 0.0))
            else:
                face_tint_data[face_idx].append((0.0, 0.0, 0.0, 0.0))

            f_count = float(loc.get("frame_count", 1)) if loc else 1.0
            f_time = float(loc.get("frametime", 1)) if loc else 1.0
            interp = 1.0 if loc and loc.get("interpolate", False) else 0.0
            if loc is None and block_face_anim_timing_lut:
                at_lut = block_face_anim_timing_lut.get(parsed.name) or block_face_anim_timing_lut.get(parsed.full_state)
                if at_lut and len(at_lut) > face_idx:
                    face_anim_timing[face_idx].append(at_lut[face_idx])
                else:
                    face_anim_timing[face_idx].append((f_count, f_time, interp, 0.0))
            else:
                face_anim_timing[face_idx].append((f_count, f_time, interp, 0.0))

            fw = float(loc.get("frame_width", tile_size)) if loc else float(tile_size)
            fh = float(loc.get("frame_height", tile_size)) if loc else float(tile_size)
            if loc is None and block_face_anim_frame_size_lut:
                as_lut = block_face_anim_frame_size_lut.get(parsed.name) or block_face_anim_frame_size_lut.get(parsed.full_state)
                if as_lut and len(as_lut) > face_idx:
                    face_anim_frame_size[face_idx].append(as_lut[face_idx])
                else:
                    face_anim_frame_size[face_idx].append((fw, fh, 0.0, 0.0))
            else:
                face_anim_frame_size[face_idx].append((fw, fh, 0.0, 0.0))

            face_uv_rot[face_idx].append(uv_r)
            face_uv_bounds[face_idx].append((float(uv_b[0]), float(uv_b[1]), float(uv_b[2]), float(uv_b[3])))

        # Statistics
        if parsed.block_type == BlockTypeEnum.CUBE:
            cubes_count += 1
        elif parsed.block_type == BlockTypeEnum.FLUID:
            fluids_count += 1
        else:
            props_count += 1

    # 1. Update pure point geometry in Blender C++
    mesh.clear_geometry()
    mesh.from_pydata(vertices, [], [])
    mesh.update()
    # Geometry clearing does not remove Blender attributes. Clear the whole
    # declared source schema so a rebuild cannot leave dead fields behind.
    clear_point_attributes(mesh)
    mesh["yefira:attribute_contract"] = CONTRACT_VERSION

    num_pts = len(vertices)
    if num_pts > 0:
        # 2. Fast Attribute Writes
        _write_int_attribute(mesh, BLOCK_TYPE, block_types)
        _write_int_attribute(mesh, TEMPLATE_INDEX, instance_indices)
        _write_int_attribute(mesh, MTK_MATERIAL_ID, material_ids)
        _write_int_attribute(mesh, MTK_IS_OPAQUE, is_opaque_list)
        _write_int_attribute(mesh, MTK_EMISSIVE, emissive_list)
        # Atlas metadata is emitted as geometry attributes rather than
        # Geometry Nodes modifier inputs. This makes a material replacement
        # deterministic and removes user-adjustable sync state.
        _write_float_attribute(mesh, MTK_ATLAS_WIDTH, [float(atlas_width)] * num_pts)
        _write_float_attribute(mesh, MTK_ATLAS_HEIGHT, [float(atlas_height)] * num_pts)
        _write_float_attribute(mesh, MTK_TILE_SIZE, [float(tile_size)] * num_pts)
        _write_float_attribute(mesh, MTK_TILES_PER_ROW, [float(tiles_per_row)] * num_pts)
        _write_float_attribute(mesh, MTK_ANIM_ATLAS_WIDTH, [float(anim_atlas_width)] * num_pts)
        _write_float_attribute(mesh, MTK_ANIM_ATLAS_HEIGHT, [float(anim_atlas_height)] * num_pts)
        _write_float_attribute(mesh, MTK_ANIM_FRAME_WIDTH, [float(anim_frame_width)] * num_pts)
        _write_float_attribute(mesh, MTK_ANIM_FRAME_HEIGHT, [float(anim_frame_height)] * num_pts)
        _write_float_vector_attribute(mesh, INSTANCE_ROTATION, rotations)
        _write_int_attribute(mesh, DIRECTIONAL_FACE_V_FLIP, directional_face_v_flips)
        _write_float_vector_attribute(mesh, BLOCK_CENTER, vertices)
        _write_float_vector_attribute(mesh, MC_POSITION, mc_positions)
        for face, values in zip(FACES, (tile_east, tile_west, tile_top, tile_bottom, tile_south, tile_north)):
            _write_float_vector_attribute(mesh, face_attribute("tile", face), values)
        for face, values in zip(FACES, face_chunks):
            _write_int_attribute(mesh, face_attribute("chunk", face), values)
        for face, values in zip(FACES, face_textures):
            _write_int_attribute(mesh, face_attribute("texture", face), values)
        for face, values in zip(FACES, face_tint_data):
            _write_float_color_attribute(mesh, face_attribute("tint_data", face), values)
        for face, values in zip(FACES, face_anim_timing):
            _write_float_color_attribute(mesh, face_attribute("anim_timing", face), values)
        for face, values in zip(FACES, face_anim_frame_size):
            _write_float_color_attribute(mesh, face_attribute("anim_frame_size", face), values)
        for face, values in zip(FACES, face_uv_rot):
            _write_float_attribute(mesh, face_attribute("uv_rot", face), values)
        for face, values in zip(FACES, face_uv_bounds):
            _write_float_color_attribute(mesh, face_attribute("uv_bounds", face), values)
        _write_float_color_attribute(mesh, MTK_BIOME_TINT_COLOR, tint_colors)
        _write_float_color_attribute(mesh, MTK_BIOME_TINT_DATA, tint_datas)
        _write_string_attribute(mesh, BLOCK_STATE, block_states)
        _write_string_attribute(mesh, BLOCK_KEY, block_keys)

    return PointCloudBuildResult(
        world_obj=obj,
        point_count=num_pts,
        cubes_count=cubes_count,
        props_count=props_count,
        fluids_count=fluids_count,
    )


def _resolve_face_values(lut, parsed: ParsedBlock, default, is_coord: bool = False) -> list:
    """Resolve 6-face values (+X, -X, +Y, -Y, +Z, -Z) for a parsed block from a lookup table."""
    if not lut:
        return [default] * 6

    # 1. Direct lookup in LUT via atlas_lookup_keys
    atlas_keys = _atlas_lookup_keys(parsed)
    raw = next((lut[key] for key in atlas_keys if key in lut), None)
    if raw is not None:
        if isinstance(raw, (list, tuple)) and len(raw) >= 6:
            if not is_coord or isinstance(raw[0], (list, tuple)):
                return [type(default)(v) if isinstance(default, int) else tuple(v) for v in raw[:6]]

    # 2. Dynamic state-aware multi-face fallback from single-entry items in lut
    name = parsed.name
    props = parsed.props
    is_lit = props.get("lit") == "true"

    def get_val(k: str):
        val = lut.get(k)
        if val is None:
            return None
        if isinstance(val, (list, tuple)) and len(val) == 6:
            return val
        return type(default)(val) if isinstance(default, int) else tuple(val)

    # Furnace, Blast Furnace, Smoker
    if name in ("furnace", "blast_furnace", "smoker"):
        top = get_val(f"{name}_top") or get_val(f"{name}_bottom") or get_val("furnace_top")
        bottom = get_val(f"{name}_bottom") or top
        side = get_val(f"{name}_side") or get_val("furnace_side")
        front = (get_val(f"{name}_front_on") if is_lit else None) or get_val(f"{name}_front") or side
        top = top or side or front or default
        bottom = bottom or top
        side = side or top
        front = front or side
        return [side, side, top, bottom, side, front]

    # Beehive, Bee Nest
    if name in ("beehive", "bee_nest"):
        is_honey = props.get("honey_level") == "5"
        top = get_val(f"{name}_top")
        bottom = get_val(f"{name}_bottom") or top
        side = get_val(f"{name}_side")
        front = (get_val(f"{name}_front_honey") if is_honey else None) or get_val(f"{name}_front") or side
        top = top or side or front or default
        bottom = bottom or top
        side = side or top
        front = front or side
        return [side, side, top, bottom, side, front]

    # Respawn Anchor
    if name == "respawn_anchor":
        charges = props.get("charges", "0")
        has_charges = str(charges) not in ("0", "")
        top = (get_val("respawn_anchor_top") if has_charges else None) or get_val("respawn_anchor_top_off")
        bottom = get_val("respawn_anchor_bottom") or top
        side = get_val(f"respawn_anchor_side{charges}") or get_val("respawn_anchor_side0") or top
        top = top or default
        bottom = bottom or top
        side = side or top
        return [side, side, top, bottom, side, side]

    # Carved Pumpkin, Jack o'Lantern
    if name in ("carved_pumpkin", "jack_o_lantern"):
        top = get_val("pumpkin_top")
        side = get_val("pumpkin_side")
        front = get_val(name) or side
        top = top or side or front or default
        side = side or top
        front = front or side
        return [side, side, top, top, side, front]

    # Dispenser, Dropper
    if name in ("dispenser", "dropper"):
        top = get_val(f"{name}_top") or get_val("furnace_top")
        side = get_val(f"{name}_side") or get_val("furnace_side")
        front = get_val(f"{name}_front") or side
        top = top or side or front or default
        side = side or top
        front = front or side
        return [side, side, top, top, side, front]

    # Observer
    if name == "observer":
        top = get_val("observer_top")
        side = get_val("observer_side")
        back = get_val("observer_back") or side
        front = get_val("observer_front") or side
        top = top or side or front or default
        side = side or top
        back = back or side
        front = front or side
        return [side, side, top, side, back, front]

    # Barrel
    if name == "barrel":
        is_open = props.get("open") == "true"
        top = (get_val("barrel_top_open") if is_open else None) or get_val("barrel_top")
        bottom = get_val("barrel_bottom") or top
        side = get_val("barrel_side") or top
        top = top or default
        bottom = bottom or top
        side = side or top
        return [side, side, top, bottom, side, side]

    # Grass Block, Podzol, Mycelium
    if name in ("grass_block", "podzol", "mycelium"):
        snowy = props.get("snowy") == "true"
        top = get_val(f"{name}_top")
        bottom = get_val("dirt") or top
        side = (get_val("grass_block_snow") if snowy else None) or get_val(f"{name}_side") or top
        top = top or default
        bottom = bottom or top
        side = side or top
        return [side, side, top, bottom, side, side]

    # Red Mushroom Block, Brown Mushroom Block, Mushroom Stem
    if name in ("red_mushroom_block", "brown_mushroom_block", "mushroom_stem"):
        skin = get_val(name) or default
        inside = get_val("mushroom_block_inside") or skin
        top = inside if props.get("up") == "false" else skin
        bottom = inside if props.get("down") == "false" else skin
        east = inside if props.get("east") == "false" else skin
        west = inside if props.get("west") == "false" else skin
        south = inside if props.get("south") == "false" else skin
        north = inside if props.get("north") == "false" else skin
        return [east, west, top, bottom, south, north]

    # Axis Blocks (Local Base: Top/Bottom=Top/End texture, Sides=Side/Bark texture)
    is_axis_block = "axis" in props or name.endswith(("_log", "_wood", "_stem", "_hyphae", "basalt", "hay_block", "bone_block"))
    if is_axis_block:
        top_tex = get_val(f"{name}_top") or get_val(f"{name}_end") or get_val(name)
        side_tex = get_val(f"{name}_side") or get_val(name) or top_tex
        top_tex = top_tex or side_tex or default
        side_tex = side_tex or top_tex
        return [side_tex, side_tex, top_tex, top_tex, side_tex, side_tex]

    # Redstone Lamp
    if name == "redstone_lamp":
        lamp = (get_val("redstone_lamp_on") if is_lit else None) or get_val("redstone_lamp") or default
        return [lamp] * 6

    # Fallback to single entry
    val = get_val(name) or default
    return [type(default)(val) if isinstance(default, int) else tuple(val)] * 6


def _lookup_face_values(lut, parsed: ParsedBlock, default) -> list:
    return _resolve_face_values(lut, parsed, default)


def _write_float_attribute(mesh: bpy.types.Mesh, name: str, values: list[float]):
    attr = mesh.attributes.get(name)
    if not attr or attr.data_type != 'FLOAT' or attr.domain != 'POINT' or len(attr.data) != len(values):
        if attr:
            mesh.attributes.remove(attr)
        attr = mesh.attributes.new(name=name, type='FLOAT', domain='POINT')
    attr.data.foreach_set('value', values)


def _write_int_attribute(mesh: bpy.types.Mesh, name: str, values: list[int]):
    attr = mesh.attributes.get(name)
    if not attr or attr.data_type != 'INT' or attr.domain != 'POINT' or len(attr.data) != len(values):
        if attr:
            mesh.attributes.remove(attr)
        attr = mesh.attributes.new(name=name, type='INT', domain='POINT')
    attr.data.foreach_set('value', values)


def _write_float_vector_attribute(mesh: bpy.types.Mesh, name: str, vectors: list[tuple[float, float, float]]):
    attr = mesh.attributes.get(name)
    if not attr or attr.data_type != 'FLOAT_VECTOR' or attr.domain != 'POINT' or len(attr.data) != len(vectors):
        if attr:
            mesh.attributes.remove(attr)
        attr = mesh.attributes.new(name=name, type='FLOAT_VECTOR', domain='POINT')
    
    # Flatten tuples for foreach_set
    flat = [c for v in vectors for c in v]
    attr.data.foreach_set('vector', flat)


def _write_float_color_attribute(mesh: bpy.types.Mesh, name: str, colors: list[tuple[float, float, float, float]]):
    attr = mesh.attributes.get(name)
    if not attr or attr.data_type != 'FLOAT_COLOR' or attr.domain != 'POINT' or len(attr.data) != len(colors):
        if attr:
            mesh.attributes.remove(attr)
        attr = mesh.attributes.new(name=name, type='FLOAT_COLOR', domain='POINT')
    
    flat = [c for col in colors for c in col]
    attr.data.foreach_set('color', flat)


def _write_string_attribute(mesh: bpy.types.Mesh, name: str, strings: list[str | bytes]):
    attr = mesh.attributes.get(name)
    if not attr or attr.data_type != 'STRING' or attr.domain != 'POINT' or len(attr.data) != len(strings):
        if attr:
            mesh.attributes.remove(attr)
        attr = mesh.attributes.new(name=name, type='STRING', domain='POINT')
    for i, s in enumerate(strings):
        # Blender's RNA string-attribute API uses UTF-8 bytes even though the
        # logical value is text. Normalise here so block states and stable
        # ``mc_block_key`` values have one safe writer.
        attr.data[i].value = s if isinstance(s, bytes) else s.encode('utf-8')

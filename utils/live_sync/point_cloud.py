"""
Ultra-fast Point Cloud Builder for MoziToolKit Live Sync and Yefira.
Emits pure point vertices and attributes for Blender native Geometry Nodes execution.
Zero face generation in Python -> 100% crash-free, sub-millisecond updates.
"""

from __future__ import annotations
import bpy
import logging
import numpy as np
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, Union

from .storage import VoxelStorage, block_key
from .classifier import parse_and_classify, BlockTypeEnum, ParsedBlock, atlas_lookup_keys
from .template_catalog import get_or_create_template_collection, get_template_index_map
from .constants import (
    BLOCK_CENTER, BLOCK_KEY, BLOCK_STATE, BLOCK_TYPE, CONTRACT_VERSION,
    DEFAULT_ANIM_ATLAS_HEIGHT, DEFAULT_ANIM_ATLAS_WIDTH,
    DEFAULT_ANIM_FRAME_HEIGHT, DEFAULT_ANIM_FRAME_WIDTH,
    DEFAULT_ATLAS_HEIGHT, DEFAULT_ATLAS_WIDTH, DEFAULT_TILE_SIZE,
    DEFAULT_TILES_PER_ROW, DEFAULT_WORLD_MESH_NAME, DEFAULT_WORLD_OBJECT_NAME,
    DIRECTIONAL_FACE_V_FLIP,
    FACES, INSTANCE_ROTATION, MC_POSITION, MTK_ANIM_ATLAS_HEIGHT,
    MTK_ANIM_ATLAS_WIDTH, MTK_ANIM_FRAME_HEIGHT, MTK_ANIM_FRAME_WIDTH,
    MTK_ATLAS_HEIGHT, MTK_ATLAS_WIDTH, MTK_BIOME_TINT_COLOR,
    MTK_BIOME_TINT_DATA, MTK_EMISSIVE, MTK_IS_OPAQUE, MTK_MATERIAL_ID,
    MTK_TILE_SIZE, MTK_TILES_PER_ROW, TEMPLATE_INDEX, clear_point_attributes,
    face_attribute,
)
from ..mc_baker import StateBaker

_GLOBAL_STATE_BAKER = StateBaker()
_last_pack_fingerprint: Optional[tuple[str, ...]] = None
_last_configured_loader = None
_STATE_ATTR_CACHE: dict[str, Any] = {}
_LAST_ATLAS_FINGERPRINT: Optional[tuple] = None


def refresh_baker_sources() -> None:
    """Synchronize StateBaker resource loaders with the configured Resource Pack Stack."""
    global _last_pack_fingerprint, _last_configured_loader
    try:
        from ..materials.pack_stack import get_configured_pack_stack, get_pack_stack_fingerprint
        current_fingerprint = get_pack_stack_fingerprint()
        if current_fingerprint != _last_pack_fingerprint:
            _last_pack_fingerprint = current_fingerprint
            composite_loader = get_configured_pack_stack().get_composite_loader()
            _last_configured_loader = composite_loader
            _GLOBAL_STATE_BAKER.resource_loader = composite_loader
            _GLOBAL_STATE_BAKER.model_parser.model_loader_fn = composite_loader.load_model if composite_loader else None
            _GLOBAL_STATE_BAKER.state_resolver.blockstate_loader_fn = composite_loader.load_blockstate if composite_loader else None
            _GLOBAL_STATE_BAKER.clear_cache()
            _STATE_ATTR_CACHE.clear()
    except Exception as e:
        logger.debug(f"Could not refresh baker sources from pack stack: {e}")


def clear_state_cache() -> None:
    """Clear precomputed blockstate attribute cache."""
    global _LAST_ATLAS_FINGERPRINT
    _STATE_ATTR_CACHE.clear()
    _LAST_ATLAS_FINGERPRINT = None


def set_baker_resource_source(source_path: str | Path) -> None:
    """Configure or update the resource pack/JAR source for DCC-side blockstate baking."""
    global _last_pack_fingerprint
    _GLOBAL_STATE_BAKER.set_resource_source(source_path)
    try:
        _last_pack_fingerprint = (str(Path(source_path).resolve()),)
    except Exception:
        _last_pack_fingerprint = (str(source_path),)
    _STATE_ATTR_CACHE.clear()


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


class PrecomputedStateAttr:
    __slots__ = (
        'full_state', 'name', 'block_type', 'tmpl_idx', 'rot_euler',
        'is_directional_flip', 'tint_color', 'tint_data', 'is_opaque', 'is_emissive',
        'mat_id', 'tile_coords', 'face_chunks', 'face_textures', 'face_tint_data',
        'face_anim_timing', 'face_anim_frame_size', 'face_uv_rot', 'face_uv_bounds'
    )

    def __init__(
        self,
        state_str: str,
        template_indices: dict[str, int],
        atlas_mapping_dict: dict[str, Any],
        atlas_mapping_textures: dict[str, Any],
        block_face_lut: dict[str, Any],
        block_face_chunk_lut: dict[str, Any],
        block_face_texture_lut: dict[str, Any],
        block_face_tint_lut: dict[str, Any],
        block_face_anim_timing_lut: dict[str, Any],
        block_face_anim_frame_size_lut: dict[str, Any],
        block_face_uv_rot_lut: Optional[dict[str, Any]] = None,
        block_face_uv_bounds_lut: Optional[dict[str, Any]] = None,
        tile_size: float = DEFAULT_TILE_SIZE,
    ):
        import json
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

        self.full_state = parsed.full_state
        self.name = parsed.name
        self.block_type = parsed.block_type
        self.tmpl_idx = _resolve_template_index(template_indices, parsed.template_name)
        self.rot_euler = parsed.rot_euler
        self.is_directional_flip = int(parsed.name in ("command_block", "chain_command_block", "repeating_command_block"))
        self.tint_color = parsed.tint_color
        self.tint_data = parsed.tint_data
        self.is_opaque = int(parsed.is_opaque)
        self.is_emissive = int(parsed.is_emissive)

        atlas_keys = atlas_lookup_keys(parsed)
        mat_id = next((atlas_mapping_dict[key] for key in atlas_keys if key in atlas_mapping_dict), None) if atlas_mapping_dict else None
        if mat_id is None:
            mat_id = 0
        self.mat_id = mat_id

        json_faces = json_obj.get("faces") if (json_obj and isinstance(json_obj, dict) and isinstance(json_obj.get("faces"), dict)) else None
        baked_model = _GLOBAL_STATE_BAKER.bake_block_state(parsed.full_state) if not json_faces else None

        tiles = []
        chunks = []
        textures = []
        tint_datas = []
        anim_timings = []
        anim_frame_sizes = []
        uv_rots = []
        uv_bounds_list = []

        for face_idx, face_name in enumerate(FACES):
            if json_faces and face_name in json_faces:
                face_info = json_faces[face_name]
                tex_name = face_info.get("tex")
                uv_r = float(face_info.get("rot", 0))
                uv_b = tuple(face_info.get("uv", [0.0, 0.0, 1.0, 1.0]))
                tint_idx = int(face_info.get("tint", -1))
            else:
                baked_face = baked_model.faces[face_idx]
                tex_name = baked_face.texture
                uv_r = float(baked_face.uv_rot)
                uv_b = tuple(baked_face.uv_bounds)
                tint_idx = int(baked_face.tint_index)

            loc = None
            if atlas_mapping_textures:
                if tex_name:
                    short_tex = tex_name.split(":", 1)[-1].removeprefix("block/")
                    loc = (
                        atlas_mapping_textures.get(tex_name)
                        or atlas_mapping_textures.get(f"minecraft:{short_tex}")
                        or atlas_mapping_textures.get(f"minecraft:block/{short_tex}")
                        or atlas_mapping_textures.get(short_tex)
                    )
                if loc is None and parsed.name in atlas_mapping_textures:
                    loc = atlas_mapping_textures.get(parsed.name)

            if loc and loc.get("kind") == "animation":
                px = int(loc.get("pixel_x", 0))
                fw = max(1, int(loc.get("frame_width", 16)))
                col = float(px // fw)
                row = 0.0
                cid = int(loc.get("chunk_id", 0))
                tid = int(loc.get("texture_id", 0))
            elif loc:
                col = float(loc.get("tile_column", 0))
                row = float(loc.get("tile_row", 0))
                cid = int(loc.get("chunk_id", 0))
                tid = int(loc.get("texture_id", 0))
            else:
                face_coords = _resolve_face_values(block_face_lut, parsed, (0, 0), is_coord=True)
                col, row = float(face_coords[face_idx][0]), float(face_coords[face_idx][1])
                cid = int(_resolve_face_values(block_face_chunk_lut, parsed, 0)[face_idx])
                tid = int(_resolve_face_values(block_face_texture_lut, parsed, 0)[face_idx])

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

            tiles.append((col, row, 0.0))
            chunks.append(cid)
            textures.append(tid)

            if tint_idx >= 0 or (loc and loc.get("default_tint_weight", 0.0) > 0):
                base_w = float(loc.get("default_base_tint_weight", 1.0)) if loc else 1.0
                over_w = float(loc.get("default_overlay_tint_weight", 0.0)) if loc else 0.0
                tint_w = float(loc.get("default_tint_weight", 1.0)) if loc else 1.0
                is_h = 1.0 if loc and loc.get("is_hardcoded", False) else 0.0
                tint_datas.append((base_w, over_w, tint_w, is_h))
            elif loc is None and block_face_tint_lut:
                tint_lut = block_face_tint_lut.get(parsed.name) or block_face_tint_lut.get(parsed.full_state)
                if tint_lut and len(tint_lut) > face_idx:
                    tint_datas.append(tuple(float(v) for v in tint_lut[face_idx]))
                else:
                    tint_datas.append((0.0, 0.0, 0.0, 0.0))
            else:
                tint_datas.append((0.0, 0.0, 0.0, 0.0))

            f_count = float(loc.get("frame_count", 1)) if loc else 1.0
            f_time = float(loc.get("frametime", 1)) if loc else 1.0
            interp = 1.0 if loc and loc.get("interpolate", False) else 0.0
            if loc is None and block_face_anim_timing_lut:
                at_lut = block_face_anim_timing_lut.get(parsed.name) or block_face_anim_timing_lut.get(parsed.full_state)
                if at_lut and len(at_lut) > face_idx:
                    anim_timings.append(tuple(float(v) for v in at_lut[face_idx]))
                else:
                    anim_timings.append((f_count, f_time, interp, 0.0))
            else:
                anim_timings.append((f_count, f_time, interp, 0.0))

            fw = float(loc.get("frame_width", tile_size)) if loc else float(tile_size)
            fh = float(loc.get("frame_height", tile_size)) if loc else float(tile_size)
            if loc is None and block_face_anim_frame_size_lut:
                as_lut = block_face_anim_frame_size_lut.get(parsed.name) or block_face_anim_frame_size_lut.get(parsed.full_state)
                if as_lut and len(as_lut) > face_idx:
                    anim_frame_sizes.append(tuple(float(v) for v in as_lut[face_idx]))
                else:
                    anim_frame_sizes.append((fw, fh, 0.0, 0.0))
            else:
                anim_frame_sizes.append((fw, fh, 0.0, 0.0))

            uv_rots.append(uv_r)
            uv_bounds_list.append((float(uv_b[0]), float(uv_b[1]), float(uv_b[2]), float(uv_b[3])))

        self.tile_coords = tuple(tiles)
        self.face_chunks = tuple(chunks)
        self.face_textures = tuple(textures)
        self.face_tint_data = tuple(tint_datas)
        self.face_anim_timing = tuple(anim_timings)
        self.face_anim_frame_size = tuple(anim_frame_sizes)
        self.face_uv_rot = tuple(uv_rots)
        self.face_uv_bounds = tuple(uv_bounds_list)


def mc_to_blender_local_coords(
    coords: np.ndarray,
    min_x: int,
    min_y: int,
    min_z: int,
    size_x: int,
    size_y: int,
    size_z: int,
) -> np.ndarray:
    """
    Convert Minecraft world coordinates (East=+X, Up=+Y, South=+Z)
    to Blender world origin-centered local coordinates (X=X, Y=-Z, Z=Y+0.5).
    """
    half_x = size_x / 2.0 - 0.5
    half_z = size_z / 2.0 - 0.5

    vertices = np.empty((len(coords), 3), dtype=np.float32)
    vertices[:, 0] = (coords[:, 0] - min_x) - half_x
    vertices[:, 1] = -((coords[:, 2] - min_z) - half_z)
    vertices[:, 2] = (coords[:, 1] - min_y) + 0.5
    return vertices


def update_world_point_cloud(
    context: bpy.types.Context,
    storage: VoxelStorage,
    filter_air: bool = True,
    atlas_mapping_dict: Optional[dict[str, int]] = None,
    block_face_lut: Optional[dict[str, list[tuple[int, int]]]] = None,
    block_face_chunk_lut: Optional[dict[str, list[int]]] = None,
    block_face_texture_lut: Optional[dict[str, list[int]]] = None,
    block_face_tint_lut: Optional[dict[str, list[tuple[float, float, float, float]]]] = None,
    block_face_anim_timing_lut: Optional[dict[str, list[tuple[float, float, float, float]]]] = None,
    block_face_anim_frame_size_lut: Optional[dict[str, list[tuple[float, float, float, float]]]] = None,
    block_face_uv_rot_lut: Optional[dict[str, list[float]]] = None,
    block_face_uv_bounds_lut: Optional[dict[str, list[tuple[float, float, float, float]]]] = None,
    atlas_mapping_textures: Optional[dict[str, Any]] = None,
    atlas_width: float = DEFAULT_ATLAS_WIDTH,
    atlas_height: float = DEFAULT_ATLAS_HEIGHT,
    tile_size: float = DEFAULT_TILE_SIZE,
    tiles_per_row: int = DEFAULT_TILES_PER_ROW,
    anim_atlas_width: float = DEFAULT_ANIM_ATLAS_WIDTH,
    anim_atlas_height: float = DEFAULT_ANIM_ATLAS_HEIGHT,
    anim_frame_width: float = DEFAULT_ANIM_FRAME_WIDTH,
    anim_frame_height: float = DEFAULT_ANIM_FRAME_HEIGHT,
) -> PointCloudBuildResult:
    """
    Constructs or updates the Yefira_World mesh object from storage voxels in Blender C++.
    Writes structured attributes including 6-face Atlas tile coordinates, UV rotations, and animation metadata.
    Utilizes vectorized NumPy operations and precomputed state metadata caching for sub-millisecond execution.
    """
    if storage.size_x == 0 or storage.size_y == 0 or storage.size_z == 0:
        return PointCloudBuildResult(None, 0, 0, 0, 0)

    import numpy as np

    refresh_baker_sources()

    min_x, min_y, min_z = storage.min_x, storage.min_y, storage.min_z
    size_x, size_y, size_z = storage.size_x, storage.size_y, storage.size_z
    block_map = storage.block_map

    template_col = get_or_create_template_collection(context)
    template_indices = get_template_index_map(template_col)

    # Object and Mesh Setup
    obj_name = DEFAULT_WORLD_OBJECT_NAME
    mesh_name = DEFAULT_WORLD_MESH_NAME

    if obj_name in bpy.data.objects:
        obj = bpy.data.objects[obj_name]
        mesh = obj.data
    else:
        mesh = bpy.data.meshes.new(mesh_name)
        obj = bpy.data.objects.new(obj_name, mesh)
        obj.location = (0.0, 0.0, 0.0)
        context.collection.objects.link(obj)

    mapping_dict = atlas_mapping_dict or {}
    mapping_tex = atlas_mapping_textures or {}
    bf_lut = block_face_lut or {}
    bfc_lut = block_face_chunk_lut or {}
    bft_lut = block_face_texture_lut or {}
    bftint_lut = block_face_tint_lut or {}
    bfat_lut = block_face_anim_timing_lut or {}
    bfas_lut = block_face_anim_frame_size_lut or {}
    bfuvr_lut = block_face_uv_rot_lut or {}
    bfuvb_lut = block_face_uv_bounds_lut or {}

    global _LAST_ATLAS_FINGERPRINT
    tmpl_tuple = tuple(obj.name for obj in template_col.objects) if template_col else ()
    current_atlas_fingerprint = (
        id(atlas_mapping_dict),
        len(mapping_dict),
        id(block_face_lut),
        len(bf_lut),
        id(atlas_mapping_textures),
        len(mapping_tex),
        float(tile_size),
        float(atlas_width),
        float(atlas_height),
        float(anim_atlas_width),
        float(anim_atlas_height),
        tmpl_tuple,
    )
    if _LAST_ATLAS_FINGERPRINT is None or current_atlas_fingerprint != _LAST_ATLAS_FINGERPRINT:
        _STATE_ATTR_CACHE.clear()
        _LAST_ATLAS_FINGERPRINT = current_atlas_fingerprint

    # 1. Fetch / precompute palette metadata
    unique_states = list(set(block_map.values()))
    state_to_idx = {s: i for i, s in enumerate(unique_states)}
    num_unique = len(unique_states)

    palette_entries: list[PrecomputedStateAttr] = []
    for s in unique_states:
        entry = _STATE_ATTR_CACHE.get(s)
        if entry is None:
            entry = PrecomputedStateAttr(
                state_str=s,
                template_indices=template_indices,
                atlas_mapping_dict=mapping_dict,
                atlas_mapping_textures=mapping_tex,
                block_face_lut=bf_lut,
                block_face_chunk_lut=bfc_lut,
                block_face_texture_lut=bft_lut,
                block_face_tint_lut=bftint_lut,
                block_face_anim_timing_lut=bfat_lut,
                block_face_anim_frame_size_lut=bfas_lut,
                block_face_uv_rot_lut=bfuvr_lut,
                block_face_uv_bounds_lut=bfuvb_lut,
                tile_size=tile_size,
            )
            _STATE_ATTR_CACHE[s] = entry
        palette_entries.append(entry)

    # 2. Build vectorized palette tables
    p_block_types = np.array([e.block_type for e in palette_entries], dtype=np.int32)
    p_tmpl_indices = np.array([e.tmpl_idx for e in palette_entries], dtype=np.int32)
    p_material_ids = np.array([e.mat_id for e in palette_entries], dtype=np.int32)
    p_is_opaque = np.array([e.is_opaque for e in palette_entries], dtype=np.int32)
    p_emissive = np.array([e.is_emissive for e in palette_entries], dtype=np.int32)
    p_dir_flips = np.array([e.is_directional_flip for e in palette_entries], dtype=np.int32)
    p_rotations = np.array([e.rot_euler for e in palette_entries], dtype=np.float32)
    p_tint_colors = np.array([e.tint_color for e in palette_entries], dtype=np.float32)
    p_tint_datas = np.array([e.tint_data for e in palette_entries], dtype=np.float32)
    p_full_states = [e.full_state for e in palette_entries]

    p_face_tiles = np.array([[e.tile_coords[f] for e in palette_entries] for f in range(6)], dtype=np.float32)
    p_face_chunks = np.array([[e.face_chunks[f] for e in palette_entries] for f in range(6)], dtype=np.int32)
    p_face_textures = np.array([[e.face_textures[f] for e in palette_entries] for f in range(6)], dtype=np.int32)
    p_face_tint_data = np.array([[e.face_tint_data[f] for e in palette_entries] for f in range(6)], dtype=np.float32)
    p_face_anim_timing = np.array([[e.face_anim_timing[f] for e in palette_entries] for f in range(6)], dtype=np.float32)
    p_face_anim_frame_size = np.array([[e.face_anim_frame_size[f] for e in palette_entries] for f in range(6)], dtype=np.float32)
    p_face_uv_rot = np.array([[e.face_uv_rot[f] for e in palette_entries] for f in range(6)], dtype=np.float32)
    p_face_uv_bounds = np.array([[e.face_uv_bounds[f] for e in palette_entries] for f in range(6)], dtype=np.float32)

    # 3. Vectorized extraction of scene blocks
    keys = list(block_map.keys())
    vals = list(block_map.values())
    if not keys:
        mesh.clear_geometry()
        return PointCloudBuildResult(obj, 0, 0, 0, 0)

    coords = np.array(keys, dtype=np.float32)
    state_indices = np.array([state_to_idx[v] for v in vals], dtype=np.int32)

    if filter_air:
        non_air = (p_block_types[state_indices] != BlockTypeEnum.AIR)
        if not np.all(non_air):
            coords = coords[non_air]
            state_indices = state_indices[non_air]
            keys = [keys[i] for i, ok in enumerate(non_air) if ok]

    num_pts = len(state_indices)
    if num_pts == 0:
        mesh.clear_geometry()
        return PointCloudBuildResult(obj, 0, 0, 0, 0)

    vertices = mc_to_blender_local_coords(coords, min_x, min_y, min_z, size_x, size_y, size_z)

    mc_positions = coords
    block_centers = vertices

    block_types = p_block_types[state_indices]
    instance_indices = p_tmpl_indices[state_indices]
    material_ids = p_material_ids[state_indices]
    is_opaque_list = p_is_opaque[state_indices]
    emissive_list = p_emissive[state_indices]
    directional_face_v_flips = p_dir_flips[state_indices]
    rotations = p_rotations[state_indices]
    tint_colors = p_tint_colors[state_indices]
    tint_datas = p_tint_datas[state_indices]

    cubes_count = int(np.count_nonzero(block_types == BlockTypeEnum.CUBE))
    fluids_count = int(np.count_nonzero(block_types == BlockTypeEnum.FLUID))
    props_count = num_pts - cubes_count - fluids_count

    # 4. Geometry update
    if len(mesh.vertices) != num_pts:
        mesh.clear_geometry()
        mesh.vertices.add(num_pts)
    mesh.vertices.foreach_set('co', vertices.ravel())
    mesh.update()
    mesh["yefira:attribute_contract"] = CONTRACT_VERSION

    # 5. Fast in-place attribute writing
    _write_numpy_attribute(mesh, BLOCK_TYPE, 'INT', 'POINT', block_types)
    _write_numpy_attribute(mesh, TEMPLATE_INDEX, 'INT', 'POINT', instance_indices)
    _write_numpy_attribute(mesh, MTK_MATERIAL_ID, 'INT', 'POINT', material_ids)
    _write_numpy_attribute(mesh, MTK_IS_OPAQUE, 'INT', 'POINT', is_opaque_list)
    _write_numpy_attribute(mesh, MTK_EMISSIVE, 'INT', 'POINT', emissive_list)

    const_buf = np.empty(num_pts, dtype=np.float32)
    const_buf.fill(float(atlas_width))
    _write_numpy_attribute(mesh, MTK_ATLAS_WIDTH, 'FLOAT', 'POINT', const_buf)
    const_buf.fill(float(atlas_height))
    _write_numpy_attribute(mesh, MTK_ATLAS_HEIGHT, 'FLOAT', 'POINT', const_buf)
    const_buf.fill(float(tile_size))
    _write_numpy_attribute(mesh, MTK_TILE_SIZE, 'FLOAT', 'POINT', const_buf)
    const_buf.fill(float(tiles_per_row))
    _write_numpy_attribute(mesh, MTK_TILES_PER_ROW, 'FLOAT', 'POINT', const_buf)
    const_buf.fill(float(anim_atlas_width))
    _write_numpy_attribute(mesh, MTK_ANIM_ATLAS_WIDTH, 'FLOAT', 'POINT', const_buf)
    const_buf.fill(float(anim_atlas_height))
    _write_numpy_attribute(mesh, MTK_ANIM_ATLAS_HEIGHT, 'FLOAT', 'POINT', const_buf)
    const_buf.fill(float(anim_frame_width))
    _write_numpy_attribute(mesh, MTK_ANIM_FRAME_WIDTH, 'FLOAT', 'POINT', const_buf)
    const_buf.fill(float(anim_frame_height))
    _write_numpy_attribute(mesh, MTK_ANIM_FRAME_HEIGHT, 'FLOAT', 'POINT', const_buf)

    _write_numpy_attribute(mesh, INSTANCE_ROTATION, 'FLOAT_VECTOR', 'POINT', rotations)
    _write_numpy_attribute(mesh, DIRECTIONAL_FACE_V_FLIP, 'INT', 'POINT', directional_face_v_flips)
    _write_numpy_attribute(mesh, BLOCK_CENTER, 'FLOAT_VECTOR', 'POINT', block_centers)
    _write_numpy_attribute(mesh, MC_POSITION, 'FLOAT_VECTOR', 'POINT', mc_positions)

    for f, face in enumerate(FACES):
        _write_numpy_attribute(mesh, face_attribute("tile", face), 'FLOAT_VECTOR', 'POINT', p_face_tiles[f, state_indices])
        _write_numpy_attribute(mesh, face_attribute("chunk", face), 'INT', 'POINT', p_face_chunks[f, state_indices])
        _write_numpy_attribute(mesh, face_attribute("texture", face), 'INT', 'POINT', p_face_textures[f, state_indices])
        _write_numpy_attribute(mesh, face_attribute("tint_data", face), 'FLOAT_COLOR', 'POINT', p_face_tint_data[f, state_indices])
        _write_numpy_attribute(mesh, face_attribute("anim_timing", face), 'FLOAT_COLOR', 'POINT', p_face_anim_timing[f, state_indices])
        _write_numpy_attribute(mesh, face_attribute("anim_frame_size", face), 'FLOAT_COLOR', 'POINT', p_face_anim_frame_size[f, state_indices])
        _write_numpy_attribute(mesh, face_attribute("uv_rot", face), 'FLOAT', 'POINT', p_face_uv_rot[f, state_indices])
        _write_numpy_attribute(mesh, face_attribute("uv_bounds", face), 'FLOAT_COLOR', 'POINT', p_face_uv_bounds[f, state_indices])

    _write_numpy_attribute(mesh, MTK_BIOME_TINT_COLOR, 'FLOAT_COLOR', 'POINT', tint_colors)
    _write_numpy_attribute(mesh, MTK_BIOME_TINT_DATA, 'FLOAT_COLOR', 'POINT', tint_datas)

    block_states = [p_full_states[idx] for idx in state_indices]
    block_keys = [f"{k[0]},{k[1]},{k[2]}" for k in keys]
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
    atlas_keys = atlas_lookup_keys(parsed)
    raw = next((lut[key] for key in atlas_keys if key in lut), None)
    if raw is not None:
        if isinstance(raw, (list, tuple)) and len(raw) >= 6:
            if not is_coord or isinstance(raw[0], (list, tuple)):
                return [type(default)(v) if isinstance(default, int) else tuple(v) for v in raw[:6]]

    # 2. Lookup via StateBaker resolved 6-face textures
    try:
        baked = _GLOBAL_STATE_BAKER.bake_block_state(parsed.full_state)
        face_vals = []
        found_any = False
        for face in baked.faces:
            tex = face.texture
            short_tex = tex.split(":", 1)[-1].removeprefix("block/")
            val = lut.get(tex) or lut.get(short_tex) or lut.get(f"minecraft:{short_tex}") or lut.get(f"minecraft:block/{short_tex}")
            if val is not None:
                found_any = True
                if isinstance(val, (list, tuple)) and len(val) == 6:
                    val = val[0]
                face_vals.append(type(default)(val) if isinstance(default, int) else tuple(val))
            else:
                face_vals.append(default)
        if found_any:
            return face_vals
    except Exception:
        pass

    # 3. Fallback to single entry by block name
    val = lut.get(parsed.name, default)
    if isinstance(val, (list, tuple)) and len(val) == 6:
        return list(val)
    return [type(default)(val) if isinstance(default, int) else tuple(val)] * 6


def _write_numpy_attribute(mesh: bpy.types.Mesh, name: str, data_type: str, domain: str, np_arr) -> None:
    """Fast write of contiguous NumPy array into Blender mesh attribute."""
    num_items = len(np_arr)
    attr = mesh.attributes.get(name)
    if not attr or attr.data_type != data_type or attr.domain != domain or len(attr.data) != num_items:
        if attr:
            mesh.attributes.remove(attr)
        attr = mesh.attributes.new(name=name, type=data_type, domain=domain)

    field = 'value' if data_type in ('FLOAT', 'INT') else ('vector' if data_type == 'FLOAT_VECTOR' else 'color')
    attr.data.foreach_set(field, np_arr.ravel())


def _write_string_attribute(mesh: bpy.types.Mesh, name: str, strings: list[str | bytes]):
    attr = mesh.attributes.get(name)
    if not attr or attr.data_type != 'STRING' or attr.domain != 'POINT' or len(attr.data) != len(strings):
        if attr:
            mesh.attributes.remove(attr)
        attr = mesh.attributes.new(name=name, type='STRING', domain='POINT')
    attr_data = attr.data
    for i, s in enumerate(strings):
        attr_data[i].value = s if isinstance(s, bytes) else s.encode('utf-8')


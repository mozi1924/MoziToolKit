"""
BMesh geometry generation, vertex transformation, loop UV assignment, and face culling for Live Sync.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple
import bmesh
from mathutils import Vector

from .constants import (
    DIR_TO_INDEX,
    MC_DIR_OFFSETS,
    MTK_BLOCK_X,
    MTK_BLOCK_Y,
    MTK_BLOCK_Z,
    MTK_FACE_DIR,
    MTK_UV_ROTATION,
    MTK_ANIM_TIMING,
    MTK_ANIM_FRAME_SIZE,
    MTK_MATERIAL_PROPS,
    MTK_UV_TILING_TRANSFORM,
    MTK_BIOME_TINT_DATA,
    MTK_BIOME_TINT_COLOR,
    MTK_COLORMAP_UV,
    MTK_ATLAS_CHUNK_ID,
    MTK_SOURCE_TEXTURE_KEY,
    UV_MAP,
)
from ..culling import (
    get_shared_face_culler,
    CUBE_FACE_MC_VERTICES,
    CUBE_FACE_CANONICAL_UVS,
    MC_DIR_OFFSETS,
    DIR_TO_INDEX,
    mc_local_to_blender,
    extract_quad_face_occlusion_rect,
)

from ..mc_baker import StateBaker
from .material_manager import LiveSyncMaterialManager, ResolvedFaceTexture
from .fluid_mesher import generate_fluid_mesh_faces
from .mesh_cache import (
    CachedStateMeta,
    get_cached_state_meta,
    _GLOBAL_STATE_META_CACHE,
)
from .material_binding import (
    get_shared_material_manager,
    _GLOBAL_MAT_MANAGER,
)
from ..materials.biome.biome import KNOWN_OVERLAY_PAIRS

OVERLAY_TO_BASE_MAP: dict[str, str] = {v: k for k, v in KNOWN_OVERLAY_PAIRS.items()}

# Backward-compatibility aliases
_mc_local_to_blender = mc_local_to_blender



def _get_or_create_bmesh_layers(bm: bmesh.types.BMesh) -> dict[str, Any]:
    """Ensure all required BMesh loop and face attribute layers exist."""
    return {
        "uv": bm.loops.layers.uv.get(UV_MAP) or bm.loops.layers.uv.new(UV_MAP),
        "color": bm.loops.layers.color.get("Color") or bm.loops.layers.color.new("Color"),
        "rot": bm.faces.layers.float.get(MTK_UV_ROTATION) or bm.faces.layers.float.new(MTK_UV_ROTATION),
        "timing": bm.faces.layers.float_color.get(MTK_ANIM_TIMING) or bm.faces.layers.float_color.new(MTK_ANIM_TIMING),
        "frame_size": bm.faces.layers.float_color.get(MTK_ANIM_FRAME_SIZE) or bm.faces.layers.float_color.new(MTK_ANIM_FRAME_SIZE),
        "material_props": bm.faces.layers.float_color.get(MTK_MATERIAL_PROPS) or bm.faces.layers.float_color.new(MTK_MATERIAL_PROPS),
        "tiling": bm.faces.layers.float_color.get(MTK_UV_TILING_TRANSFORM) or bm.faces.layers.float_color.new(MTK_UV_TILING_TRANSFORM),
        "tint_data": bm.faces.layers.float_color.get(MTK_BIOME_TINT_DATA) or bm.faces.layers.float_color.new(MTK_BIOME_TINT_DATA),
        "tint_color": bm.faces.layers.float_color.get(MTK_BIOME_TINT_COLOR) or bm.faces.layers.float_color.new(MTK_BIOME_TINT_COLOR),
        "colormap_uv": bm.faces.layers.float_vector.get(MTK_COLORMAP_UV) or bm.faces.layers.float_vector.new(MTK_COLORMAP_UV),
        "block_x": bm.faces.layers.int.get(MTK_BLOCK_X) or bm.faces.layers.int.new(MTK_BLOCK_X),
        "block_y": bm.faces.layers.int.get(MTK_BLOCK_Y) or bm.faces.layers.int.new(MTK_BLOCK_Y),
        "block_z": bm.faces.layers.int.get(MTK_BLOCK_Z) or bm.faces.layers.int.new(MTK_BLOCK_Z),
        "face_dir": bm.faces.layers.int.get(MTK_FACE_DIR) or bm.faces.layers.int.new(MTK_FACE_DIR),
        "atlas_chunk": bm.faces.layers.int.get(MTK_ATLAS_CHUNK_ID) or bm.faces.layers.int.new(MTK_ATLAS_CHUNK_ID),
        "source_key": bm.faces.layers.string.get(MTK_SOURCE_TEXTURE_KEY) or bm.faces.layers.string.new(MTK_SOURCE_TEXTURE_KEY),
    }


def _emit_bmesh_face(
    bm: bmesh.types.BMesh,
    verts_coords: Sequence[tuple[float, float, float]],
    f_res: ResolvedFaceTexture,
    layers: dict[str, Any],
    block_pos: tuple[int, int, int],
    face_dir_idx: int,
    loop_uvs_mc: Sequence[tuple[float, float]],
    uv_rot: float = 0.0,
    use_tint: bool = False,
    model_uv_scale: tuple[float, float] = (1.0, 1.0),
    mat_manager: Optional[LiveSyncMaterialManager] = None,
    voxel_storage: Optional[Any] = None,
) -> bool:
    """Helper to emit a single polygon face into BMesh with all shader attributes and UVs."""
    face_bm_verts = [bm.verts.new(v) for v in verts_coords]
    try:
        bm_face = bm.faces.new(face_bm_verts)
    except ValueError:
        return False

    bm_face.material_index = mat_manager.get_slot_for_chunk(f_res.chunk_id) if mat_manager else f_res.slot_index
    bm_face[layers["atlas_chunk"]] = f_res.chunk_id
    bm_face[layers["rot"]] = uv_rot
    bm_face[layers["timing"]] = f_res.anim_timing
    bm_face[layers["frame_size"]] = f_res.anim_frame_size
    bm_face[layers["material_props"]] = f_res.material_props
    bm_face[layers["tiling"]] = f_res.uv_tiling_transform
    bm_face[layers["tint_data"]] = f_res.biome_tint_data

    # Biome Colormap UV & Tint Color Calculation
    if voxel_storage is not None and hasattr(voxel_storage, "get_smoothed_biome_data"):
        u_blend, v_blend, water_linear = voxel_storage.get_smoothed_biome_data(block_pos[0], block_pos[1], block_pos[2], radius=2)
        bm_face[layers["colormap_uv"]] = (u_blend, v_blend, 0.0)
        if abs(f_res.biome_tint_data[3] - 3.0) < 0.1:  # Water tint
            tint_color_val = water_linear
        else:
            tint_color_val = f_res.biome_tint_color
    else:
        bm_face[layers["colormap_uv"]] = (0.2, 0.32, 0.0)
        tint_color_val = f_res.biome_tint_color

    bm_face[layers["tint_color"]] = tint_color_val
    bm_face[layers["block_x"]] = block_pos[0]
    bm_face[layers["block_y"]] = block_pos[1]
    bm_face[layers["block_z"]] = block_pos[2]
    bm_face[layers["face_dir"]] = face_dir_idx
    if layers.get("source_key") and f_res.source_texture_key:
        bm_face[layers["source_key"]] = f_res.source_texture_key.encode("utf-8")

    uv_layer = layers["uv"]
    color_layer = layers["color"]
    sx, sy = model_uv_scale

    for loop_idx, loop in enumerate(bm_face.loops):
        if loop_idx < len(loop_uvs_mc):
            u_mc, v_mc = loop_uvs_mc[loop_idx]
        else:
            u_mc, v_mc = (0.0, 0.0)
        u_scaled = float(u_mc) * sx
        v_scaled = float(v_mc) * sy
        loop[uv_layer].uv = Vector(f_res.calc_uv_fn(u_scaled, 1.0 - v_scaled))
        loop[color_layer] = tint_color_val if use_tint else (1.0, 1.0, 1.0, 1.0)

    return True


def generate_single_block_faces(
    bm: bmesh.types.BMesh,
    x: int, y: int, z: int,
    state_str: str,
    block_map: dict[tuple[int, int, int], str],
    state_cache: dict[str, CachedStateMeta],
    layers: dict[str, Any],
    origin_centered: bool,
    min_x: int, min_y: int, min_z: int,
    half_x: float, half_z: float,
    mat_manager: Optional[LiveSyncMaterialManager] = None,
    baker: Optional[StateBaker] = None,
    voxel_storage: Optional[Any] = None,
) -> tuple[int, int, int]:
    """
    Generates faces for a single block at (x, y, z) into BMesh with full 6-face neighbor culling.
    Returns (is_cube, is_prop, is_fluid).
    """
    meta = state_cache.get(state_str)
    if not meta and state_str:
        if state_str in _GLOBAL_STATE_META_CACHE:
            meta = _GLOBAL_STATE_META_CACHE[state_str]
        elif mat_manager is not None and baker is not None:
            meta = get_cached_state_meta(state_str, mat_manager, baker)
        if meta:
            state_cache[state_str] = meta

    if not meta or meta.is_air:
        return (0, 0, 0)

    if origin_centered:
        bx = (x - min_x) - half_x
        by = -((z - min_z) - half_z)
        bz = (y - min_y) + 0.5
    else:
        bx = float(x)
        by = -float(z)
        bz = float(y)

    def _get_neighbor_meta(pos: tuple[int, int, int]) -> Optional[CachedStateMeta]:
        n_state = block_map.get(pos)
        if not n_state:
            return None
        nm = state_cache.get(n_state)
        if not nm:
            if n_state in _GLOBAL_STATE_META_CACHE:
                nm = _GLOBAL_STATE_META_CACHE[n_state]
            elif mat_manager is not None and baker is not None:
                nm = get_cached_state_meta(n_state, mat_manager, baker)
            if nm:
                state_cache[n_state] = nm
        return nm

    is_cube_cnt = 0
    is_prop_cnt = 0
    is_fluid_cnt = 0

    face_culler = get_shared_face_culler()

    if meta.is_fluid:
        eff_mat_mgr = mat_manager or _GLOBAL_MAT_MANAGER or get_shared_material_manager(world_obj=None, atlas_params=None)
        fluid_faces = generate_fluid_mesh_faces(
            bm=bm,
            x=x, y=y, z=z,
            state_str=state_str,
            block_map=block_map,
            layers=layers,
            origin_centered=origin_centered,
            min_x=min_x, min_y=min_y, min_z=min_z,
            half_x=half_x, half_z=half_z,
            mat_manager=eff_mat_mgr,
            voxel_storage=voxel_storage,
        )
        is_fluid_cnt = 1 if fluid_faces > 0 else 0

    elif meta.baked_model and meta.baked_model.elements:
        if meta.is_cube:
            is_cube_cnt = 1
        else:
            is_prop_cnt = 1

        rendered_cube_faces: set[str] = set()
        for elem in meta.baked_model.elements:
            for f_dir, bf in elem.faces.items():
                if not bf.vertices or len(bf.vertices) < 3:
                    continue

                # If this block is a standard cube and this face direction was already rendered
                # by a base element (e.g. grass_block Element 0 provides grass_block_side with
                # integrated atlas overlay composite), skip the duplicate overlay quad.
                clean_tex = (bf.texture or "").split(":", 1)[-1].removeprefix("block/")
                if meta.is_cube and f_dir in rendered_cube_faces and clean_tex in OVERLAY_TO_BASE_MAP:
                    continue

                cull_dir = bf.cullface or (f_dir if meta.is_cube else None)
                if cull_dir and cull_dir in MC_DIR_OFFSETS:
                    dx, dy, dz = MC_DIR_OFFSETS[cull_dir]
                    n_pos = (x + dx, y + dy, z + dz)
                    n_meta = _get_neighbor_meta(n_pos)
                    quad_rect = extract_quad_face_occlusion_rect(bf.vertices, cull_dir) if not meta.is_cube else None
                    quad_shape = (quad_rect,) if quad_rect else None
                    if not face_culler.should_render_face(
                        state_meta=meta.cull_meta,
                        neighbor_meta=n_meta.cull_meta if n_meta else None,
                        direction=cull_dir,
                        quad_face_shape=quad_shape,
                        block_pos=(x, y, z),
                        neighbor_pos=n_pos,
                    ):
                        continue


                f_res = meta.get_face_res(bf, f_dir)
                bl_coords = [_mc_local_to_blender(lx, ly, lz) for lx, ly, lz in bf.vertices]
                world_coords = [(bx + vx, by + vy, bz + vz) for vx, vy, vz in bl_coords]

                if _emit_bmesh_face(
                    bm=bm,
                    verts_coords=world_coords,
                    f_res=f_res,
                    layers=layers,
                    block_pos=(x, y, z),
                    face_dir_idx=DIR_TO_INDEX.get(f_dir, -1),
                    loop_uvs_mc=bf.uvs,
                    uv_rot=0.0,
                    use_tint=(bf.tint_index >= 0 or f_res.use_tint),
                    model_uv_scale=f_res.model_uv_scale,
                    mat_manager=mat_manager,
                    voxel_storage=voxel_storage,
                ):
                    if meta.is_cube:
                        rendered_cube_faces.add(f_dir)

    else:
        is_cube_cnt = 1
        for f_name in ("east", "west", "up", "down", "south", "north"):
            dx, dy, dz = MC_DIR_OFFSETS[f_name]
            neighbor_pos = (x + dx, y + dy, z + dz)
            n_meta = _get_neighbor_meta(neighbor_pos)
            if not face_culler.should_render_face(
                state_meta=meta.cull_meta,
                neighbor_meta=n_meta.cull_meta if n_meta else None,
                direction=f_name,
                block_pos=(x, y, z),
                neighbor_pos=neighbor_pos,
            ):
                continue

            f_res = meta.faces_info.get(f_name, meta.faces_info.get("east"))
            mc_verts = CUBE_FACE_MC_VERTICES[f_name]
            canonical_uvs = CUBE_FACE_CANONICAL_UVS[f_name]
            bl_coords = [_mc_local_to_blender(lx, ly, lz) for lx, ly, lz in mc_verts]
            world_coords = [(bx + vx, by + vy, bz + vz) for vx, vy, vz in bl_coords]

            _emit_bmesh_face(
                bm=bm,
                verts_coords=world_coords,
                f_res=f_res,
                layers=layers,
                block_pos=(x, y, z),
                face_dir_idx=DIR_TO_INDEX.get(f_name, -1),
                loop_uvs_mc=canonical_uvs,
                uv_rot=0.0,
                use_tint=f_res.use_tint,
                mat_manager=mat_manager,
                voxel_storage=voxel_storage,
            )

    # If block is waterlogged:
    if meta.parsed.is_waterlogged and not meta.is_fluid:
        eff_mat_mgr = mat_manager or _GLOBAL_MAT_MANAGER or get_shared_material_manager(world_obj=None, atlas_params=None)
        fluid_faces = generate_fluid_mesh_faces(
            bm=bm,
            x=x, y=y, z=z,
            state_str="minecraft:water[level=0]",
            block_map=block_map,
            layers=layers,
            origin_centered=origin_centered,
            min_x=min_x, min_y=min_y, min_z=min_z,
            half_x=half_x, half_z=half_z,
            mat_manager=eff_mat_mgr,
            voxel_storage=voxel_storage,
        )
        if fluid_faces > 0:
            is_fluid_cnt = 1

    return (is_cube_cnt, is_prop_cnt, is_fluid_cnt)


def generate_voxel_geometry(
    bm: bmesh.types.BMesh,
    voxel_items: list[tuple[tuple[int, int, int], str]],
    block_map: dict[tuple[int, int, int], str],
    state_cache: dict[str, CachedStateMeta],
    uv_layer: Any = None,
    color_layer: Any = None,
    origin_centered: bool = True,
    min_x: int = 0, min_y: int = 0, min_z: int = 0,
    half_x: float = 0.0, half_z: float = 0.0,
    mat_manager: Optional[LiveSyncMaterialManager] = None,
    baker: Optional[StateBaker] = None,
    voxel_storage: Optional[Any] = None,
) -> tuple[int, int, int]:
    """
    Constructs BMesh geometry for a collection of voxels with 6-face culling,
    exact MC Baker BakedFace vertex transformations, and native Atlas UV loop projection.
    Dynamically writes named face attributes for shaders and block convention.
    Returns (cubes_count, props_count, fluids_count).
    """
    layers = _get_or_create_bmesh_layers(bm)
    cubes_count = 0
    props_count = 0
    fluids_count = 0

    for (x, y, z), state_str in voxel_items:
        c, p, f = generate_single_block_faces(
            bm=bm,
            x=x, y=y, z=z,
            state_str=state_str,
            block_map=block_map,
            state_cache=state_cache,
            layers=layers,
            origin_centered=origin_centered,
            min_x=min_x, min_y=min_y, min_z=min_z,
            half_x=half_x, half_z=half_z,
            mat_manager=mat_manager,
            baker=baker,
            voxel_storage=voxel_storage,
        )
        cubes_count += c
        props_count += p
        fluids_count += f

    return cubes_count, props_count, fluids_count

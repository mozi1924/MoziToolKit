"""
Fluid Mesher for MoziToolKit Live Sync.
Constructs physically accurate Minecraft fluid surfaces (Water & Lava) directly in Blender BMesh.

Features:
- Sub-millisecond 4-corner fluid height calculation with neighbor sampling.
- JMC2OBJ-style solid block boundary handling (solid walls do not drag down water level).
- Accurate fluid flow vector calculation and top-face UV rotation for flowing fluids.
- Mineways-standard non-collapsed, linearly mapped UVs on slanted fluid side faces.
- 6-direction culling (against fluid above, solid below, and equal/higher fluid neighbors).
- Full compatibility with Atlas Animation Chunks, Biome Tinting, and Material Slots.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple
import bpy
import bmesh
from mathutils import Vector

from ..classifier import (
    parse_and_classify,
    BlockTypeEnum,
    ParsedBlock,
    FLUID_BLOCKS,
    AIR_BLOCKS,
    TRANSPARENT_BLOCKS,
)
from ..constants import (
    DIR_TO_INDEX,
    UV_MAP,
    MTK_UV_ROTATION,
    MTK_ANIM_TIMING,
    MTK_ANIM_FRAME_SIZE,
    MTK_UV_TILING_TRANSFORM,
    MTK_BIOME_TINT_DATA,
    MTK_BIOME_TINT_COLOR,
    MTK_ATLAS_CHUNK_ID,
    MTK_BLOCK_X,
    MTK_BLOCK_Y,
    MTK_BLOCK_Z,
    MTK_FACE_DIR,
    MTK_SOURCE_TEXTURE_KEY,
)
from ..material.manager import LiveSyncMaterialManager, ResolvedFaceTexture
from ...culling import get_shared_face_culler
from ...mesh.fluid_uv import get_fluid_top_uvs, get_fluid_side_uvs



# Maximum height of a Minecraft source water/lava block (8/9)
MAX_FLUID_HEIGHT: float = 8.0 / 9.0  # ~0.8888889
FLUID_EPSILON: float = 0.0  # Kept 0.0 to ensure adjacent vertical fluid columns weld perfectly without gaps


def get_fluid_base_height(state_str: str) -> float:
    """
    Compute own fluid height in [0..1] for a single fluid or waterlogged blockstate.
    Level 0 / Waterlogged = Source block (8/9).
    Level 1..7 = Flowing levels (7/9 .. 1/9).
    Level 8..15 = Falling fluid (8/9).
    """
    if not state_str:
        return 0.0
    parsed = parse_and_classify(state_str)
    if parsed.is_waterlogged:
        return MAX_FLUID_HEIGHT
    if parsed.block_type != BlockTypeEnum.FLUID and parsed.name not in FLUID_BLOCKS:
        return 0.0

    raw_level = parsed.props.get("level", "0")
    try:
        level_int = int(raw_level)
    except (ValueError, TypeError):
        level_int = 0

    if level_int >= 8:
        return MAX_FLUID_HEIGHT
    elif level_int > 0:
        return (8.0 - level_int) / 9.0
    else:
        return MAX_FLUID_HEIGHT


def is_fluid_block(state_str: Optional[str]) -> bool:
    """Check if a blockstate is water, lava, or waterlogged."""
    if not state_str:
        return False
    parsed = parse_and_classify(state_str)
    return parsed.block_type == BlockTypeEnum.FLUID or parsed.name in FLUID_BLOCKS or parsed.is_waterlogged


def sample_fluid_height(

    block_map: dict[tuple[int, int, int], str],
    x: int, y: int, z: int,
    fluid_type: str,
) -> float:
    """
    Sample fluid height at (x, y, z):
    - Returns 1.0 if (x, y, z) has the same fluid/waterlogged and the block directly above (x, y+1, z) is also water/submerged.
    - Returns own_height in (0..1) if (x, y, z) is the same fluid or waterlogged block.
    - Returns -1.0 if (x, y, z) is a solid opaque block (indicates solid boundary, excluded from corner averaging).
    - Returns 0.0 if (x, y, z) is air or non-solid / non-fluid block.
    """
    state_str = block_map.get((x, y, z))
    if not state_str:
        return 0.0

    parsed = parse_and_classify(state_str)
    name_clean = parsed.name.replace("flowing_", "")
    is_fluid_match = (name_clean == fluid_type) or (fluid_type == "water" and parsed.is_waterlogged)

    if is_fluid_match:
        # Check if block directly above is also the same fluid / waterlogged
        above_state = block_map.get((x, y + 1, z))
        if above_state:
            p_above = parse_and_classify(above_state)
            if (p_above.name.replace("flowing_", "") == fluid_type) or (fluid_type == "water" and p_above.is_waterlogged):
                return 1.0
        if parsed.is_waterlogged and fluid_type == "water":
            return MAX_FLUID_HEIGHT
        return get_fluid_base_height(state_str)

    # If it's a solid opaque block that is not waterlogged, return -1.0
    if parsed.is_opaque and parsed.block_type not in (BlockTypeEnum.AIR, BlockTypeEnum.FLUID):
        return -1.0

    return 0.0


def calculate_corner_average(
    h_center: float,
    h_adj1: float,
    h_adj2: float,
    h_diag: float,
    is_source: bool = False,
) -> float:
    """
    Calculates the averaged fluid height for one corner between center, two adjacent neighbors,
    and the diagonal neighbor using canonical Minecraft fluid mechanics.

    - Submerged corners (fluid above, h >= 1.0) stay at 1.0.
    - Solid blocks (h == -1.0) are completely excluded (JMC2OBJ solid boundary preservation).
    - Still source blocks (is_source == True): surface tension keeps flat MAX_FLUID_HEIGHT (8/9)
      against air and chunk/selection boundaries, preventing boundary drooping.
    - Flowing fluids (is_source == False): open air (h == 0.0) contributes with weight 1.0,
      pulling downstream corners down to naturally generate trapezoidal side faces and sloped surfaces.
    """
    # If any fluid has height 1.0 (submerged/water above), the corner is fully at height 1.0
    if h_center >= 1.0 or h_adj1 >= 1.0 or h_adj2 >= 1.0:
        return 1.0

    # Still water source block protection (prevents selection boundary drooping):
    # A still source block maintains flat MAX_FLUID_HEIGHT unless it borders
    # lower flowing fluid actively drawing the water level down.
    if is_source:
        fluid_samples = [h for h in (h_adj1, h_adj2, h_diag) if h > 0.0]
        if not fluid_samples or all(h >= 0.8 for h in fluid_samples):
            return MAX_FLUID_HEIGHT

    # Flowing fluid (level 1..7, falling spills, or source bordering lower fluid):
    # Canonical Minecraft weighted averaging:
    # Source blocks (>= 0.8) have weight 10.0; flowing fluids and air (0.0 <= h < 0.8) have weight 1.0.
    # Solid blocks (-1.0) are skipped.
    weighted_sum = 0.0
    total_weight = 0.0

    # 1. Center fluid
    if h_center >= 0.8:
        weighted_sum += h_center * 10.0
        total_weight += 10.0
    elif h_center >= 0.0:
        weighted_sum += h_center * 1.0
        total_weight += 1.0

    # 2. Adjacent 1
    if h_adj1 >= 0.8:
        weighted_sum += h_adj1 * 10.0
        total_weight += 10.0
    elif h_adj1 >= 0.0:
        weighted_sum += h_adj1 * 1.0
        total_weight += 1.0

    # 3. Adjacent 2
    if h_adj2 >= 0.8:
        weighted_sum += h_adj2 * 10.0
        total_weight += 10.0
    elif h_adj2 >= 0.0:
        weighted_sum += h_adj2 * 1.0
        total_weight += 1.0

    # 4. Diagonal (only if at least one adjacent neighbor is fluid)
    if (h_adj1 > 0.0 or h_adj2 > 0.0) and h_diag >= 0.0:
        if h_diag >= 1.0:
            return 1.0
        if h_diag >= 0.8:
            weighted_sum += h_diag * 10.0
            total_weight += 10.0
        else:
            weighted_sum += h_diag * 1.0
            total_weight += 1.0

    if total_weight > 0.0:
        return weighted_sum / total_weight
    return max(0.0, h_center)


def calculate_fluid_corner_heights(
    block_map: dict[tuple[int, int, int], str],
    x: int, y: int, z: int,
    fluid_type: str,
) -> tuple[float, float, float, float]:
    """
    Compute 4 corner heights (c_NW, c_NE, c_SE, c_SW) in [0..1] for the fluid block at (x, y, z).
    North is -Z, South is +Z, West is -X, East is +X.
    NW: (X=0, Z=0)
    NE: (X=1, Z=0)
    SE: (X=1, Z=1)
    SW: (X=0, Z=1)
    """
    # Check if this fluid block itself has fluid above it
    above_state = block_map.get((x, y + 1, z))
    if above_state:
        p_above = parse_and_classify(above_state)
        if p_above.name.replace("flowing_", "") == fluid_type or (fluid_type == "water" and p_above.is_waterlogged):
            return (1.0, 1.0, 1.0, 1.0)

    state_str = block_map.get((x, y, z))
    is_source = False
    if state_str:
        parsed = parse_and_classify(state_str)
        if parsed.is_waterlogged:
            is_source = True
        elif "flowing_" not in parsed.name:
            level_str = parsed.props.get("level", "0")
            is_source = (level_str == "0")

    h_center = sample_fluid_height(block_map, x, y, z, fluid_type)
    h_N = sample_fluid_height(block_map, x, y, z - 1, fluid_type)
    h_S = sample_fluid_height(block_map, x, y, z + 1, fluid_type)
    h_E = sample_fluid_height(block_map, x + 1, y, z, fluid_type)
    h_W = sample_fluid_height(block_map, x - 1, y, z, fluid_type)

    h_NE = sample_fluid_height(block_map, x + 1, y, z - 1, fluid_type)
    h_NW = sample_fluid_height(block_map, x - 1, y, z - 1, fluid_type)
    h_SE = sample_fluid_height(block_map, x + 1, y, z + 1, fluid_type)
    h_SW = sample_fluid_height(block_map, x - 1, y, z + 1, fluid_type)

    c_NW = calculate_corner_average(h_center, h_N, h_W, h_NW, is_source=is_source)
    c_NE = calculate_corner_average(h_center, h_N, h_E, h_NE, is_source=is_source)
    c_SE = calculate_corner_average(h_center, h_S, h_E, h_SE, is_source=is_source)
    c_SW = calculate_corner_average(h_center, h_S, h_W, h_SW, is_source=is_source)

    return (c_NW, c_NE, c_SE, c_SW)


def calculate_fluid_flow_vector(
    block_map: dict[tuple[int, int, int], str],
    x: int, y: int, z: int,
    fluid_type: str,
    own_height: float,
) -> tuple[float, float, float]:
    """
    Calculate horizontal flow direction vector (vx, vz) and UV rotation angle in radians.
    Returns (vx, vz, flow_angle).
    """
    vx = 0.0
    vz = 0.0

    # 4 horizontal directions: North(0, -1), South(0, 1), West(-1, 0), East(1, 0)
    for dx, dz in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        nx, ny, nz = x + dx, y, z + dz
        n_state = block_map.get((nx, ny, nz))
        if not n_state:
            # Air / empty neighbor: check block below
            below_state = block_map.get((nx, ny - 1, nz))
            if below_state:
                p_below = parse_and_classify(below_state)
                is_below_fluid = (p_below.name.replace("flowing_", "") == fluid_type) or (fluid_type == "water" and p_below.is_waterlogged)
                if is_below_fluid:
                    b_h = get_fluid_base_height(below_state)
                    diff = own_height - (b_h - MAX_FLUID_HEIGHT)
                    vx += dx * diff
                    vz += dz * diff
        else:
            p_n = parse_and_classify(n_state)
            is_n_fluid = (p_n.name.replace("flowing_", "") == fluid_type) or (fluid_type == "water" and p_n.is_waterlogged)
            if is_n_fluid:
                n_h = get_fluid_base_height(n_state)
                diff = own_height - n_h
                if diff != 0.0:
                    vx += dx * diff
                    vz += dz * diff
            elif not p_n.is_opaque:
                # Non-opaque non-fluid neighbor: check block below
                below_state = block_map.get((nx, ny - 1, nz))
                if below_state:
                    p_below = parse_and_classify(below_state)
                    is_below_fluid = (p_below.name.replace("flowing_", "") == fluid_type) or (fluid_type == "water" and p_below.is_waterlogged)
                    if is_below_fluid:
                        b_h = get_fluid_base_height(below_state)
                        diff = own_height - (b_h - MAX_FLUID_HEIGHT)
                        vx += dx * diff
                        vz += dz * diff

    flow_len = math.sqrt(vx * vx + vz * vz)
    if flow_len < 1e-4:
        return (0.0, 0.0, 0.0)

    # Angle in radians (Minecraft convention: atan2(vz, vx) - pi/2)
    flow_angle = math.atan2(vz, vx) - (math.pi / 2.0)
    return (vx, vz, flow_angle)


def _emit_fluid_face(
    bm: bmesh.types.BMesh,
    verts_coords: Sequence[tuple[float, float, float]],
    loop_uvs_mc: Sequence[tuple[float, float]],
    f_res: ResolvedFaceTexture,
    layers: dict[str, Any],
    block_pos: tuple[int, int, int],
    face_dir_idx: int,
    uv_rot: float = 0.0,
    use_tint: bool = True,
    mat_manager: Optional[LiveSyncMaterialManager] = None,
    voxel_storage: Optional[Any] = None,
) -> bool:
    """Helper to emit a single fluid polygon into BMesh."""
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
    if "material_props" in layers:
        bm_face[layers["material_props"]] = f_res.material_props
    bm_face[layers["tiling"]] = f_res.uv_tiling_transform
    bm_face[layers["tint_data"]] = f_res.biome_tint_data

    # Biome Colormap UV & Tint Color Calculation
    if voxel_storage is not None and hasattr(voxel_storage, "get_smoothed_biome_data"):
        u_blend, v_blend, water_linear = voxel_storage.get_smoothed_biome_data(block_pos[0], block_pos[1], block_pos[2], radius=2)
        if "colormap_uv" in layers:
            bm_face[layers["colormap_uv"]] = (u_blend, v_blend, 0.0)
        if abs(f_res.biome_tint_data[3] - 3.0) < 0.1:  # Water tint
            tint_col_val = water_linear
        else:
            tint_col_val = f_res.biome_tint_color
    else:
        if "colormap_uv" in layers:
            bm_face[layers["colormap_uv"]] = (0.2, 0.32, 0.0)
        tint_col_val = f_res.biome_tint_color

    bm_face[layers["tint_color"]] = tint_col_val
    bm_face[layers["block_x"]] = block_pos[0]
    bm_face[layers["block_y"]] = block_pos[1]
    bm_face[layers["block_z"]] = block_pos[2]
    bm_face[layers["face_dir"]] = face_dir_idx
    if layers.get("source_key") and f_res.source_texture_key:
        bm_face[layers["source_key"]] = f_res.source_texture_key.encode("utf-8")

    uv_layer = layers["uv"]
    color_layer = layers["color"]

    for loop_idx, loop in enumerate(bm_face.loops):
        if loop_idx < len(loop_uvs_mc):
            u_mc, v_mc = loop_uvs_mc[loop_idx]
        else:
            u_mc, v_mc = (0.0, 0.0)
        # Blender V coordinate is 1.0 - v_mc
        loop[uv_layer].uv = Vector(f_res.calc_uv_fn(u_mc, 1.0 - v_mc))
        loop[color_layer] = tint_col_val if use_tint else (1.0, 1.0, 1.0, 1.0)

    return True


def is_fluid_flowing(
    state_str: str,
    block_map: dict[tuple[int, int, int], str],
    x: int, y: int, z: int,
    fluid_type: str,
    flow_vx: float,
    flow_vz: float,
) -> bool:
    """
    Determine if fluid at (x, y, z) is actively flowing and should use the flowing texture/animation.
    Returns True for flowing streams, waterfalls, and falling fluid columns.
    """
    parsed = parse_and_classify(state_str)
    # 1. State name check (e.g. minecraft:flowing_water, minecraft:flowing_lava)
    if "flowing_" in parsed.name:
        return True

    # 2. Level property check: level=0 is still source.
    # level=1..7 is flowing fluid.
    # level=8..15 is falling fluid (bit 0x8 set, e.g. waterfalls).
    level_str = parsed.props.get("level", "0")
    try:
        level_int = int(level_str)
    except ValueError:
        level_int = 0

    if level_int > 0 and not parsed.is_waterlogged:
        return True

    # 3. Dynamic flow vector velocity check
    if abs(flow_vx) > 1e-4 or abs(flow_vz) > 1e-4:
        return True

    # 4. Vertical falling column check
    # Fluid directly above dropping down into this block (waterfall column)
    above_state = block_map.get((x, y + 1, z))
    if above_state:
        p_above = parse_and_classify(above_state)
        if p_above.name.replace("flowing_", "") == fluid_type or (fluid_type == "water" and p_above.is_waterlogged):
            a_level = int(p_above.props.get("level", "0")) if p_above.props.get("level", "0").isdigit() else 0
            if a_level > 0 or "flowing_" in p_above.name:
                return True

    # Fluid directly below drawing downward flow
    below_state = block_map.get((x, y - 1, z))
    if below_state:
        p_below = parse_and_classify(below_state)
        if fluid_type == "water" and p_below.is_waterlogged:
            pass
        elif below_state != state_str:
            if p_below.name.replace("flowing_", "") == fluid_type:
                b_level = int(p_below.props.get("level", "0")) if p_below.props.get("level", "0").isdigit() else 0
                if b_level > 0:
                    return True

    return False


def should_cull_fluid_face(
    neighbor_state: Optional[str],
    fluid_type: str,
    direction: str = "up",
    own_state: Optional[str] = None,
) -> bool:
    """
    Authoritative face culling for fluid faces against adjacent blocks.
    Delegates to FaceCuller engine for canonical Minecraft 1.21+ fluid occlusion.
    """
    if not neighbor_state:
        return False

    culler = get_shared_face_culler()
    state_str = own_state or f"minecraft:{fluid_type}"
    meta_a = culler.get_meta(state_str)
    meta_b = culler.get_meta(neighbor_state)

    return not culler.should_render_face(
        state_meta=meta_a,
        neighbor_meta=meta_b,
        direction=direction,
    )



# Global cache for static fluid face resources to eliminate thousands of repeated dynamic lookups
_FLUID_RESOURCE_CACHE: dict[tuple[int, str, float], ResolvedFaceTexture] = {}


def get_cached_fluid_face_resource(
    mat_manager: LiveSyncMaterialManager,
    parsed: ParsedBlock,
    target_tex: str,
    face_name: str,
    face_idx: int,
    rot: float = 0.0,
) -> ResolvedFaceTexture:
    """Retrieve pre-resolved fluid face texture metadata with memoization."""
    key = (id(mat_manager), target_tex, round(rot, 4))
    res = _FLUID_RESOURCE_CACHE.get(key)
    if res is None:
        res = mat_manager.resolve_block_face(
            parsed=parsed,
            face_name=face_name,
            face_index=face_idx,
            json_face_info={"tex": target_tex, "rot": rot},
        )
        _FLUID_RESOURCE_CACHE[key] = res
    return res


def _emit_fluid_buffer_face(
    buffer: Any,
    verts_coords: Sequence[tuple[float, float, float]],
    loop_uvs_mc: Sequence[tuple[float, float]],
    f_res: ResolvedFaceTexture,
    block_pos: tuple[int, int, int],
    face_dir_idx: int,
    uv_rot: float = 0.0,
    use_tint: bool = True,
    mat_manager: Optional[LiveSyncMaterialManager] = None,
    voxel_storage: Optional[Any] = None,
) -> None:
    """Helper to emit a single fluid polygon into RawSectionGeometryBuffer."""
    mat_slot = mat_manager.get_slot_for_chunk(f_res.chunk_id) if mat_manager else f_res.slot_index

    # Biome Colormap UV & Tint Color Calculation
    if voxel_storage is not None and hasattr(voxel_storage, "get_smoothed_biome_data"):
        u_blend, v_blend, water_linear = voxel_storage.get_smoothed_biome_data(block_pos[0], block_pos[1], block_pos[2], radius=2)
        colormap_uv = (u_blend, v_blend, 0.0)
        if abs(f_res.biome_tint_data[3] - 3.0) < 0.1:  # Water tint
            tint_col_val = water_linear
        else:
            tint_col_val = f_res.biome_tint_color
    else:
        colormap_uv = (0.2, 0.32, 0.0)
        tint_col_val = f_res.biome_tint_color

    calc_uv = f_res.calc_uv_fn
    transformed_uvs = [calc_uv(u_mc, 1.0 - v_mc) for u_mc, v_mc in loop_uvs_mc]
    tint_color = tint_col_val if use_tint else (1.0, 1.0, 1.0, 1.0)
    loop_colors = [tint_color] * len(verts_coords)

    buffer.add_face(
        verts_coords=verts_coords,
        loop_uvs=transformed_uvs,
        loop_colors=loop_colors,
        material_index=mat_slot,
        block_pos=block_pos,
        face_dir_idx=face_dir_idx,
        atlas_chunk=f_res.chunk_id,
        uv_rot=uv_rot,
        timing=f_res.anim_timing,
        frame_size=f_res.anim_frame_size,
        material_props=f_res.material_props,
        tiling=f_res.uv_tiling_transform,
        tint_data=f_res.biome_tint_data,
        tint_color=tint_col_val,
        colormap_uv=colormap_uv,
        source_key=f_res.source_texture_key or "",
    )


def generate_fluid_mesh_faces(
    bm: bmesh.types.BMesh,
    x: int, y: int, z: int,
    state_str: str,
    block_map: dict[tuple[int, int, int], str],
    layers: dict[str, Any],
    origin_centered: bool,
    min_x: int, min_y: int, min_z: int,
    half_x: float, half_z: float,
    mat_manager: LiveSyncMaterialManager,
    voxel_storage: Optional[Any] = None,
) -> int:
    """
    Construct complete Minecraft fluid geometry (Top, Bottom, and 4 Slanted Sides) for (x, y, z) into BMesh.
    Applies Mineways-standard non-collapsed UVs on slanted sides and JMC2OBJ boundary preservation.
    Returns the number of faces generated.
    """
    parsed = parse_and_classify(state_str)
    fluid_type = parsed.name.replace("flowing_", "")
    if fluid_type not in ("water", "lava"):
        fluid_type = "water"

    # Fast 6-face culling pre-pass: If fully enclosed by occluding blocks, short-circuit immediately
    up_state = block_map.get((x, y + 1, z))
    down_state = block_map.get((x, y - 1, z))
    north_state = block_map.get((x, y, z - 1))
    south_state = block_map.get((x, y, z + 1))
    west_state = block_map.get((x - 1, y, z))
    east_state = block_map.get((x + 1, y, z))

    render_up = not should_cull_fluid_face(up_state, fluid_type, direction="up", own_state=state_str)
    render_down = not should_cull_fluid_face(down_state, fluid_type, direction="down", own_state=state_str)
    render_north = not should_cull_fluid_face(north_state, fluid_type, direction="north", own_state=state_str)
    render_south = not should_cull_fluid_face(south_state, fluid_type, direction="south", own_state=state_str)
    render_west = not should_cull_fluid_face(west_state, fluid_type, direction="west", own_state=state_str)
    render_east = not should_cull_fluid_face(east_state, fluid_type, direction="east", own_state=state_str)

    if not (render_up or render_down or render_north or render_south or render_west or render_east):
        return 0

    own_height = get_fluid_base_height(state_str)
    c_NW, c_NE, c_SE, c_SW = calculate_fluid_corner_heights(block_map, x, y, z, fluid_type)

    if origin_centered:
        bx = (x - min_x) - half_x
        by = -((z - min_z) - half_z)
        bz = (y - min_y) + 0.5
    else:
        bx = float(x)
        by = -float(z)
        bz = float(y)

    # 1. Flow Direction and UV Rotation
    flow_vx, flow_vz, flow_angle = calculate_fluid_flow_vector(block_map, x, y, z, fluid_type, own_height)
    is_flowing = is_fluid_flowing(state_str, block_map, x, y, z, fluid_type, flow_vx, flow_vz)

    # Resolve Still and Flowing Face Resources with memoization
    target_tex_still = f"minecraft:block/{fluid_type}_still"
    target_tex_flow = f"minecraft:block/{fluid_type}_flow"

    res_still = get_cached_fluid_face_resource(
        mat_manager=mat_manager,
        parsed=parsed,
        target_tex=target_tex_still,
        face_name="top",
        face_idx=DIR_TO_INDEX["up"],
        rot=0.0,
    )
    side_res = get_cached_fluid_face_resource(
        mat_manager=mat_manager,
        parsed=parsed,
        target_tex=target_tex_flow,
        face_name="north",
        face_idx=DIR_TO_INDEX["north"],
        rot=0.0,
    )
    if is_flowing and abs(flow_angle) > 1e-4:
        res_flow = get_cached_fluid_face_resource(
            mat_manager=mat_manager,
            parsed=parsed,
            target_tex=target_tex_flow,
            face_name="top",
            face_idx=DIR_TO_INDEX["up"],
            rot=flow_angle,
        )
    else:
        res_flow = get_cached_fluid_face_resource(
            mat_manager=mat_manager,
            parsed=parsed,
            target_tex=target_tex_flow,
            face_name="top",
            face_idx=DIR_TO_INDEX["up"],
            rot=0.0,
        )

    top_res = res_flow if is_flowing else res_still

    faces_emitted = 0
    top_NW = c_NW
    top_NE = c_NE
    top_SE = c_SE
    top_SW = c_SW

    # 1. Top Face (UP)
    if render_up:
        v_nw = (bx - 0.5, by + 0.5, bz - 0.5 + top_NW)
        v_sw = (bx - 0.5, by - 0.5, bz - 0.5 + top_SW)
        v_se = (bx + 0.5, by - 0.5, bz - 0.5 + top_SE)
        v_ne = (bx + 0.5, by + 0.5, bz - 0.5 + top_NE)

        top_uvs_mc = get_fluid_top_uvs(is_flowing=is_flowing, rotation=flow_angle if is_flowing else 0.0)

        if _emit_fluid_face(
            bm=bm,
            verts_coords=(v_nw, v_sw, v_se, v_ne),
            loop_uvs_mc=top_uvs_mc,
            f_res=top_res,
            layers=layers,
            block_pos=(x, y, z),
            face_dir_idx=DIR_TO_INDEX["up"],
            uv_rot=0.0,
            use_tint=top_res.use_tint,
            mat_manager=mat_manager,
            voxel_storage=voxel_storage,
        ):
            faces_emitted += 1

    # 2. Bottom Face (DOWN)
    if render_down:
        v_bot_sw = (bx - 0.5, by - 0.5, bz - 0.5)
        v_bot_nw = (bx - 0.5, by + 0.5, bz - 0.5)
        v_bot_ne = (bx + 0.5, by + 0.5, bz - 0.5)
        v_bot_se = (bx + 0.5, by - 0.5, bz - 0.5)
        bot_uvs_mc = get_fluid_top_uvs(is_flowing=False, rotation=0.0)

        if _emit_fluid_face(
            bm=bm,
            verts_coords=(v_bot_sw, v_bot_nw, v_bot_ne, v_bot_se),
            loop_uvs_mc=bot_uvs_mc,
            f_res=res_still,
            layers=layers,
            block_pos=(x, y, z),
            face_dir_idx=DIR_TO_INDEX["down"],
            uv_rot=0.0,
            use_tint=res_still.use_tint,
            mat_manager=mat_manager,
            voxel_storage=voxel_storage,
        ):
            faces_emitted += 1

    # 3. Side Faces (North, South, West, East)
    if render_north:
        v_ne_top = (bx + 0.5, by + 0.5, bz - 0.5 + top_NE)
        v_ne_bot = (bx + 0.5, by + 0.5, bz - 0.5)
        v_nw_bot = (bx - 0.5, by + 0.5, bz - 0.5)
        v_nw_top = (bx - 0.5, by + 0.5, bz - 0.5 + top_NW)
        north_uvs_mc = get_fluid_side_uvs(top_NE, top_NW)
        if _emit_fluid_face(
            bm=bm,
            verts_coords=(v_ne_top, v_ne_bot, v_nw_bot, v_nw_top),
            loop_uvs_mc=north_uvs_mc,
            f_res=side_res,
            layers=layers,
            block_pos=(x, y, z),
            face_dir_idx=DIR_TO_INDEX["north"],
            uv_rot=0.0,
            use_tint=side_res.use_tint,
            mat_manager=mat_manager,
            voxel_storage=voxel_storage,
        ):
            faces_emitted += 1

    if render_south:
        v_sw_top = (bx - 0.5, by - 0.5, bz - 0.5 + top_SW)
        v_sw_bot = (bx - 0.5, by - 0.5, bz - 0.5)
        v_se_bot = (bx + 0.5, by - 0.5, bz - 0.5)
        v_se_top = (bx + 0.5, by - 0.5, bz - 0.5 + top_SE)
        south_uvs_mc = get_fluid_side_uvs(top_SW, top_SE)
        if _emit_fluid_face(
            bm=bm,
            verts_coords=(v_sw_top, v_sw_bot, v_se_bot, v_se_top),
            loop_uvs_mc=south_uvs_mc,
            f_res=side_res,
            layers=layers,
            block_pos=(x, y, z),
            face_dir_idx=DIR_TO_INDEX["south"],
            uv_rot=0.0,
            use_tint=side_res.use_tint,
            mat_manager=mat_manager,
            voxel_storage=voxel_storage,
        ):
            faces_emitted += 1

    if render_west:
        v_nw_top = (bx - 0.5, by + 0.5, bz - 0.5 + top_NW)
        v_nw_bot = (bx - 0.5, by + 0.5, bz - 0.5)
        v_sw_bot = (bx - 0.5, by - 0.5, bz - 0.5)
        v_sw_top = (bx - 0.5, by - 0.5, bz - 0.5 + top_SW)
        west_uvs_mc = get_fluid_side_uvs(top_NW, top_SW)
        if _emit_fluid_face(
            bm=bm,
            verts_coords=(v_nw_top, v_nw_bot, v_sw_bot, v_sw_top),
            loop_uvs_mc=west_uvs_mc,
            f_res=side_res,
            layers=layers,
            block_pos=(x, y, z),
            face_dir_idx=DIR_TO_INDEX["west"],
            uv_rot=0.0,
            use_tint=side_res.use_tint,
            mat_manager=mat_manager,
            voxel_storage=voxel_storage,
        ):
            faces_emitted += 1

    if render_east:
        v_se_top = (bx + 0.5, by - 0.5, bz - 0.5 + top_SE)
        v_se_bot = (bx + 0.5, by - 0.5, bz - 0.5)
        v_ne_bot = (bx + 0.5, by + 0.5, bz - 0.5)
        v_ne_top = (bx + 0.5, by + 0.5, bz - 0.5 + top_NE)
        east_uvs_mc = get_fluid_side_uvs(top_SE, top_NE)
        if _emit_fluid_face(
            bm=bm,
            verts_coords=(v_se_top, v_se_bot, v_ne_bot, v_ne_top),
            loop_uvs_mc=east_uvs_mc,
            f_res=side_res,
            layers=layers,
            block_pos=(x, y, z),
            face_dir_idx=DIR_TO_INDEX["east"],
            uv_rot=0.0,
            use_tint=side_res.use_tint,
            mat_manager=mat_manager,
            voxel_storage=voxel_storage,
        ):
            faces_emitted += 1

    return faces_emitted


def generate_fluid_buffer_faces(
    buffer: Any,
    x: int, y: int, z: int,
    state_str: str,
    block_map: dict[tuple[int, int, int], str],
    origin_centered: bool,
    min_x: int, min_y: int, min_z: int,
    half_x: float, half_z: float,
    mat_manager: LiveSyncMaterialManager,
    voxel_storage: Optional[Any] = None,
) -> int:
    """
    Construct complete Minecraft fluid geometry for (x, y, z) into RawSectionGeometryBuffer.
    100% pure Python/NumPy computation without any bpy/bmesh dependencies.
    Returns the number of faces generated.
    """
    parsed = parse_and_classify(state_str)
    fluid_type = parsed.name.replace("flowing_", "")
    if fluid_type not in ("water", "lava"):
        fluid_type = "water"

    # Fast 6-face culling pre-pass
    up_state = block_map.get((x, y + 1, z))
    down_state = block_map.get((x, y - 1, z))
    north_state = block_map.get((x, y, z - 1))
    south_state = block_map.get((x, y, z + 1))
    west_state = block_map.get((x - 1, y, z))
    east_state = block_map.get((x + 1, y, z))

    render_up = not should_cull_fluid_face(up_state, fluid_type, direction="up", own_state=state_str)
    render_down = not should_cull_fluid_face(down_state, fluid_type, direction="down", own_state=state_str)
    render_north = not should_cull_fluid_face(north_state, fluid_type, direction="north", own_state=state_str)
    render_south = not should_cull_fluid_face(south_state, fluid_type, direction="south", own_state=state_str)
    render_west = not should_cull_fluid_face(west_state, fluid_type, direction="west", own_state=state_str)
    render_east = not should_cull_fluid_face(east_state, fluid_type, direction="east", own_state=state_str)

    if not (render_up or render_down or render_north or render_south or render_west or render_east):
        return 0

    own_height = get_fluid_base_height(state_str)
    c_NW, c_NE, c_SE, c_SW = calculate_fluid_corner_heights(block_map, x, y, z, fluid_type)

    if origin_centered:
        bx = (x - min_x) - half_x
        by = -((z - min_z) - half_z)
        bz = (y - min_y) + 0.5
    else:
        bx = float(x)
        by = -float(z)
        bz = float(y)

    flow_vx, flow_vz, flow_angle = calculate_fluid_flow_vector(block_map, x, y, z, fluid_type, own_height)
    is_flowing = is_fluid_flowing(state_str, block_map, x, y, z, fluid_type, flow_vx, flow_vz)

    # Resolve Still and Flowing Face Resources with memoization
    target_tex_still = f"minecraft:block/{fluid_type}_still"
    target_tex_flow = f"minecraft:block/{fluid_type}_flow"

    res_still = get_cached_fluid_face_resource(
        mat_manager=mat_manager,
        parsed=parsed,
        target_tex=target_tex_still,
        face_name="top",
        face_idx=DIR_TO_INDEX["up"],
        rot=0.0,
    )
    side_res = get_cached_fluid_face_resource(
        mat_manager=mat_manager,
        parsed=parsed,
        target_tex=target_tex_flow,
        face_name="north",
        face_idx=DIR_TO_INDEX["north"],
        rot=0.0,
    )
    if is_flowing and abs(flow_angle) > 1e-4:
        res_flow = get_cached_fluid_face_resource(
            mat_manager=mat_manager,
            parsed=parsed,
            target_tex=target_tex_flow,
            face_name="top",
            face_idx=DIR_TO_INDEX["up"],
            rot=flow_angle,
        )
    else:
        res_flow = get_cached_fluid_face_resource(
            mat_manager=mat_manager,
            parsed=parsed,
            target_tex=target_tex_flow,
            face_name="top",
            face_idx=DIR_TO_INDEX["up"],
            rot=0.0,
        )

    top_res = res_flow if is_flowing else res_still

    faces_emitted = 0
    top_NW, top_NE, top_SE, top_SW = c_NW, c_NE, c_SE, c_SW

    # 1. Top Face
    if render_up:
        v_nw = (bx - 0.5, by + 0.5, bz - 0.5 + top_NW)
        v_sw = (bx - 0.5, by - 0.5, bz - 0.5 + top_SW)
        v_se = (bx + 0.5, by - 0.5, bz - 0.5 + top_SE)
        v_ne = (bx + 0.5, by + 0.5, bz - 0.5 + top_NE)
        top_uvs_mc = get_fluid_top_uvs(is_flowing=is_flowing, rotation=flow_angle if is_flowing else 0.0)
        _emit_fluid_buffer_face(
            buffer=buffer,
            verts_coords=(v_nw, v_sw, v_se, v_ne),
            loop_uvs_mc=top_uvs_mc,
            f_res=top_res,
            block_pos=(x, y, z),
            face_dir_idx=DIR_TO_INDEX["up"],
            uv_rot=0.0,
            use_tint=top_res.use_tint,
            mat_manager=mat_manager,
            voxel_storage=voxel_storage,
        )
        faces_emitted += 1

    # 2. Bottom Face
    if render_down:
        v_bot_sw = (bx - 0.5, by - 0.5, bz - 0.5)
        v_bot_nw = (bx - 0.5, by + 0.5, bz - 0.5)
        v_bot_ne = (bx + 0.5, by + 0.5, bz - 0.5)
        v_bot_se = (bx + 0.5, by - 0.5, bz - 0.5)
        bot_uvs_mc = get_fluid_top_uvs(is_flowing=False, rotation=0.0)
        _emit_fluid_buffer_face(
            buffer=buffer,
            verts_coords=(v_bot_sw, v_bot_nw, v_bot_ne, v_bot_se),
            loop_uvs_mc=bot_uvs_mc,
            f_res=res_still,
            block_pos=(x, y, z),
            face_dir_idx=DIR_TO_INDEX["down"],
            uv_rot=0.0,
            use_tint=res_still.use_tint,
            mat_manager=mat_manager,
            voxel_storage=voxel_storage,
        )
        faces_emitted += 1

    # 3. Side Faces
    if render_north:
        v_ne_top = (bx + 0.5, by + 0.5, bz - 0.5 + top_NE)
        v_ne_bot = (bx + 0.5, by + 0.5, bz - 0.5)
        v_nw_bot = (bx - 0.5, by + 0.5, bz - 0.5)
        v_nw_top = (bx - 0.5, by + 0.5, bz - 0.5 + top_NW)
        north_uvs_mc = get_fluid_side_uvs(top_NE, top_NW)
        _emit_fluid_buffer_face(
            buffer=buffer,
            verts_coords=(v_ne_top, v_ne_bot, v_nw_bot, v_nw_top),
            loop_uvs_mc=north_uvs_mc,
            f_res=side_res,
            block_pos=(x, y, z),
            face_dir_idx=DIR_TO_INDEX["north"],
            uv_rot=0.0,
            use_tint=side_res.use_tint,
            mat_manager=mat_manager,
            voxel_storage=voxel_storage,
        )
        faces_emitted += 1

    if render_south:
        v_sw_top = (bx - 0.5, by - 0.5, bz - 0.5 + top_SW)
        v_sw_bot = (bx - 0.5, by - 0.5, bz - 0.5)
        v_se_bot = (bx + 0.5, by - 0.5, bz - 0.5)
        v_se_top = (bx + 0.5, by - 0.5, bz - 0.5 + top_SE)
        south_uvs_mc = get_fluid_side_uvs(top_SW, top_SE)
        _emit_fluid_buffer_face(
            buffer=buffer,
            verts_coords=(v_sw_top, v_sw_bot, v_se_bot, v_se_top),
            loop_uvs_mc=south_uvs_mc,
            f_res=side_res,
            block_pos=(x, y, z),
            face_dir_idx=DIR_TO_INDEX["south"],
            uv_rot=0.0,
            use_tint=side_res.use_tint,
            mat_manager=mat_manager,
            voxel_storage=voxel_storage,
        )
        faces_emitted += 1

    if render_west:
        v_nw_top = (bx - 0.5, by + 0.5, bz - 0.5 + top_NW)
        v_nw_bot = (bx - 0.5, by + 0.5, bz - 0.5)
        v_sw_bot = (bx - 0.5, by - 0.5, bz - 0.5)
        v_sw_top = (bx - 0.5, by - 0.5, bz - 0.5 + top_SW)
        west_uvs_mc = get_fluid_side_uvs(top_NW, top_SW)
        _emit_fluid_buffer_face(
            buffer=buffer,
            verts_coords=(v_nw_top, v_nw_bot, v_sw_bot, v_sw_top),
            loop_uvs_mc=west_uvs_mc,
            f_res=side_res,
            block_pos=(x, y, z),
            face_dir_idx=DIR_TO_INDEX["west"],
            uv_rot=0.0,
            use_tint=side_res.use_tint,
            mat_manager=mat_manager,
            voxel_storage=voxel_storage,
        )
        faces_emitted += 1

    if render_east:
        v_se_top = (bx + 0.5, by - 0.5, bz - 0.5 + top_SE)
        v_se_bot = (bx + 0.5, by - 0.5, bz - 0.5)
        v_ne_bot = (bx + 0.5, by + 0.5, bz - 0.5)
        v_ne_top = (bx + 0.5, by + 0.5, bz - 0.5 + top_NE)
        east_uvs_mc = get_fluid_side_uvs(top_SE, top_NE)
        _emit_fluid_buffer_face(
            buffer=buffer,
            verts_coords=(v_se_top, v_se_bot, v_ne_bot, v_ne_top),
            loop_uvs_mc=east_uvs_mc,
            f_res=side_res,
            block_pos=(x, y, z),
            face_dir_idx=DIR_TO_INDEX["east"],
            uv_rot=0.0,
            use_tint=side_res.use_tint,
            mat_manager=mat_manager,
            voxel_storage=voxel_storage,
        )
        faces_emitted += 1

    return faces_emitted

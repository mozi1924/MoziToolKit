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

from .classifier import (
    parse_and_classify,
    BlockTypeEnum,
    ParsedBlock,
    FLUID_BLOCKS,
    AIR_BLOCKS,
    TRANSPARENT_BLOCKS,
)
from .constants import (
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
from .material_manager import LiveSyncMaterialManager, ResolvedFaceTexture

# Maximum height of a Minecraft source water/lava block (8/9)
MAX_FLUID_HEIGHT: float = 8.0 / 9.0  # ~0.8888889
FLUID_EPSILON: float = 0.001


def get_fluid_base_height(state_str: str) -> float:
    """
    Compute own fluid height in [0..1] for a single fluid blockstate.
    Level 0 = Source block (8/9).
    Level 1..7 = Flowing levels (7/9 .. 1/9).
    Level 8..15 = Falling fluid (8/9).
    """
    if not state_str:
        return 0.0
    parsed = parse_and_classify(state_str)
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
    """Check if a blockstate is water or lava."""
    if not state_str:
        return False
    parsed = parse_and_classify(state_str)
    return parsed.block_type == BlockTypeEnum.FLUID or parsed.name in FLUID_BLOCKS


def is_same_fluid(state_a: Optional[str], state_b: Optional[str]) -> bool:
    """Check if two states belong to the same fluid type (e.g. water vs water, lava vs lava)."""
    if not state_a or not state_b:
        return False
    pa = parse_and_classify(state_a)
    pb = parse_and_classify(state_b)
    name_a = pa.name.replace("flowing_", "")
    name_b = pb.name.replace("flowing_", "")
    return name_a == name_b and name_a in ("water", "lava")


def sample_fluid_height(
    block_map: dict[tuple[int, int, int], str],
    x: int, y: int, z: int,
    fluid_type: str,
) -> float:
    """
    Sample fluid height at (x, y, z):
    - Returns 1.0 if (x, y, z) has the same fluid and the block directly above (x, y+1, z) is also the same fluid.
    - Returns own_height in (0..1) if (x, y, z) is the same fluid.
    - Returns -1.0 if (x, y, z) is a solid opaque block (indicates solid boundary, excluded from corner averaging).
    - Returns 0.0 if (x, y, z) is air or non-solid / non-fluid block.
    """
    state_str = block_map.get((x, y, z))
    if not state_str:
        return 0.0

    parsed = parse_and_classify(state_str)
    name_clean = parsed.name.replace("flowing_", "")

    if name_clean == fluid_type:
        # Check if block directly above is also the same fluid (e.g. waterfall / submerged)
        above_state = block_map.get((x, y + 1, z))
        if above_state:
            p_above = parse_and_classify(above_state)
            if p_above.name.replace("flowing_", "") == fluid_type:
                return 1.0
        return get_fluid_base_height(state_str)

    # If it's a solid opaque block, return -1.0 to indicate solid wall (JMC2OBJ optimization)
    if parsed.is_opaque and parsed.block_type not in (BlockTypeEnum.AIR, BlockTypeEnum.FLUID):
        return -1.0

    return 0.0


def calculate_corner_average(
    h_center: float,
    h_adj1: float,
    h_adj2: float,
    h_diag: float,
) -> float:
    """
    Calculates the averaged fluid height for one corner between center, two adjacent neighbors,
    and the diagonal neighbor using Minecraft Vanilla / JMC2OBJ weighted formula.
    """
    # If any fluid has height 1.0 (submerged/water above), the corner is fully at height 1.0
    if h_center >= 1.0 or h_adj1 >= 1.0 or h_adj2 >= 1.0:
        return 1.0

    samples = [h_center, h_adj1, h_adj2]
    # Sample diagonal block if at least one adjacent neighbor is fluid
    if h_adj1 > 0.0 or h_adj2 > 0.0:
        if h_diag >= 1.0:
            return 1.0
        samples.append(h_diag)

    weighted_sum = 0.0
    total_weight = 0.0

    for h in samples:
        if h >= 0.8:
            # Source blocks or near-full fluids have strong surface tension (weight 10.0)
            weighted_sum += h * 10.0
            total_weight += 10.0
        elif h >= 0.0:
            # Flowing low fluid has weight 1.0
            weighted_sum += h * 1.0
            total_weight += 1.0
        # Negative heights (-1.0 = solid blocks) are ignored! Solid boundaries do not drag water down.

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
        if p_above.name.replace("flowing_", "") == fluid_type:
            return (1.0, 1.0, 1.0, 1.0)

    h_center = sample_fluid_height(block_map, x, y, z, fluid_type)
    h_N = sample_fluid_height(block_map, x, y, z - 1, fluid_type)
    h_S = sample_fluid_height(block_map, x, y, z + 1, fluid_type)
    h_E = sample_fluid_height(block_map, x + 1, y, z, fluid_type)
    h_W = sample_fluid_height(block_map, x - 1, y, z, fluid_type)

    h_NE = sample_fluid_height(block_map, x + 1, y, z - 1, fluid_type)
    h_NW = sample_fluid_height(block_map, x - 1, y, z - 1, fluid_type)
    h_SE = sample_fluid_height(block_map, x + 1, y, z + 1, fluid_type)
    h_SW = sample_fluid_height(block_map, x - 1, y, z + 1, fluid_type)

    c_NW = calculate_corner_average(h_center, h_N, h_W, h_NW)
    c_NE = calculate_corner_average(h_center, h_N, h_E, h_NE)
    c_SE = calculate_corner_average(h_center, h_S, h_E, h_SE)
    c_SW = calculate_corner_average(h_center, h_S, h_W, h_SW)

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
                if p_below.name.replace("flowing_", "") == fluid_type:
                    b_h = get_fluid_base_height(below_state)
                    diff = own_height - (b_h - MAX_FLUID_HEIGHT)
                    vx += dx * diff
                    vz += dz * diff
        else:
            p_n = parse_and_classify(n_state)
            if p_n.name.replace("flowing_", "") == fluid_type:
                n_h = get_fluid_base_height(n_state)
                diff = own_height - n_h
                if diff != 0.0:
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
) -> bool:
    """Helper to emit a single fluid polygon into BMesh."""
    face_bm_verts = [bm.verts.new(v) for v in verts_coords]
    try:
        bm_face = bm.faces.new(face_bm_verts)
    except ValueError:
        return False

    bm_face.material_index = f_res.slot_index
    bm_face[layers["atlas_chunk"]] = f_res.chunk_id
    bm_face[layers["rot"]] = uv_rot
    bm_face[layers["timing"]] = f_res.anim_timing
    bm_face[layers["frame_size"]] = f_res.anim_frame_size
    bm_face[layers["tiling"]] = f_res.uv_tiling_transform
    bm_face[layers["tint_data"]] = f_res.biome_tint_data
    bm_face[layers["tint_color"]] = f_res.biome_tint_color
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
        loop[color_layer] = f_res.biome_tint_color if use_tint else (1.0, 1.0, 1.0, 1.0)

    return True


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
) -> int:
    """
    Construct complete Minecraft fluid geometry (Top, Bottom, and 4 Slanted Sides) for (x, y, z).
    Applies Mineways-standard non-collapsed UVs on slanted sides and JMC2OBJ boundary preservation.
    Returns the number of faces generated.
    """
    parsed = parse_and_classify(state_str)
    fluid_type = parsed.name.replace("flowing_", "")
    if fluid_type not in ("water", "lava"):
        fluid_type = "water"

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

    # Subtle offset to avoid z-fighting with adjacent solid full blocks
    top_NW = max(0.0, c_NW - FLUID_EPSILON)
    top_NE = max(0.0, c_NE - FLUID_EPSILON)
    top_SE = max(0.0, c_SE - FLUID_EPSILON)
    top_SW = max(0.0, c_SW - FLUID_EPSILON)

    # 1. Flow Direction and UV Rotation
    vx, vz, flow_angle = calculate_fluid_flow_vector(block_map, x, y, z, fluid_type, own_height)
    is_flowing = (abs(vx) > 1e-4 or abs(vz) > 1e-4)

    # Resolve Still and Flowing Face Resources
    target_tex_still = f"minecraft:block/{fluid_type}_still"
    target_tex_flow = f"minecraft:block/{fluid_type}_flow"

    res_still = mat_manager.resolve_block_face(parsed, "top", DIR_TO_INDEX["up"])
    res_flow = mat_manager.resolve_block_face(
        parsed=parsed,
        face_name="top",
        face_index=DIR_TO_INDEX["up"],
        json_face_info={"tex": target_tex_flow, "rot": flow_angle} if is_flowing else None,
    )

    top_res = res_flow if is_flowing else res_still
    faces_emitted = 0

    # -------------------------------------------------------------
    # 1. Top Face (UP)
    # -------------------------------------------------------------
    # Cull if block directly above is the same fluid
    above_state = block_map.get((x, y + 1, z))
    cull_top = False
    if above_state:
        p_above = parse_and_classify(above_state)
        if p_above.name.replace("flowing_", "") == fluid_type:
            cull_top = True

    if not cull_top:
        v_nw = (bx - 0.5, by + 0.5, bz - 0.5 + top_NW)
        v_sw = (bx - 0.5, by - 0.5, bz - 0.5 + top_SW)
        v_se = (bx + 0.5, by - 0.5, bz - 0.5 + top_SE)
        v_ne = (bx + 0.5, by + 0.5, bz - 0.5 + top_NE)

        if not is_flowing:
            top_uvs_mc = ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0))
        else:
            # Rotated UV coordinates according to Minecraft FlowingFluid
            s = math.sin(flow_angle) * 0.25
            c = math.cos(flow_angle) * 0.25
            top_uvs_mc = (
                (0.5 - c - s, 0.5 - c + s),  # NW
                (0.5 - c + s, 0.5 + c + s),  # SW
                (0.5 + c + s, 0.5 + c - s),  # SE
                (0.5 + c - s, 0.5 - c - s),  # NE
            )

        if _emit_fluid_face(
            bm=bm,
            verts_coords=(v_nw, v_sw, v_se, v_ne),
            loop_uvs_mc=top_uvs_mc,
            f_res=top_res,
            layers=layers,
            block_pos=(x, y, z),
            face_dir_idx=DIR_TO_INDEX["up"],
            uv_rot=flow_angle if is_flowing else 0.0,
            use_tint=top_res.use_tint,
        ):
            faces_emitted += 1

    # -------------------------------------------------------------
    # 2. Bottom Face (DOWN)
    # -------------------------------------------------------------
    below_state = block_map.get((x, y - 1, z))
    cull_bottom = False
    if below_state:
        p_below = parse_and_classify(below_state)
        if p_below.name.replace("flowing_", "") == fluid_type:
            cull_bottom = True
        elif p_below.is_opaque and p_below.block_type not in (BlockTypeEnum.AIR, BlockTypeEnum.FLUID):
            cull_bottom = True

    if not cull_bottom:
        v_bot_sw = (bx - 0.5, by - 0.5, bz - 0.5)
        v_bot_nw = (bx - 0.5, by + 0.5, bz - 0.5)
        v_bot_ne = (bx + 0.5, by + 0.5, bz - 0.5)
        v_bot_se = (bx + 0.5, by - 0.5, bz - 0.5)
        bot_uvs_mc = ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0))

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
        ):
            faces_emitted += 1

    # -------------------------------------------------------------
    # 3. Side Faces (North, South, West, East) - Mineways Accurate UV
    # -------------------------------------------------------------
    # For flowing side faces, Minecraft uses flowing texture (water_flow / lava_flow)
    side_res = res_flow if (is_flowing or own_height < MAX_FLUID_HEIGHT) else res_still

    def _should_cull_side(nx: int, ny: int, nz: int, h_top_max: float) -> bool:
        n_state = block_map.get((nx, ny, nz))
        if not n_state:
            return False
        p_n = parse_and_classify(n_state)
        if p_n.is_opaque and p_n.block_type not in (BlockTypeEnum.AIR, BlockTypeEnum.FLUID):
            return True
        if p_n.name.replace("flowing_", "") == fluid_type:
            # Check if neighbor has water above it
            above_n = block_map.get((nx, ny + 1, nz))
            if above_n and parse_and_classify(above_n).name.replace("flowing_", "") == fluid_type:
                return True
            n_base_h = get_fluid_base_height(n_state)
            if n_base_h >= h_top_max - 1e-4:
                return True
        return False

    # A. North Face (facing Blender +Y / MC North -Z)
    if not _should_cull_side(x, y, z - 1, max(c_NW, c_NE)):
        v_ne_top = (bx + 0.5, by + 0.5, bz - 0.5 + top_NE)
        v_ne_bot = (bx + 0.5, by + 0.5, bz - 0.5)
        v_nw_bot = (bx - 0.5, by + 0.5, bz - 0.5)
        v_nw_top = (bx - 0.5, by + 0.5, bz - 0.5 + top_NW)
        # Mineways & Vanilla UV mapping: top vertex at height h gets V_mc = 1.0 - h
        north_uvs_mc = (
            (0.0, 1.0 - top_NE),
            (0.0, 1.0),
            (1.0, 1.0),
            (1.0, 1.0 - top_NW),
        )
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
        ):
            faces_emitted += 1

    # B. South Face (facing Blender -Y / MC South +Z)
    if not _should_cull_side(x, y, z + 1, max(c_SW, c_SE)):
        v_sw_top = (bx - 0.5, by - 0.5, bz - 0.5 + top_SW)
        v_sw_bot = (bx - 0.5, by - 0.5, bz - 0.5)
        v_se_bot = (bx + 0.5, by - 0.5, bz - 0.5)
        v_se_top = (bx + 0.5, by - 0.5, bz - 0.5 + top_SE)
        south_uvs_mc = (
            (0.0, 1.0 - top_SW),
            (0.0, 1.0),
            (1.0, 1.0),
            (1.0, 1.0 - top_SE),
        )
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
        ):
            faces_emitted += 1

    # C. West Face (facing Blender -X / MC West -X)
    if not _should_cull_side(x - 1, y, z, max(c_NW, c_SW)):
        v_nw_top = (bx - 0.5, by + 0.5, bz - 0.5 + top_NW)
        v_nw_bot = (bx - 0.5, by + 0.5, bz - 0.5)
        v_sw_bot = (bx - 0.5, by - 0.5, bz - 0.5)
        v_sw_top = (bx - 0.5, by - 0.5, bz - 0.5 + top_SW)
        west_uvs_mc = (
            (0.0, 1.0 - top_NW),
            (0.0, 1.0),
            (1.0, 1.0),
            (1.0, 1.0 - top_SW),
        )
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
        ):
            faces_emitted += 1

    # D. East Face (facing Blender +X / MC East +X)
    if not _should_cull_side(x + 1, y, z, max(c_SE, c_NE)):
        v_se_top = (bx + 0.5, by - 0.5, bz - 0.5 + top_SE)
        v_se_bot = (bx + 0.5, by - 0.5, bz - 0.5)
        v_ne_bot = (bx + 0.5, by + 0.5, bz - 0.5)
        v_ne_top = (bx + 0.5, by + 0.5, bz - 0.5 + top_NE)
        east_uvs_mc = (
            (0.0, 1.0 - top_SE),
            (0.0, 1.0),
            (1.0, 1.0),
            (1.0, 1.0 - top_NE),
        )
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
        ):
            faces_emitted += 1

    return faces_emitted

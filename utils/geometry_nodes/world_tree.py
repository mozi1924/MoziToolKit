"""Geometry Nodes World Tree Orchestrator for MoziToolKit Live Sync.

Assembles reusable Geometry Node Groups into a high-performance procedural Minecraft world
evaluating on Point Cloud objects.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
import bpy

from ..live_sync.constants import (
    BLOCK_CENTER,
    BLOCK_TYPE,
    DIRECTIONAL_FACE_V_FLIP,
    INSTANCE_ROTATION,
    LOCAL_FACE_ID,
    LOCAL_UV,
    MTK_ANIM_ATLAS_HEIGHT,
    MTK_ANIM_ATLAS_WIDTH,
    MTK_ANIM_FRAME_HEIGHT,
    MTK_ANIM_FRAME_SIZE,
    MTK_ANIM_FRAME_WIDTH,
    MTK_ANIM_TIMING,
    MTK_ATLAS_CHUNK_ID,
    MTK_ATLAS_HEIGHT,
    MTK_ATLAS_TEXTURE_ID,
    MTK_BIOME_TINT_COLOR,
    MTK_BIOME_TINT_DATA,
    MTK_TILE_SIZE,
    MTK_TILES_PER_ROW,
    MTK_UV_ROTATION,
    MTK_UV_TILING_TRANSFORM,
    TEMPLATE_INDEX,
    UV_MAP,
    face_attribute,
)
from ..live_sync.template_catalog import (
    TEMPLATE_COLLECTION_NAME,
    get_or_create_template_collection,
)
from ..materials.yefira import (
    extract_atlas_parameters,
    find_all_atlas_chunk_materials,
    find_bound_atlas_material,
    get_or_create_atlas_material,
    setup_material_slots_for_object,
)
from .core import ensure_socket, prune_unlinked_nodes
from .groups import (
    get_or_create_atlas_uv_calculator_group,
    get_or_create_cube_surface_group,
    get_or_create_culling_merge_group,
    get_or_create_face_selector_color_group,
    get_or_create_face_selector_float_group,
    get_or_create_face_selector_int_group,
    get_or_create_face_selector_vector_group,
    get_or_create_instance_attribute_transfer_group,
    get_or_create_material_dispatcher_group,
)

logger = logging.getLogger("MoziToolKit.GeometryNodes")

WORLD_TREE_NAME = "Yefira_WorldTree"
WORLD_MODIFIER_NAME = "Yefira_WorldModifier"
WORLD_TREE_SCHEMA_VERSION = 27
WORLD_TREE_SCHEMA_PROPERTY = "yefira:world_tree_schema"


def setup_world_geometry_nodes(
    world_obj: bpy.types.Object,
    template_col: Optional[bpy.types.Collection] = None,
) -> Optional[bpy.types.Modifier]:
    """
    Attach and configure the unified Geometry Nodes tree on the Yefira_World point cloud.
    Handles Cube instancing, Collection Info prop instancing, rotation, and multi-chunk Material binding.
    """
    if not world_obj:
        return None

    if not template_col:
        template_col = get_or_create_template_collection(bpy.context)

    # Resolve bound Atlas material and mapping
    mat = find_bound_atlas_material(world_obj) or get_or_create_atlas_material()
    atlas_params = extract_atlas_parameters(mat)

    # Populate all material slots on world_obj in chunk_id order
    setup_material_slots_for_object(world_obj, mat, atlas_params.get("mapping"))

    # Resolve all chunk materials and construct/update independent Material Dispatcher group
    chunk_mats = find_all_atlas_chunk_materials(atlas_params.get("mapping"), bound_material=mat, obj=world_obj)
    if not chunk_mats:
        fallback_mat = find_bound_atlas_material(world_obj) or find_bound_atlas_material(None) or get_or_create_atlas_material()
        if fallback_mat:
            chunk_mats = {0: fallback_mat}

    group_mat_dispatcher = get_or_create_material_dispatcher_group(chunk_mats)

    mod = world_obj.modifiers.get(WORLD_MODIFIER_NAME)
    if not mod:
        mod = world_obj.modifiers.new(name=WORLD_MODIFIER_NAME, type="NODES")

    gn_tree = bpy.data.node_groups.get(WORLD_TREE_NAME)
    if gn_tree and gn_tree.get(WORLD_TREE_SCHEMA_PROPERTY) == WORLD_TREE_SCHEMA_VERSION:
        _update_tree_bindings(gn_tree, template_col, group_mat_dispatcher)
    elif gn_tree:
        gn_tree.nodes.clear()
        _remove_legacy_atlas_inputs(gn_tree)
        ensure_socket(gn_tree, "Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        ensure_socket(gn_tree, "Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
        _build_tree_nodes_and_links(gn_tree, template_col, atlas_params, group_mat_dispatcher)
        gn_tree[WORLD_TREE_SCHEMA_PROPERTY] = WORLD_TREE_SCHEMA_VERSION
    else:
        gn_tree = _create_world_geometry_node_tree(WORLD_TREE_NAME, template_col, atlas_params, group_mat_dispatcher)
        gn_tree[WORLD_TREE_SCHEMA_PROPERTY] = WORLD_TREE_SCHEMA_VERSION

    mod.node_group = gn_tree
    return mod


def _update_tree_bindings(
    tree: bpy.types.GeometryNodeTree,
    template_col: bpy.types.Collection,
    group_mat_dispatcher: bpy.types.GeometryNodeTree,
) -> None:
    """Refresh external data-block references without rebuilding nodes."""
    for node in tree.nodes:
        if node.bl_idname == "GeometryNodeCollectionInfo" and "Collection" in node.inputs:
            node.inputs["Collection"].default_value = template_col
        elif node.bl_idname == "GeometryNodeGroup" and node.name == "Material Dispatcher":
            node.node_tree = group_mat_dispatcher
        elif node.bl_idname == "GeometryNodeGroup" and node.name == "Hidden Face Culling & Merge":
            node.node_tree = get_or_create_culling_merge_group()


def _remove_legacy_atlas_inputs(tree: bpy.types.GeometryNodeTree) -> None:
    """Remove former user-facing atlas controls during migration."""
    for item in list(tree.interface.items_tree):
        if (
            item.item_type == "SOCKET"
            and item.in_out == "INPUT"
            and item.name in {"Atlas Width", "Atlas Height", "Tile Size", "Tiles Per Row"}
        ):
            tree.interface.remove(item)


def _create_world_geometry_node_tree(
    tree_name: str,
    template_col: bpy.types.Collection,
    atlas_params: Dict[str, Any],
    group_mat_dispatcher: bpy.types.GeometryNodeTree,
) -> bpy.types.GeometryNodeTree:
    gn_tree = bpy.data.node_groups.new(name=tree_name, type="GeometryNodeTree")
    ensure_socket(gn_tree, "Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ensure_socket(gn_tree, "Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    _build_tree_nodes_and_links(gn_tree, template_col, atlas_params, group_mat_dispatcher)
    return gn_tree


def _build_tree_nodes_and_links(
    gn_tree: bpy.types.GeometryNodeTree,
    template_col: bpy.types.Collection,
    atlas_params: Dict[str, Any],
    group_mat_dispatcher: bpy.types.GeometryNodeTree,
) -> None:
    nodes = gn_tree.nodes
    links = gn_tree.links

    # 1. Ensure all reusable sub-groups exist
    group_vec_selector = get_or_create_face_selector_vector_group()
    group_int_selector = get_or_create_face_selector_int_group()
    group_color_selector = get_or_create_face_selector_color_group()
    group_float_selector = get_or_create_face_selector_float_group()
    group_uv_calc = get_or_create_atlas_uv_calculator_group()
    group_cube_surface = get_or_create_cube_surface_group()
    group_attribute_transfer = get_or_create_instance_attribute_transfer_group()
    group_culling_merge = get_or_create_culling_merge_group()

    # 2. Top-level Inputs & Outputs
    group_in = nodes.new("NodeGroupInput")
    group_in.location = (-800, 100)

    group_out = nodes.new("NodeGroupOutput")
    group_out.location = (2460, 100)

    # 3. Named Attribute Readers from Point Cloud
    attr_type = nodes.new("GeometryNodeInputNamedAttribute")
    attr_type.data_type = "INT"
    attr_type.inputs["Name"].default_value = BLOCK_TYPE
    attr_type.location = (-800, -100)

    attr_idx = nodes.new("GeometryNodeInputNamedAttribute")
    attr_idx.data_type = "INT"
    attr_idx.inputs["Name"].default_value = TEMPLATE_INDEX
    attr_idx.location = (-800, -250)

    attr_rot = nodes.new("GeometryNodeInputNamedAttribute")
    attr_rot.data_type = "FLOAT_VECTOR"
    attr_rot.inputs["Name"].default_value = INSTANCE_ROTATION
    attr_rot.location = (-800, -400)

    # 4. Compare block_type == 0 (Cubes)
    cmp_cube = nodes.new("FunctionNodeCompare")
    cmp_cube.data_type = "INT"
    cmp_cube.operation = "EQUAL"
    cmp_cube.inputs["B"].default_value = 0
    cmp_cube.location = (-600, 0)
    links.new(attr_type.outputs["Attribute"], cmp_cube.inputs["A"])

    # 5. Separate Geometry (Cubes vs Props)
    sep_geo = nodes.new("GeometryNodeSeparateGeometry")
    sep_geo.location = (-600, 100)
    links.new(group_in.outputs["Geometry"], sep_geo.inputs["Geometry"])
    links.new(cmp_cube.outputs["Result"], sep_geo.inputs["Selection"])

    # --- BRANCH A: Standard Cubes with Instance Attribute Transfer ---
    cube_surface = nodes.new("GeometryNodeGroup")
    cube_surface.node_tree = group_cube_surface
    cube_surface.name = "Minecraft Cube Surface"
    cube_surface.label = "Cube Surface + Local UV"
    cube_surface.location = (-400, 250)

    iop_cube = nodes.new("GeometryNodeInstanceOnPoints")
    iop_cube.location = (-200, 250)
    links.new(sep_geo.outputs["Selection"], iop_cube.inputs["Points"])
    links.new(cube_surface.outputs["Geometry"], iop_cube.inputs["Instance"])

    transfer_cube_attributes = nodes.new("GeometryNodeGroup")
    transfer_cube_attributes.node_tree = group_attribute_transfer
    transfer_cube_attributes.name = "Transfer Cube Instance Attributes"
    transfer_cube_attributes.label = "Transfer Instance Attributes"
    transfer_cube_attributes.location = (0, 250)
    links.new(iop_cube.outputs["Instances"], transfer_cube_attributes.inputs["Geometry"])
    last_cube_geo = transfer_cube_attributes.outputs["Geometry"]

    # --- BRANCH B: Collection Props with Instance Attribute Transfer ---
    col_info = nodes.new("GeometryNodeCollectionInfo")
    col_info.inputs["Collection"].default_value = template_col
    col_info.inputs["Separate Children"].default_value = True
    col_info.inputs["Reset Children"].default_value = True
    col_info.location = (-400, -150)

    iop_prop = nodes.new("GeometryNodeInstanceOnPoints")
    iop_prop.inputs["Pick Instance"].default_value = True
    iop_prop.location = (-200, -150)
    links.new(sep_geo.outputs["Inverted"], iop_prop.inputs["Points"])
    links.new(col_info.outputs["Instances"], iop_prop.inputs["Instance"])
    links.new(attr_idx.outputs["Attribute"], iop_prop.inputs["Instance Index"])
    links.new(attr_rot.outputs["Attribute"], iop_prop.inputs["Rotation"])

    transfer_prop_attributes = nodes.new("GeometryNodeGroup")
    transfer_prop_attributes.node_tree = group_attribute_transfer
    transfer_prop_attributes.name = "Transfer Prop Instance Attributes"
    transfer_prop_attributes.label = "Transfer Instance Attributes"
    transfer_prop_attributes.location = (0, -150)
    links.new(iop_prop.outputs["Instances"], transfer_prop_attributes.inputs["Geometry"])
    last_prop_geo = transfer_prop_attributes.outputs["Geometry"]

    # --- JOIN BRANCHES & REALIZE ---
    join_node = nodes.new("GeometryNodeJoinGeometry")
    join_node.location = (200, 100)
    links.new(last_cube_geo, join_node.inputs["Geometry"])
    links.new(last_prop_geo, join_node.inputs["Geometry"])

    realize_node = nodes.new("GeometryNodeRealizeInstances")
    realize_node.location = (380, 100)
    links.new(join_node.outputs["Geometry"], realize_node.inputs["Geometry"])

    # Read Realized LocalFaceID (INT on FACE domain)
    read_face_id = nodes.new("GeometryNodeInputNamedAttribute")
    read_face_id.data_type = "INT"
    read_face_id.inputs["Name"].default_value = LOCAL_FACE_ID
    read_face_id.location = (380, -100)

    # --- SUBGROUP: SELECT FACE TILE (VECTOR) ---
    call_tile_selector = nodes.new("GeometryNodeGroup")
    call_tile_selector.node_tree = group_vec_selector
    call_tile_selector.name = "Select Face Tile"
    call_tile_selector.location = (760, 500)
    links.new(read_face_id.outputs["Attribute"], call_tile_selector.inputs["Face ID"])

    for index, (socket_name, attr_name) in enumerate((
        ("Top (+Z)", face_attribute("tile", "top")),
        ("Bottom (-Z)", face_attribute("tile", "bottom")),
        ("East (+X)", face_attribute("tile", "east")),
        ("West (-X)", face_attribute("tile", "west")),
        ("North (+Y)", face_attribute("tile", "north")),
        ("South (-Y)", face_attribute("tile", "south")),
    )):
        reader = nodes.new("GeometryNodeInputNamedAttribute")
        reader.data_type = "FLOAT_VECTOR"
        reader.inputs["Name"].default_value = attr_name
        reader.location = (560, 600 - index * 40)
        links.new(reader.outputs["Attribute"], call_tile_selector.inputs[socket_name])

    # --- SUBGROUP: SELECT FACE CHUNK ID (INT) ---
    call_chunk_selector = nodes.new("GeometryNodeGroup")
    call_chunk_selector.node_tree = group_int_selector
    call_chunk_selector.name = "Select Face Chunk ID"
    call_chunk_selector.location = (760, 260)
    links.new(read_face_id.outputs["Attribute"], call_chunk_selector.inputs["Face ID"])

    for index, (socket_name, face) in enumerate((
        ("Top (+Z)", "top"),
        ("Bottom (-Z)", "bottom"),
        ("East (+X)", "east"),
        ("West (-X)", "west"),
        ("North (+Y)", "north"),
        ("South (-Y)", "south"),
    )):
        reader = nodes.new("GeometryNodeInputNamedAttribute")
        reader.data_type = "INT"
        reader.inputs["Name"].default_value = face_attribute("chunk", face)
        reader.location = (560, 320 - index * 40)
        links.new(reader.outputs["Attribute"], call_chunk_selector.inputs[socket_name])

    # --- SUBGROUP: ATLAS UV CALCULATOR ---
    call_uv_calc = nodes.new("GeometryNodeGroup")
    call_uv_calc.node_tree = group_uv_calc
    call_uv_calc.name = "Calculate Atlas UV"
    call_uv_calc.location = (2800, 300)
    links.new(call_tile_selector.outputs["Selected"], call_uv_calc.inputs["Target Tile"])

    # --- SUBGROUP: SELECT FACE UV ROTATION (FLOAT) ---
    call_uv_rot_selector = nodes.new("GeometryNodeGroup")
    call_uv_rot_selector.node_tree = group_float_selector
    call_uv_rot_selector.name = "Select Face UV Rotation"
    call_uv_rot_selector.location = (760, 20)
    links.new(read_face_id.outputs["Attribute"], call_uv_rot_selector.inputs["Face ID"])

    for index, (socket_name, face) in enumerate((
        ("Top (+Z)", "top"),
        ("Bottom (-Z)", "bottom"),
        ("East (+X)", "east"),
        ("West (-X)", "west"),
        ("North (+Y)", "north"),
        ("South (-Y)", "south"),
    )):
        reader = nodes.new("GeometryNodeInputNamedAttribute")
        reader.data_type = "FLOAT"
        reader.inputs["Name"].default_value = face_attribute("uv_rot", face)
        reader.location = (560, 40 - index * 35)
        links.new(reader.outputs["Attribute"], call_uv_rot_selector.inputs[socket_name])

    # --- SUBGROUP: SELECT FACE UV BOUNDS (COLOR) ---
    call_uv_bounds_selector = nodes.new("GeometryNodeGroup")
    call_uv_bounds_selector.node_tree = group_color_selector
    call_uv_bounds_selector.name = "Select Face UV Bounds"
    call_uv_bounds_selector.location = (760, -220)
    links.new(read_face_id.outputs["Attribute"], call_uv_bounds_selector.inputs["Face ID"])

    for index, (socket_name, face) in enumerate((
        ("Top (+Z)", "top"),
        ("Bottom (-Z)", "bottom"),
        ("East (+X)", "east"),
        ("West (-X)", "west"),
        ("North (+Y)", "north"),
        ("South (-Y)", "south"),
    )):
        reader = nodes.new("GeometryNodeInputNamedAttribute")
        reader.data_type = "FLOAT_COLOR"
        reader.inputs["Name"].default_value = face_attribute("uv_bounds", face)
        reader.location = (560, -200 - index * 35)
        links.new(reader.outputs["Attribute"], call_uv_bounds_selector.inputs[socket_name])

    # --- SUBGROUP: SELECT FACE ANIM TIMING (COLOR) ---
    call_timing_selector = nodes.new("GeometryNodeGroup")
    call_timing_selector.node_tree = group_color_selector
    call_timing_selector.name = "Select Face Anim Timing"
    call_timing_selector.location = (760, -850)
    links.new(read_face_id.outputs["Attribute"], call_timing_selector.inputs["Face ID"])

    for index, (socket_name, face) in enumerate((
        ("Top (+Z)", "top"),
        ("Bottom (-Z)", "bottom"),
        ("East (+X)", "east"),
        ("West (-X)", "west"),
        ("North (+Y)", "north"),
        ("South (-Y)", "south"),
    )):
        reader = nodes.new("GeometryNodeInputNamedAttribute")
        reader.data_type = "FLOAT_COLOR"
        reader.inputs["Name"].default_value = face_attribute("anim_timing", face)
        reader.location = (560, -780 - index * 40)
        links.new(reader.outputs["Attribute"], call_timing_selector.inputs[socket_name])

    sep_timing = nodes.new("FunctionNodeSeparateColor")
    sep_timing.location = (2560, -600)
    links.new(call_timing_selector.outputs["Selected"], sep_timing.inputs["Color"])

    # Read Realized LocalUV (FLOAT_VECTOR on CORNER domain)
    read_local_uv = nodes.new("GeometryNodeInputNamedAttribute")
    read_local_uv.data_type = "FLOAT_VECTOR"
    read_local_uv.inputs["Name"].default_value = LOCAL_UV
    read_local_uv.location = (760, -450)

    sep_local_uv = nodes.new("ShaderNodeSeparateXYZ")
    sep_local_uv.location = (940, -450)
    links.new(read_local_uv.outputs["Attribute"], sep_local_uv.inputs["Vector"])

    one_minus_u = nodes.new("ShaderNodeMath")
    one_minus_u.operation = "SUBTRACT"
    one_minus_u.inputs[0].default_value = 1.0
    one_minus_u.location = (1100, -420)
    links.new(sep_local_uv.outputs["X"], one_minus_u.inputs[1])

    one_minus_v = nodes.new("ShaderNodeMath")
    one_minus_v.operation = "SUBTRACT"
    one_minus_v.inputs[0].default_value = 1.0
    one_minus_v.location = (1100, -520)
    links.new(sep_local_uv.outputs["Y"], one_minus_v.inputs[1])

    comb_0 = nodes.new("ShaderNodeCombineXYZ")
    comb_0.location = (1260, -360)
    links.new(sep_local_uv.outputs["X"], comb_0.inputs["X"])
    links.new(sep_local_uv.outputs["Y"], comb_0.inputs["Y"])

    comb_90 = nodes.new("ShaderNodeCombineXYZ")
    comb_90.location = (1260, -460)
    links.new(one_minus_v.outputs["Value"], comb_90.inputs["X"])
    links.new(sep_local_uv.outputs["X"], comb_90.inputs["Y"])

    comb_180 = nodes.new("ShaderNodeCombineXYZ")
    comb_180.location = (1260, -560)
    links.new(one_minus_u.outputs["Value"], comb_180.inputs["X"])
    links.new(one_minus_v.outputs["Value"], comb_180.inputs["Y"])

    comb_270 = nodes.new("ShaderNodeCombineXYZ")
    comb_270.location = (1260, -660)
    links.new(sep_local_uv.outputs["Y"], comb_270.inputs["X"])
    links.new(one_minus_u.outputs["Value"], comb_270.inputs["Y"])

    # Rotation selection switches
    cmp_rot_225 = nodes.new("FunctionNodeCompare")
    cmp_rot_225.data_type = "FLOAT"
    cmp_rot_225.operation = "GREATER_THAN"
    cmp_rot_225.inputs["B"].default_value = 225.0
    cmp_rot_225.location = (1100, -660)
    links.new(call_uv_rot_selector.outputs["Selected"], cmp_rot_225.inputs["A"])

    sw_rot_270 = nodes.new("GeometryNodeSwitch")
    sw_rot_270.input_type = "VECTOR"
    sw_rot_270.location = (1440, -560)
    links.new(cmp_rot_225.outputs["Result"], sw_rot_270.inputs["Switch"])
    links.new(comb_180.outputs["Vector"], sw_rot_270.inputs["False"])
    links.new(comb_270.outputs["Vector"], sw_rot_270.inputs["True"])

    cmp_rot_135 = nodes.new("FunctionNodeCompare")
    cmp_rot_135.data_type = "FLOAT"
    cmp_rot_135.operation = "GREATER_THAN"
    cmp_rot_135.inputs["B"].default_value = 135.0
    cmp_rot_135.location = (1100, -760)
    links.new(call_uv_rot_selector.outputs["Selected"], cmp_rot_135.inputs["A"])

    sw_rot_180 = nodes.new("GeometryNodeSwitch")
    sw_rot_180.input_type = "VECTOR"
    sw_rot_180.location = (1600, -460)
    links.new(cmp_rot_135.outputs["Result"], sw_rot_180.inputs["Switch"])
    links.new(comb_90.outputs["Vector"], sw_rot_180.inputs["False"])
    links.new(sw_rot_270.outputs["Output"], sw_rot_180.inputs["True"])

    cmp_rot_45 = nodes.new("FunctionNodeCompare")
    cmp_rot_45.data_type = "FLOAT"
    cmp_rot_45.operation = "GREATER_THAN"
    cmp_rot_45.inputs["B"].default_value = 45.0
    cmp_rot_45.location = (1100, -860)
    links.new(call_uv_rot_selector.outputs["Selected"], cmp_rot_45.inputs["A"])

    sw_rot_final = nodes.new("GeometryNodeSwitch")
    sw_rot_final.input_type = "VECTOR"
    sw_rot_final.location = (1760, -360)
    links.new(cmp_rot_45.outputs["Result"], sw_rot_final.inputs["Switch"])
    links.new(comb_0.outputs["Vector"], sw_rot_final.inputs["False"])
    links.new(sw_rot_180.outputs["Output"], sw_rot_final.inputs["True"])

    sep_rot_uv = nodes.new("ShaderNodeSeparateXYZ")
    sep_rot_uv.location = (1920, -360)
    links.new(sw_rot_final.outputs["Output"], sep_rot_uv.inputs["Vector"])

    sep_bounds = nodes.new("FunctionNodeSeparateColor")
    sep_bounds.location = (1920, -560)
    links.new(call_uv_bounds_selector.outputs["Selected"], sep_bounds.inputs["Color"])

    sub_du = nodes.new("ShaderNodeMath")
    sub_du.operation = "SUBTRACT"
    sub_du.location = (2080, -500)
    links.new(sep_bounds.outputs["Blue"], sub_du.inputs[0])
    links.new(sep_bounds.outputs["Red"], sub_du.inputs[1])

    sub_dv = nodes.new("ShaderNodeMath")
    sub_dv.operation = "SUBTRACT"
    sub_dv.location = (2080, -620)
    links.new(sep_bounds.outputs["Alpha"], sub_dv.inputs[0])
    links.new(sep_bounds.outputs["Green"], sub_dv.inputs[1])

    mul_u = nodes.new("ShaderNodeMath")
    mul_u.operation = "MULTIPLY"
    mul_u.location = (2240, -400)
    links.new(sep_rot_uv.outputs["X"], mul_u.inputs[0])
    links.new(sub_du.outputs["Value"], mul_u.inputs[1])

    add_u_final = nodes.new("ShaderNodeMath")
    add_u_final.operation = "ADD"
    add_u_final.location = (2400, -400)
    links.new(sep_bounds.outputs["Red"], add_u_final.inputs[0])
    links.new(mul_u.outputs["Value"], add_u_final.inputs[1])

    mul_v = nodes.new("ShaderNodeMath")
    mul_v.operation = "MULTIPLY"
    mul_v.location = (2240, -520)
    links.new(sep_rot_uv.outputs["Y"], mul_v.inputs[0])
    links.new(sub_dv.outputs["Value"], mul_v.inputs[1])

    add_v_final = nodes.new("ShaderNodeMath")
    add_v_final.operation = "ADD"
    add_v_final.location = (2400, -520)
    links.new(sep_bounds.outputs["Green"], add_v_final.inputs[0])
    links.new(mul_v.outputs["Value"], add_v_final.inputs[1])

    comb_local_uv_final = nodes.new("ShaderNodeCombineXYZ")
    comb_local_uv_final.location = (2560, -460)
    links.new(add_u_final.outputs["Value"], comb_local_uv_final.inputs["X"])
    links.new(add_v_final.outputs["Value"], comb_local_uv_final.inputs["Y"])

    links.new(comb_local_uv_final.outputs["Vector"], call_uv_calc.inputs["Local UV"])
    links.new(call_chunk_selector.outputs["Selected"], call_uv_calc.inputs["Chunk ID"])
    links.new(sep_timing.outputs["Red"], call_uv_calc.inputs["Anim Frame Count"])

    for index, (socket_name, attr_name) in enumerate((
        ("Tiles Per Row", MTK_TILES_PER_ROW),
        ("Tile Size", MTK_TILE_SIZE),
        ("Atlas Height", MTK_ATLAS_HEIGHT),
        ("Anim Atlas Width", MTK_ANIM_ATLAS_WIDTH),
        ("Anim Atlas Height", MTK_ANIM_ATLAS_HEIGHT),
        ("Anim Frame Width", MTK_ANIM_FRAME_WIDTH),
        ("Anim Frame Height", MTK_ANIM_FRAME_HEIGHT),
    )):
        reader = nodes.new("GeometryNodeInputNamedAttribute")
        reader.data_type = "FLOAT"
        reader.inputs["Name"].default_value = attr_name
        reader.location = (760, 160 - index * 40)
        links.new(reader.outputs["Attribute"], call_uv_calc.inputs[socket_name])

    # Store UVMap (CORNER)
    store_uv_final = nodes.new("GeometryNodeStoreNamedAttribute")
    store_uv_final.data_type = "FLOAT_VECTOR"
    store_uv_final.domain = "CORNER"
    store_uv_final.inputs["Name"].default_value = UV_MAP
    store_uv_final.location = (1180, 100)
    links.new(realize_node.outputs["Geometry"], store_uv_final.inputs["Geometry"])
    links.new(call_uv_calc.outputs["Atlas UV"], store_uv_final.inputs["Value"])

    # Store UV Tiling Transform
    store_tiling = nodes.new("GeometryNodeStoreNamedAttribute")
    store_tiling.data_type = "FLOAT_COLOR"
    store_tiling.domain = "CORNER"
    store_tiling.inputs["Name"].default_value = MTK_UV_TILING_TRANSFORM
    store_tiling.inputs["Value"].default_value = (1.0, 1.0, 0.0, 0.0)
    store_tiling.location = (1360, 100)
    links.new(store_uv_final.outputs["Geometry"], store_tiling.inputs["Geometry"])

    # Store UV Rotation
    store_rot = nodes.new("GeometryNodeStoreNamedAttribute")
    store_rot.data_type = "FLOAT"
    store_rot.domain = "CORNER"
    store_rot.inputs["Name"].default_value = MTK_UV_ROTATION
    store_rot.inputs["Value"].default_value = 0.0
    store_rot.location = (1540, 100)
    links.new(store_tiling.outputs["Geometry"], store_rot.inputs["Geometry"])

    # --- SUBGROUP: SELECT FACE TINT DATA (COLOR) ---
    call_tint_selector = nodes.new("GeometryNodeGroup")
    call_tint_selector.node_tree = group_color_selector
    call_tint_selector.name = "Select Biome Tint Data"
    call_tint_selector.location = (760, -100)
    links.new(read_face_id.outputs["Attribute"], call_tint_selector.inputs["Face ID"])

    for index, (socket_name, face) in enumerate((
        ("Top (+Z)", "top"),
        ("Bottom (-Z)", "bottom"),
        ("East (+X)", "east"),
        ("West (-X)", "west"),
        ("North (+Y)", "north"),
        ("South (-Y)", "south"),
    )):
        reader = nodes.new("GeometryNodeInputNamedAttribute")
        reader.data_type = "FLOAT_COLOR"
        reader.inputs["Name"].default_value = face_attribute("tint_data", face)
        reader.location = (560, -30 - index * 40)
        links.new(reader.outputs["Attribute"], call_tint_selector.inputs[socket_name])

    store_tint_data = nodes.new("GeometryNodeStoreNamedAttribute")
    store_tint_data.data_type = "FLOAT_COLOR"
    store_tint_data.domain = "FACE"
    store_tint_data.inputs["Name"].default_value = MTK_BIOME_TINT_DATA
    store_tint_data.location = (1720, 100)
    links.new(store_rot.outputs["Geometry"], store_tint_data.inputs["Geometry"])
    links.new(call_tint_selector.outputs["Selected"], store_tint_data.inputs["Value"])

    # --- SUBGROUP: SELECT FACE CHUNK ID (INT) ---
    store_chunk_id = nodes.new("GeometryNodeStoreNamedAttribute")
    store_chunk_id.data_type = "INT"
    store_chunk_id.domain = "FACE"
    store_chunk_id.inputs["Name"].default_value = MTK_ATLAS_CHUNK_ID
    store_chunk_id.location = (1900, 100)
    links.new(store_tint_data.outputs["Geometry"], store_chunk_id.inputs["Geometry"])
    links.new(call_chunk_selector.outputs["Selected"], store_chunk_id.inputs["Value"])

    # --- SUBGROUP: SELECT FACE TEXTURE ID (INT) ---
    call_texture_selector = nodes.new("GeometryNodeGroup")
    call_texture_selector.node_tree = group_int_selector
    call_texture_selector.name = "Select Face Texture ID"
    call_texture_selector.location = (760, -600)
    links.new(read_face_id.outputs["Attribute"], call_texture_selector.inputs["Face ID"])

    for index, (socket_name, face) in enumerate((
        ("Top (+Z)", "top"),
        ("Bottom (-Z)", "bottom"),
        ("East (+X)", "east"),
        ("West (-X)", "west"),
        ("North (+Y)", "north"),
        ("South (-Y)", "south"),
    )):
        reader = nodes.new("GeometryNodeInputNamedAttribute")
        reader.data_type = "INT"
        reader.inputs["Name"].default_value = face_attribute("texture", face)
        reader.location = (560, -530 - index * 40)
        links.new(reader.outputs["Attribute"], call_texture_selector.inputs[socket_name])

    store_texture_id = nodes.new("GeometryNodeStoreNamedAttribute")
    store_texture_id.data_type = "INT"
    store_texture_id.domain = "FACE"
    store_texture_id.inputs["Name"].default_value = MTK_ATLAS_TEXTURE_ID
    store_texture_id.location = (2080, 100)
    links.new(store_chunk_id.outputs["Geometry"], store_texture_id.inputs["Geometry"])
    links.new(call_texture_selector.outputs["Selected"], store_texture_id.inputs["Value"])

    # --- SUBGROUP: STORE ANIM TIMING (FACE domain) ---
    store_timing = nodes.new("GeometryNodeStoreNamedAttribute")
    store_timing.data_type = "FLOAT_COLOR"
    store_timing.domain = "FACE"
    store_timing.inputs["Name"].default_value = MTK_ANIM_TIMING
    store_timing.location = (2260, 100)
    links.new(store_texture_id.outputs["Geometry"], store_timing.inputs["Geometry"])
    links.new(call_timing_selector.outputs["Selected"], store_timing.inputs["Value"])

    # --- SUBGROUP: SELECT FACE ANIM FRAME SIZE (COLOR) ---
    call_size_selector = nodes.new("GeometryNodeGroup")
    call_size_selector.node_tree = group_color_selector
    call_size_selector.name = "Select Face Anim Frame Size"
    call_size_selector.location = (760, -1100)
    links.new(read_face_id.outputs["Attribute"], call_size_selector.inputs["Face ID"])

    for index, (socket_name, face) in enumerate((
        ("Top (+Z)", "top"),
        ("Bottom (-Z)", "bottom"),
        ("East (+X)", "east"),
        ("West (-X)", "west"),
        ("North (+Y)", "north"),
        ("South (-Y)", "south"),
    )):
        reader = nodes.new("GeometryNodeInputNamedAttribute")
        reader.data_type = "FLOAT_COLOR"
        reader.inputs["Name"].default_value = face_attribute("anim_frame_size", face)
        reader.location = (560, -1030 - index * 40)
        links.new(reader.outputs["Attribute"], call_size_selector.inputs[socket_name])

    store_size = nodes.new("GeometryNodeStoreNamedAttribute")
    store_size.data_type = "FLOAT_COLOR"
    store_size.domain = "FACE"
    store_size.inputs["Name"].default_value = MTK_ANIM_FRAME_SIZE
    store_size.location = (2440, 100)
    links.new(store_timing.outputs["Geometry"], store_size.inputs["Geometry"])
    links.new(call_size_selector.outputs["Selected"], store_size.inputs["Value"])

    # --- SUBGROUP: STORE BIOME TINT COLOR (FACE domain) ---
    reader_color = nodes.new("GeometryNodeInputNamedAttribute")
    reader_color.data_type = "FLOAT_COLOR"
    reader_color.inputs["Name"].default_value = MTK_BIOME_TINT_COLOR
    reader_color.location = (2440, -100)

    store_color = nodes.new("GeometryNodeStoreNamedAttribute")
    store_color.data_type = "FLOAT_COLOR"
    store_color.domain = "FACE"
    store_color.inputs["Name"].default_value = MTK_BIOME_TINT_COLOR
    store_color.location = (2620, 100)
    links.new(store_size.outputs["Geometry"], store_color.inputs["Geometry"])
    links.new(reader_color.outputs["Attribute"], store_color.inputs["Value"])

    # --- SUBGROUP: HIDDEN FACE CULLING & VERTEX MERGE ---
    call_culling_merge = nodes.new("GeometryNodeGroup")
    call_culling_merge.node_tree = group_culling_merge
    call_culling_merge.name = "Hidden Face Culling & Merge"
    call_culling_merge.location = (2800, 100)
    links.new(store_color.outputs["Geometry"], call_culling_merge.inputs["Geometry"])
    links.new(group_in.outputs["Geometry"], call_culling_merge.inputs["Point Cloud"])

    # --- SUBGROUP: MATERIAL DISPATCHER ---
    call_mat_dispatcher = nodes.new("GeometryNodeGroup")
    call_mat_dispatcher.node_tree = group_mat_dispatcher
    call_mat_dispatcher.name = "Material Dispatcher"
    call_mat_dispatcher.location = (3020, 100)
    links.new(call_culling_merge.outputs["Geometry"], call_mat_dispatcher.inputs["Geometry"])

    # Final Output
    group_out.location = (3240, 100)
    links.new(call_mat_dispatcher.outputs["Geometry"], group_out.inputs["Geometry"])
    prune_unlinked_nodes(gn_tree)

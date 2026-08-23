"""Procedural 1x1x1 Minecraft Cube geometry generator with Face Normal and Local UV attributes."""

from __future__ import annotations

import bpy
from ..core import ensure_gn_group, ensure_socket, finalize_group
from ...live_sync.constants import CUBE_FACE_NORMAL, LOCAL_FACE_ID, LOCAL_UV

GROUP_NAME_CUBE_SURFACE = "Yefira_Cube_Surface"
CUBE_SURFACE_VERSION = 8


def get_or_create_cube_surface_group() -> bpy.types.GeometryNodeTree:
    """Build a standard 1x1x1 Minecraft cube and attach face normal, local face ID and local UV."""
    tree, needs_build = ensure_gn_group(GROUP_NAME_CUBE_SURFACE, CUBE_SURFACE_VERSION)
    if not needs_build:
        return tree

    ensure_socket(tree, "Geometry", "OUTPUT", "NodeSocketGeometry")
    nodes, links = tree.nodes, tree.links

    # 1. Base Mesh Cube
    cube = nodes.new("GeometryNodeMeshCube")
    cube.inputs["Size"].default_value = (1.0, 1.0, 1.0)
    cube.location = (-650, 0)

    # 2. Store Face Normal on FACE domain
    normal = nodes.new("GeometryNodeInputNormal")
    normal.location = (-650, 250)

    store_normal = nodes.new("GeometryNodeStoreNamedAttribute")
    store_normal.data_type = "FLOAT_VECTOR"
    store_normal.domain = "FACE"
    store_normal.inputs["Name"].default_value = CUBE_FACE_NORMAL
    store_normal.location = (-460, 0)
    links.new(cube.outputs["Mesh"], store_normal.inputs["Geometry"])
    links.new(normal.outputs["Normal"], store_normal.inputs["Value"])

    # 3. Position and Face Normal Deconstruction
    position = nodes.new("GeometryNodeInputPosition")
    position.location = (-650, 480)
    separate_pos = nodes.new("ShaderNodeSeparateXYZ")
    separate_pos.location = (-460, 480)
    links.new(position.outputs["Position"], separate_pos.inputs["Vector"])

    read_face_norm = nodes.new("GeometryNodeInputNamedAttribute")
    read_face_norm.data_type = "FLOAT_VECTOR"
    read_face_norm.inputs["Name"].default_value = CUBE_FACE_NORMAL
    read_face_norm.location = (-650, 250)

    separate_normal = nodes.new("ShaderNodeSeparateXYZ")
    separate_normal.location = (-460, 250)
    links.new(read_face_norm.outputs["Attribute"], separate_normal.inputs["Vector"])

    def compare(axis: str, operation: str, y: float) -> bpy.types.Node:
        node = nodes.new("FunctionNodeCompare")
        node.data_type, node.operation = "FLOAT", operation
        node.inputs["B"].default_value = 0.5 if operation == "GREATER_THAN" else -0.5
        node.location = (-260, y)
        links.new(separate_normal.outputs[axis], node.inputs["A"])
        return node

    top = compare("Z", "GREATER_THAN", 400)
    bottom = compare("Z", "LESS_THAN", 300)
    east = compare("X", "GREATER_THAN", 200)
    west = compare("X", "LESS_THAN", 100)
    north = compare("Y", "GREATER_THAN", 0)

    # LocalFaceID integer mapping:
    # 0: Top (+Z), 1: Bottom (-Z), 2: North (+Y), 3: South (-Y), 4: East (+X), 5: West (-X)
    def make_int_switch(compare_node, false_val: int, true_val: int, x: float, y: float, false_socket=None):
        sw = nodes.new("GeometryNodeSwitch")
        sw.input_type = "INT"
        sw.location = (x, y)
        links.new(compare_node.outputs["Result"], sw.inputs["Switch"])
        if false_socket is not None:
            links.new(false_socket, sw.inputs["False"])
        else:
            sw.inputs["False"].default_value = false_val
        sw.inputs["True"].default_value = true_val
        return sw.outputs["Output"]

    fid_north = make_int_switch(north, 3, 2, -60, -500)
    fid_east = make_int_switch(east, 0, 4, 100, -500, false_socket=fid_north)
    fid_west = make_int_switch(west, 0, 5, 260, -500, false_socket=fid_east)
    fid_bottom = make_int_switch(bottom, 0, 1, 420, -500, false_socket=fid_west)
    fid_final = make_int_switch(top, 0, 0, 580, -500, false_socket=fid_bottom)

    store_face_id = nodes.new("GeometryNodeStoreNamedAttribute")
    store_face_id.data_type, store_face_id.domain = "INT", "FACE"
    store_face_id.inputs["Name"].default_value = LOCAL_FACE_ID
    store_face_id.location = (-260, 0)
    links.new(store_normal.outputs["Geometry"], store_face_id.inputs["Geometry"])
    links.new(fid_final, store_face_id.inputs["Value"])

    def offset(axis: str, operation: str, y: float):
        node = nodes.new("ShaderNodeMath")
        node.operation = operation
        node.location = (-260, y)
        if operation == "ADD":
            node.inputs[1].default_value = 0.5
            links.new(separate_pos.outputs[axis], node.inputs[0])
        else:
            node.inputs[0].default_value = 0.5
            links.new(separate_pos.outputs[axis], node.inputs[1])
        return node.outputs["Value"]

    plus_x, minus_x = offset("X", "ADD", -120), offset("X", "SUBTRACT", -200)
    plus_y, minus_y = offset("Y", "ADD", -280), offset("Y", "SUBTRACT", -360)
    plus_z = offset("Z", "ADD", -440)

    def mix(selector: bpy.types.Node, false_value, true_value, x: float, y: float):
        node = nodes.new("ShaderNodeMix")
        node.data_type, node.location = "FLOAT", (x, y)
        links.new(selector.outputs["Result"], node.inputs[0])
        links.new(false_value, node.inputs[2])
        links.new(true_value, node.inputs[3])
        return node.outputs[0]

    v_side_or_bottom = mix(bottom, plus_z, minus_y, -60, 320)
    local_v = mix(top, v_side_or_bottom, plus_y, 120, 320)

    u_side_or_north = mix(north, plus_x, minus_x, -60, 100)
    u_side_or_west = mix(west, u_side_or_north, minus_y, 120, 100)
    local_u = mix(east, u_side_or_west, plus_y, 300, 100)

    combine = nodes.new("ShaderNodeCombineXYZ")
    combine.location = (480, 200)
    links.new(local_u, combine.inputs["X"])
    links.new(local_v, combine.inputs["Y"])

    store_uv = nodes.new("GeometryNodeStoreNamedAttribute")
    store_uv.data_type, store_uv.domain = "FLOAT_VECTOR", "CORNER"
    store_uv.inputs["Name"].default_value = LOCAL_UV
    store_uv.location = (660, 0)
    links.new(store_face_id.outputs["Geometry"], store_uv.inputs["Geometry"])
    links.new(combine.outputs["Vector"], store_uv.inputs["Value"])

    group_out = nodes.new("NodeGroupOutput")
    group_out.location = (840, 0)
    links.new(store_uv.outputs["Geometry"], group_out.inputs["Geometry"])

    return finalize_group(tree)

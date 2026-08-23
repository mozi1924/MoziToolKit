"""Geometry node group for transparency-aware hidden face culling and vertex merging."""

from __future__ import annotations

import bpy
from ..core import ensure_gn_group, ensure_socket, finalize_group
from ...live_sync.constants import BLOCK_TYPE, MTK_IS_OPAQUE, MTK_MATERIAL_ID

GROUP_NAME_CULLING_MERGE = "Yefira_Culling_And_Merge"
CULLING_MERGE_VERSION = 2


def get_or_create_culling_merge_group() -> bpy.types.GeometryNodeTree:
    """
    Build a reusable node group that culls hidden interior faces and merges coplanar vertices.
    Inputs:
        - Geometry (Geometry): Realized mesh containing faces and attributes.
        - Point Cloud (Geometry): Original point cloud for neighbor spatial queries.
        - Enable Culling (Boolean): Toggle face culling on/off (default: True).
        - Enable Merge (Boolean): Toggle vertex merge on/off (default: True).
        - Merge Distance (Float): Distance threshold for merging (default: 0.0001).
    Outputs:
        - Geometry (Geometry): Optimized mesh with hidden faces removed and vertices merged.
    """
    tree, needs_build = ensure_gn_group(GROUP_NAME_CULLING_MERGE, CULLING_MERGE_VERSION)
    if not needs_build:
        return tree

    ensure_socket(tree, "Geometry", "INPUT", "NodeSocketGeometry")
    ensure_socket(tree, "Point Cloud", "INPUT", "NodeSocketGeometry")
    ensure_socket(tree, "Enable Culling", "INPUT", "NodeSocketBool", default_value=True)
    ensure_socket(tree, "Enable Merge", "INPUT", "NodeSocketBool", default_value=True)
    ensure_socket(tree, "Merge Distance", "INPUT", "NodeSocketFloat", default_value=0.0001)
    ensure_socket(tree, "Geometry", "OUTPUT", "NodeSocketGeometry")

    nodes, links = tree.nodes, tree.links

    # 1. Group Input & Output
    gin = nodes.new("NodeGroupInput")
    gin.location = (-1200, 0)

    gout = nodes.new("NodeGroupOutput")
    gout.location = (1600, 0)

    # 2. Face Center and Normal on Realized Mesh (FACE domain)
    pos = nodes.new("GeometryNodeInputPosition")
    pos.location = (-1000, 300)

    norm = nodes.new("GeometryNodeInputNormal")
    norm.location = (-1000, 150)

    # 3. Calculate Neighbor Center: Position + Normal * 0.5
    scale_norm = nodes.new("ShaderNodeVectorMath")
    scale_norm.operation = "SCALE"
    scale_norm.inputs["Scale"].default_value = 0.5
    scale_norm.location = (-800, 150)
    links.new(norm.outputs["Normal"], scale_norm.inputs[0])

    neigh_pos = nodes.new("ShaderNodeVectorMath")
    neigh_pos.operation = "ADD"
    neigh_pos.location = (-600, 250)
    links.new(pos.outputs["Position"], neigh_pos.inputs[0])
    links.new(scale_norm.outputs["Vector"], neigh_pos.inputs[1])

    # 4. Sample Nearest Point on Point Cloud
    sample_nearest = nodes.new("GeometryNodeSampleNearest")
    sample_nearest.domain = "POINT"
    sample_nearest.location = (-380, 400)
    links.new(gin.outputs["Point Cloud"], sample_nearest.inputs["Geometry"])
    links.new(neigh_pos.outputs["Vector"], sample_nearest.inputs["Sample Position"])

    # 5. Verify distance to sampled point is < 0.1 (confirms neighbor block exists)
    pos_source = nodes.new("GeometryNodeInputPosition")
    pos_source.location = (-380, 200)

    sample_pos = nodes.new("GeometryNodeSampleIndex")
    sample_pos.data_type = "FLOAT_VECTOR"
    sample_pos.domain = "POINT"
    sample_pos.location = (-180, 300)
    links.new(gin.outputs["Point Cloud"], sample_pos.inputs["Geometry"])
    links.new(pos_source.outputs["Position"], sample_pos.inputs["Value"])
    links.new(sample_nearest.outputs["Index"], sample_pos.inputs["Index"])

    dist_node = nodes.new("ShaderNodeVectorMath")
    dist_node.operation = "DISTANCE"
    dist_node.location = (20, 300)
    links.new(neigh_pos.outputs["Vector"], dist_node.inputs[0])
    links.new(sample_pos.outputs["Value"], dist_node.inputs[1])

    cmp_dist = nodes.new("FunctionNodeCompare")
    cmp_dist.data_type = "FLOAT"
    cmp_dist.operation = "LESS_THAN"
    cmp_dist.inputs["B"].default_value = 0.1
    cmp_dist.location = (200, 300)
    links.new(dist_node.outputs["Value"], cmp_dist.inputs["A"])

    # 6. Sample Neighbor Attributes from Point Cloud
    read_type_in = nodes.new("GeometryNodeInputNamedAttribute")
    read_type_in.data_type = "INT"
    read_type_in.inputs["Name"].default_value = BLOCK_TYPE
    read_type_in.location = (-380, 50)

    sample_type = nodes.new("GeometryNodeSampleIndex")
    sample_type.data_type = "INT"
    sample_type.domain = "POINT"
    sample_type.location = (-180, 50)
    links.new(gin.outputs["Point Cloud"], sample_type.inputs["Geometry"])
    links.new(read_type_in.outputs["Attribute"], sample_type.inputs["Value"])
    links.new(sample_nearest.outputs["Index"], sample_type.inputs["Index"])

    cmp_neigh_cube = nodes.new("FunctionNodeCompare")
    cmp_neigh_cube.data_type = "INT"
    cmp_neigh_cube.operation = "EQUAL"
    cmp_neigh_cube.inputs["B"].default_value = 0
    cmp_neigh_cube.location = (200, 50)
    links.new(sample_type.outputs["Value"], cmp_neigh_cube.inputs["A"])

    valid_cube_neigh = nodes.new("FunctionNodeBooleanMath")
    valid_cube_neigh.operation = "AND"
    valid_cube_neigh.location = (400, 200)
    links.new(cmp_dist.outputs["Result"], valid_cube_neigh.inputs[0])
    links.new(cmp_neigh_cube.outputs["Result"], valid_cube_neigh.inputs[1])

    read_op_in = nodes.new("GeometryNodeInputNamedAttribute")
    read_op_in.data_type = "INT"
    read_op_in.inputs["Name"].default_value = MTK_IS_OPAQUE
    read_op_in.location = (-380, -100)

    sample_neigh_op = nodes.new("GeometryNodeSampleIndex")
    sample_neigh_op.data_type = "INT"
    sample_neigh_op.domain = "POINT"
    sample_neigh_op.location = (-180, -100)
    links.new(gin.outputs["Point Cloud"], sample_neigh_op.inputs["Geometry"])
    links.new(read_op_in.outputs["Attribute"], sample_neigh_op.inputs["Value"])
    links.new(sample_nearest.outputs["Index"], sample_neigh_op.inputs["Index"])

    cmp_neigh_op = nodes.new("FunctionNodeCompare")
    cmp_neigh_op.data_type = "INT"
    cmp_neigh_op.operation = "EQUAL"
    cmp_neigh_op.inputs["B"].default_value = 1
    cmp_neigh_op.location = (200, -100)
    links.new(sample_neigh_op.outputs["Value"], cmp_neigh_op.inputs["A"])

    read_mat_in = nodes.new("GeometryNodeInputNamedAttribute")
    read_mat_in.data_type = "INT"
    read_mat_in.inputs["Name"].default_value = MTK_MATERIAL_ID
    read_mat_in.location = (-380, -250)

    sample_neigh_mat = nodes.new("GeometryNodeSampleIndex")
    sample_neigh_mat.data_type = "INT"
    sample_neigh_mat.domain = "POINT"
    sample_neigh_mat.location = (-180, -250)
    links.new(gin.outputs["Point Cloud"], sample_neigh_mat.inputs["Geometry"])
    links.new(read_mat_in.outputs["Attribute"], sample_neigh_mat.inputs["Value"])
    links.new(sample_nearest.outputs["Index"], sample_neigh_mat.inputs["Index"])

    # 7. Read Self Attributes on Realized Mesh Face
    read_self_op = nodes.new("GeometryNodeInputNamedAttribute")
    read_self_op.data_type = "INT"
    read_self_op.inputs["Name"].default_value = MTK_IS_OPAQUE
    read_self_op.location = (-180, -400)

    cmp_self_op = nodes.new("FunctionNodeCompare")
    cmp_self_op.data_type = "INT"
    cmp_self_op.operation = "EQUAL"
    cmp_self_op.inputs["B"].default_value = 1
    cmp_self_op.location = (200, -400)
    links.new(read_self_op.outputs["Attribute"], cmp_self_op.inputs["A"])

    read_self_mat = nodes.new("GeometryNodeInputNamedAttribute")
    read_self_mat.data_type = "INT"
    read_self_mat.inputs["Name"].default_value = MTK_MATERIAL_ID
    read_self_mat.location = (-180, -550)

    cmp_same_mat = nodes.new("FunctionNodeCompare")
    cmp_same_mat.data_type = "INT"
    cmp_same_mat.operation = "EQUAL"
    cmp_same_mat.location = (200, -550)
    links.new(read_self_mat.outputs["Attribute"], cmp_same_mat.inputs["A"])
    links.new(sample_neigh_mat.outputs["Value"], cmp_same_mat.inputs["B"])

    # 8. Culling Rules
    cull_when_opaque = nodes.new("FunctionNodeBooleanMath")
    cull_when_opaque.operation = "AND"
    cull_when_opaque.location = (400, -250)
    links.new(cmp_self_op.outputs["Result"], cull_when_opaque.inputs[0])
    links.new(cmp_neigh_op.outputs["Result"], cull_when_opaque.inputs[1])

    self_not_op = nodes.new("FunctionNodeBooleanMath")
    self_not_op.operation = "NOT"
    self_not_op.location = (400, -400)
    links.new(cmp_self_op.outputs["Result"], self_not_op.inputs[0])

    neigh_op_or_same = nodes.new("FunctionNodeBooleanMath")
    neigh_op_or_same.operation = "OR"
    neigh_op_or_same.location = (400, -550)
    links.new(cmp_neigh_op.outputs["Result"], neigh_op_or_same.inputs[0])
    links.new(cmp_same_mat.outputs["Result"], neigh_op_or_same.inputs[1])

    cull_when_transp = nodes.new("FunctionNodeBooleanMath")
    cull_when_transp.operation = "AND"
    cull_when_transp.location = (600, -450)
    links.new(self_not_op.outputs["Boolean"], cull_when_transp.inputs[0])
    links.new(neigh_op_or_same.outputs["Boolean"], cull_when_transp.inputs[1])

    cull_rule = nodes.new("FunctionNodeBooleanMath")
    cull_rule.operation = "OR"
    cull_rule.location = (800, -350)
    links.new(cull_when_opaque.outputs["Boolean"], cull_rule.inputs[0])
    links.new(cull_when_transp.outputs["Boolean"], cull_rule.inputs[1])

    cull_selection = nodes.new("FunctionNodeBooleanMath")
    cull_selection.operation = "AND"
    cull_selection.location = (1000, -100)
    links.new(valid_cube_neigh.outputs["Boolean"], cull_selection.inputs[0])
    links.new(cull_rule.outputs["Boolean"], cull_selection.inputs[1])

    final_cull = nodes.new("FunctionNodeBooleanMath")
    final_cull.operation = "AND"
    final_cull.location = (1200, 0)
    links.new(gin.outputs["Enable Culling"], final_cull.inputs[0])
    links.new(cull_selection.outputs["Boolean"], final_cull.inputs[1])

    # 9. Delete Geometry (FACE domain)
    del_geo = nodes.new("GeometryNodeDeleteGeometry")
    del_geo.domain = "FACE"
    del_geo.location = (1200, 200)
    links.new(gin.outputs["Geometry"], del_geo.inputs["Geometry"])
    links.new(final_cull.outputs["Boolean"], del_geo.inputs["Selection"])

    # 10. Merge by Distance
    mbd = nodes.new("GeometryNodeMergeByDistance")
    mbd.location = (1400, 200)
    links.new(del_geo.outputs["Geometry"], mbd.inputs["Geometry"])
    links.new(gin.outputs["Enable Merge"], mbd.inputs["Selection"])
    links.new(gin.outputs["Merge Distance"], mbd.inputs["Distance"])

    # 11. Final Output
    links.new(mbd.outputs["Geometry"], gout.inputs["Geometry"])

    tree["mozi_role"] = "culling_merge"
    return finalize_group(tree)

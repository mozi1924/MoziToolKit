"""Calculates UVMap coordinate in non-square Atlas texture space from Local UV and Tile coordinate."""

from __future__ import annotations

import bpy
from ..core import ensure_gn_group, ensure_socket, finalize_group

GROUP_NAME_ATLAS_UV_CALCULATOR = "Yefira_Atlas_UV_Calculator"
ATLAS_UV_CALCULATOR_VERSION = 3


def get_or_create_atlas_uv_calculator_group() -> bpy.types.GeometryNodeTree:
    """
    Reusable node group: Calculates UVMap coordinate in Atlas space from LocalUV and Tile Col/Row,
    supporting both static grid chunks and horizontal multi-column animation chunks.
    """
    tree, needs_build = ensure_gn_group(GROUP_NAME_ATLAS_UV_CALCULATOR, ATLAS_UV_CALCULATOR_VERSION)
    if not needs_build:
        return tree

    ensure_socket(tree, "Target Tile", "INPUT", "NodeSocketVector")
    ensure_socket(tree, "Local UV", "INPUT", "NodeSocketVector")
    ensure_socket(tree, "Chunk ID", "INPUT", "NodeSocketInt", default_value=0)
    ensure_socket(tree, "Tiles Per Row", "INPUT", "NodeSocketFloat", default_value=256.0)
    ensure_socket(tree, "Tile Size", "INPUT", "NodeSocketFloat", default_value=16.0)
    ensure_socket(tree, "Atlas Height", "INPUT", "NodeSocketFloat", default_value=80.0)
    ensure_socket(tree, "Anim Atlas Width", "INPUT", "NodeSocketFloat", default_value=896.0)
    ensure_socket(tree, "Anim Atlas Height", "INPUT", "NodeSocketFloat", default_value=1024.0)
    ensure_socket(tree, "Anim Frame Width", "INPUT", "NodeSocketFloat", default_value=16.0)
    ensure_socket(tree, "Anim Frame Height", "INPUT", "NodeSocketFloat", default_value=16.0)
    ensure_socket(tree, "Atlas UV", "OUTPUT", "NodeSocketVector")

    nodes, links = tree.nodes, tree.links
    gin = nodes.new("NodeGroupInput")
    gin.location = (-650, 0)
    gout = nodes.new("NodeGroupOutput")
    gout.location = (900, 20)

    sep_target = nodes.new("ShaderNodeSeparateXYZ")
    sep_target.location = (-450, 180)
    links.new(gin.outputs["Target Tile"], sep_target.inputs["Vector"])

    sep_local = nodes.new("ShaderNodeSeparateXYZ")
    sep_local.location = (-450, -120)
    links.new(gin.outputs["Local UV"], sep_local.inputs["Vector"])

    # --- 1. STATIC UV CALCULATION ---
    step_u = nodes.new("ShaderNodeMath")
    step_u.operation = "DIVIDE"
    step_u.inputs[0].default_value = 1.0
    step_u.location = (-250, 300)
    links.new(gin.outputs["Tiles Per Row"], step_u.inputs[1])

    step_v = nodes.new("ShaderNodeMath")
    step_v.operation = "DIVIDE"
    step_v.location = (-250, -250)
    links.new(gin.outputs["Tile Size"], step_v.inputs[0])
    links.new(gin.outputs["Atlas Height"], step_v.inputs[1])

    col_plus_u = nodes.new("ShaderNodeMath")
    col_plus_u.operation = "ADD"
    col_plus_u.location = (-250, 180)
    links.new(sep_target.outputs["X"], col_plus_u.inputs[0])
    links.new(sep_local.outputs["X"], col_plus_u.inputs[1])

    atlas_u_static = nodes.new("ShaderNodeMath")
    atlas_u_static.operation = "MULTIPLY"
    atlas_u_static.location = (-50, 200)
    links.new(col_plus_u.outputs["Value"], atlas_u_static.inputs[0])
    links.new(step_u.outputs["Value"], atlas_u_static.inputs[1])

    inv_v = nodes.new("ShaderNodeMath")
    inv_v.operation = "SUBTRACT"
    inv_v.inputs[0].default_value = 1.0
    inv_v.location = (-250, -120)
    links.new(sep_local.outputs["Y"], inv_v.inputs[1])

    row_plus_inv_v = nodes.new("ShaderNodeMath")
    row_plus_inv_v.operation = "ADD"
    row_plus_inv_v.location = (-50, -120)
    links.new(sep_target.outputs["Y"], row_plus_inv_v.inputs[0])
    links.new(inv_v.outputs["Value"], row_plus_inv_v.inputs[1])

    v_scaled = nodes.new("ShaderNodeMath")
    v_scaled.operation = "MULTIPLY"
    v_scaled.location = (120, -120)
    links.new(row_plus_inv_v.outputs["Value"], v_scaled.inputs[0])
    links.new(step_v.outputs["Value"], v_scaled.inputs[1])

    atlas_v_static = nodes.new("ShaderNodeMath")
    atlas_v_static.operation = "SUBTRACT"
    atlas_v_static.inputs[0].default_value = 1.0
    atlas_v_static.location = (280, -120)
    links.new(v_scaled.outputs["Value"], atlas_v_static.inputs[1])

    comb_static = nodes.new("ShaderNodeCombineXYZ")
    comb_static.location = (450, 100)
    links.new(atlas_u_static.outputs["Value"], comb_static.inputs["X"])
    links.new(atlas_v_static.outputs["Value"], comb_static.inputs["Y"])

    # --- 2. ANIMATION UV CALCULATION ---
    col_px = nodes.new("ShaderNodeMath")
    col_px.operation = "MULTIPLY"
    col_px.location = (-250, 20)
    links.new(sep_target.outputs["X"], col_px.inputs[0])
    links.new(gin.outputs["Anim Frame Width"], col_px.inputs[1])

    u_px = nodes.new("ShaderNodeMath")
    u_px.operation = "MULTIPLY"
    u_px.location = (-250, -40)
    links.new(sep_local.outputs["X"], u_px.inputs[0])
    links.new(gin.outputs["Anim Frame Width"], u_px.inputs[1])

    total_px = nodes.new("ShaderNodeMath")
    total_px.operation = "ADD"
    total_px.location = (-50, 0)
    links.new(col_px.outputs["Value"], total_px.inputs[0])
    links.new(u_px.outputs["Value"], total_px.inputs[1])

    atlas_u_anim = nodes.new("ShaderNodeMath")
    atlas_u_anim.operation = "DIVIDE"
    atlas_u_anim.location = (120, 0)
    links.new(total_px.outputs["Value"], atlas_u_anim.inputs[0])
    links.new(gin.outputs["Anim Atlas Width"], atlas_u_anim.inputs[1])

    inv_v_fh = nodes.new("ShaderNodeMath")
    inv_v_fh.operation = "MULTIPLY"
    inv_v_fh.location = (-50, -300)
    links.new(inv_v.outputs["Value"], inv_v_fh.inputs[0])
    links.new(gin.outputs["Anim Frame Height"], inv_v_fh.inputs[1])

    v_anim_ratio = nodes.new("ShaderNodeMath")
    v_anim_ratio.operation = "DIVIDE"
    v_anim_ratio.location = (120, -300)
    links.new(inv_v_fh.outputs["Value"], v_anim_ratio.inputs[0])
    links.new(gin.outputs["Anim Atlas Height"], v_anim_ratio.inputs[1])

    atlas_v_anim = nodes.new("ShaderNodeMath")
    atlas_v_anim.operation = "SUBTRACT"
    atlas_v_anim.inputs[0].default_value = 1.0
    atlas_v_anim.location = (280, -300)
    links.new(v_anim_ratio.outputs["Value"], atlas_v_anim.inputs[1])

    comb_anim = nodes.new("ShaderNodeCombineXYZ")
    comb_anim.location = (450, -100)
    links.new(atlas_u_anim.outputs["Value"], comb_anim.inputs["X"])
    links.new(atlas_v_anim.outputs["Value"], comb_anim.inputs["Y"])

    # --- 3. CHUNK SWITCH ---
    cmp_is_anim = nodes.new("FunctionNodeCompare")
    cmp_is_anim.data_type = "INT"
    cmp_is_anim.operation = "GREATER_THAN"
    cmp_is_anim.inputs["B"].default_value = 0
    cmp_is_anim.location = (450, 300)
    links.new(gin.outputs["Chunk ID"], cmp_is_anim.inputs["A"])

    sw_chunk = nodes.new("GeometryNodeSwitch")
    sw_chunk.input_type = "VECTOR"
    sw_chunk.location = (680, 20)
    links.new(cmp_is_anim.outputs["Result"], sw_chunk.inputs["Switch"])
    links.new(comb_static.outputs["Vector"], sw_chunk.inputs["False"])
    links.new(comb_anim.outputs["Vector"], sw_chunk.inputs["True"])

    links.new(sw_chunk.outputs["Output"], gout.inputs["Atlas UV"])
    return finalize_group(tree)

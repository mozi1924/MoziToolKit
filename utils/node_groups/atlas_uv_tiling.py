"""Shader node group for Atlas UV Self-Tiling (Legacy / Standalone Fallback).

Retained for backward compatibility and specialized shader use cases.
Modern MoziToolKit pipelines bake UV rotation, 16x16 sampling windows, and
affine transformations directly into vertex/loop geometry UV coordinates,
achieving zero runtime shader overhead and saving mesh attribute slots under EEVEE.
"""


from __future__ import annotations

import bpy

from .core import add_sockets, ensure_group, finalize_group, link, node


ATLAS_UV_TILING_VERSION = 3


def ensure_atlas_uv_tiling() -> bpy.types.NodeTree:
    """Create or return the reusable MC_Atlas_UV_Tiling node group."""
    tree = ensure_group("MC_Atlas_UV_Tiling", ATLAS_UV_TILING_VERSION)
    if tree.nodes and tree.get("mozi_template_complete"):
        return tree

    add_sockets(tree, (
        ("Vector", "INPUT", "NodeSocketVector", None),
        ("Scale", "INPUT", "NodeSocketVector", (1.0, 1.0, 1.0)),
        ("Location", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0)),
        ("Rotation", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0)),
        ("Mapped Vector", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0)),
        ("Use External Vector", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0),
        ("Atlas Width", "INPUT", "NodeSocketFloat", 4096.0, 1.0, 65536.0),
        ("Atlas Height", "INPUT", "NodeSocketFloat", 80.0, 1.0, 65536.0),
        ("Tile Width", "INPUT", "NodeSocketFloat", 16.0, 1.0, 16384.0),
        ("Tile Height", "INPUT", "NodeSocketFloat", 16.0, 1.0, 16384.0),
        ("Atlas UV", "OUTPUT", "NodeSocketVector", None),
        ("Local UV", "OUTPUT", "NodeSocketVector", None),
    ))

    nodes, links = tree.nodes, tree.links
    group_in = node(nodes, "NodeGroupInput", "Group Input", location=(-1400, 0))
    group_out = node(nodes, "NodeGroupOutput", "Group Output", location=(2400, 0))

    # 1. Normalized step size per tile in UV space
    step_u = node(nodes, "ShaderNodeMath", "Step U", location=(-1200, 200), properties={"operation": "DIVIDE"})
    step_v = node(nodes, "ShaderNodeMath", "Step V", location=(-1200, 50), properties={"operation": "DIVIDE"})
    link(links, group_in, "Tile Width", step_u, "Value[0]")
    link(links, group_in, "Atlas Width", step_u, "Value[1]")
    link(links, group_in, "Tile Height", step_v, "Value[0]")
    link(links, group_in, "Atlas Height", step_v, "Value[1]")

    # Grid columns and rows count
    max_cols = node(nodes, "ShaderNodeMath", "Max Cols", location=(-1200, 350), properties={"operation": "DIVIDE"})
    link(links, group_in, "Atlas Width", max_cols, "Value[0]")
    link(links, group_in, "Tile Width", max_cols, "Value[1]")
    max_cols_m1 = node(nodes, "ShaderNodeMath", "Max Cols Minus 1", location=(-1000, 350), properties={"operation": "SUBTRACT"}, inputs={"Value[1]": 1.0})
    link(links, max_cols, "Value", max_cols_m1, "Value[0]")

    max_rows = node(nodes, "ShaderNodeMath", "Max Rows", location=(-1200, -350), properties={"operation": "DIVIDE"})
    link(links, group_in, "Atlas Height", max_rows, "Value[0]")
    link(links, group_in, "Tile Height", max_rows, "Value[1]")
    max_rows_m1 = node(nodes, "ShaderNodeMath", "Max Rows Minus 1", location=(-1000, -350), properties={"operation": "SUBTRACT"}, inputs={"Value[1]": 1.0})
    link(links, max_rows, "Value", max_rows_m1, "Value[0]")

    # 2. Separate incoming baked Atlas UV
    sep_baked = node(nodes, "ShaderNodeSeparateXYZ", "Separate Baked UV", location=(-1200, -150))
    link(links, group_in, "Vector", sep_baked, "Vector")

    # 3. Identify Atlas Cell Bounds (Cell Min U, Min V) with boundary clamping
    u_div_step = node(nodes, "ShaderNodeMath", "U / Step U", location=(-1000, 200), properties={"operation": "DIVIDE"})
    link(links, sep_baked, "X", u_div_step, "Value[0]")
    link(links, step_u, "Value", u_div_step, "Value[1]")

    col_floor = node(nodes, "ShaderNodeMath", "Col Index Unclamped", location=(-820, 200), properties={"operation": "FLOOR"})
    link(links, u_div_step, "Value", col_floor, "Value[0]")

    col_clamp_max = node(nodes, "ShaderNodeMath", "Col Index Max Clamp", location=(-660, 250), properties={"operation": "MINIMUM"})
    link(links, col_floor, "Value", col_clamp_max, "Value[0]")
    link(links, max_cols_m1, "Value", col_clamp_max, "Value[1]")

    col_idx = node(nodes, "ShaderNodeMath", "Col Index", location=(-500, 250), properties={"operation": "MAXIMUM"}, inputs={"Value[1]": 0.0})
    link(links, col_clamp_max, "Value", col_idx, "Value[0]")

    cell_min_u = node(nodes, "ShaderNodeMath", "Cell Min U", location=(-340, 250), properties={"operation": "MULTIPLY"})
    link(links, col_idx, "Value", cell_min_u, "Value[0]")
    link(links, step_u, "Value", cell_min_u, "Value[1]")

    v_div_step = node(nodes, "ShaderNodeMath", "V / Step V", location=(-1000, 50), properties={"operation": "DIVIDE"})
    link(links, sep_baked, "Y", v_div_step, "Value[0]")
    link(links, step_v, "Value", v_div_step, "Value[1]")

    row_floor = node(nodes, "ShaderNodeMath", "Row Index Unclamped", location=(-820, 50), properties={"operation": "FLOOR"})
    link(links, v_div_step, "Value", row_floor, "Value[0]")

    row_clamp_max = node(nodes, "ShaderNodeMath", "Row Index Max Clamp", location=(-660, 50), properties={"operation": "MINIMUM"})
    link(links, row_floor, "Value", row_clamp_max, "Value[0]")
    link(links, max_rows_m1, "Value", row_clamp_max, "Value[1]")

    row_idx = node(nodes, "ShaderNodeMath", "Row Index", location=(-500, 50), properties={"operation": "MAXIMUM"}, inputs={"Value[1]": 0.0})
    link(links, row_clamp_max, "Value", row_idx, "Value[0]")

    cell_min_v = node(nodes, "ShaderNodeMath", "Cell Min V", location=(-340, 50), properties={"operation": "MULTIPLY"})
    link(links, row_idx, "Value", cell_min_v, "Value[0]")
    link(links, step_v, "Value", cell_min_v, "Value[1]")

    # 4. Normalized Continuous Local UV [0, 1] inside the cell
    u_sub_min = node(nodes, "ShaderNodeMath", "U - Cell Min U", location=(-180, 250), properties={"operation": "SUBTRACT"})
    link(links, sep_baked, "X", u_sub_min, "Value[0]")
    link(links, cell_min_u, "Value", u_sub_min, "Value[1]")
    local_u = node(nodes, "ShaderNodeMath", "Local U", location=(-20, 250), properties={"operation": "DIVIDE"})
    link(links, u_sub_min, "Value", local_u, "Value[0]")
    link(links, step_u, "Value", local_u, "Value[1]")

    v_sub_min = node(nodes, "ShaderNodeMath", "V - Cell Min V", location=(-180, 50), properties={"operation": "SUBTRACT"})
    link(links, sep_baked, "Y", v_sub_min, "Value[0]")
    link(links, cell_min_v, "Value", v_sub_min, "Value[1]")
    local_v = node(nodes, "ShaderNodeMath", "Local V", location=(-20, 50), properties={"operation": "DIVIDE"})
    link(links, v_sub_min, "Value", local_v, "Value[0]")
    link(links, step_v, "Value", local_v, "Value[1]")

    comb_local = node(nodes, "ShaderNodeCombineXYZ", "Combine Local UV", location=(140, 150))
    link(links, local_u, "Value", comb_local, "X")
    link(links, local_v, "Value", comb_local, "Y")
    link(links, comb_local, "Vector", group_out, "Local UV")

    # 5. Shift Origin to UV Center (0.5, 0.5) for Center-based Scaling & Rotation
    sub_center = node(
        nodes,
        "ShaderNodeVectorMath",
        "Subtract Center (0.5)",
        location=(300, 150),
        properties={"operation": "SUBTRACT"},
        inputs={"Vector[1]": (0.5, 0.5, 0.0)},
    )
    link(links, comb_local, "Vector", sub_center, "Vector[0]")

    # 6. Internal Mapping Node (operating centered at (0, 0))
    mapping = node(nodes, "ShaderNodeMapping", "Internal Mapping", location=(480, 150), properties={"vector_type": "POINT"})
    link(links, sub_center, "Vector", mapping, "Vector")
    link(links, group_in, "Location", mapping, "Location")
    link(links, group_in, "Rotation", mapping, "Rotation")
    link(links, group_in, "Scale", mapping, "Scale")

    # 7. Shift Back from Center (+0.5)
    add_center = node(
        nodes,
        "ShaderNodeVectorMath",
        "Add Center (0.5)",
        location=(660, 150),
        properties={"operation": "ADD"},
        inputs={"Vector[1]": (0.5, 0.5, 0.0)},
    )
    link(links, mapping, "Vector", add_center, "Vector[0]")

    # 8. Mix between Internal Mapping Vector and External Mapped Vector
    mix_vec = node(nodes, "ShaderNodeMix", "Choose Mapping Vector", location=(840, 150), properties={"data_type": "VECTOR"})
    link(links, group_in, "Use External Vector", mix_vec, "Factor")
    link(links, add_center, "Vector", mix_vec, "A[1]")  # Vector A socket
    link(links, group_in, "Mapped Vector", mix_vec, "B[1]")  # Vector B socket

    # 9. Separate Transformed Local Coordinates
    sep_trans = node(nodes, "ShaderNodeSeparateXYZ", "Separate Transformed Vector", location=(1020, 150))
    link(links, mix_vec, "Result[1]", sep_trans, "Vector")  # Vector Result socket

    # 10. Wrap Local UV within [0, 1) using FRACT
    wrap_u = node(nodes, "ShaderNodeMath", "Wrap Local U", location=(1200, 200), properties={"operation": "FRACT"})
    wrap_v = node(nodes, "ShaderNodeMath", "Wrap Local V", location=(1200, 50), properties={"operation": "FRACT"})
    link(links, sep_trans, "X", wrap_u, "Value[0]")
    link(links, sep_trans, "Y", wrap_v, "Value[0]")

    # 11. Project wrapped local coordinates back to Atlas UV space
    wrap_u_scaled = node(nodes, "ShaderNodeMath", "Scaled Wrap U", location=(1380, 200), properties={"operation": "MULTIPLY"})
    link(links, wrap_u, "Value", wrap_u_scaled, "Value[0]")
    link(links, step_u, "Value", wrap_u_scaled, "Value[1]")

    raw_atlas_u = node(nodes, "ShaderNodeMath", "Raw Atlas U", location=(1540, 200), properties={"operation": "ADD"})
    link(links, cell_min_u, "Value", raw_atlas_u, "Value[0]")
    link(links, wrap_u_scaled, "Value", raw_atlas_u, "Value[1]")

    wrap_v_scaled = node(nodes, "ShaderNodeMath", "Scaled Wrap V", location=(1380, 50), properties={"operation": "MULTIPLY"})
    link(links, wrap_v, "Value", wrap_v_scaled, "Value[0]")
    link(links, step_v, "Value", wrap_v_scaled, "Value[1]")

    raw_atlas_v = node(nodes, "ShaderNodeMath", "Raw Atlas V", location=(1540, 50), properties={"operation": "ADD"})
    link(links, cell_min_v, "Value", raw_atlas_v, "Value[0]")
    link(links, wrap_v_scaled, "Value", raw_atlas_v, "Value[1]")

    # Cell bounds clamping
    cell_max_u = node(nodes, "ShaderNodeMath", "Cell Max U", location=(1540, 320), properties={"operation": "ADD"})
    link(links, cell_min_u, "Value", cell_max_u, "Value[0]")
    link(links, step_u, "Value", cell_max_u, "Value[1]")

    clamp_u_min = node(nodes, "ShaderNodeMath", "Clamp Atlas U Min", location=(1700, 200), properties={"operation": "MAXIMUM"})
    link(links, raw_atlas_u, "Value", clamp_u_min, "Value[0]")
    link(links, cell_min_u, "Value", clamp_u_min, "Value[1]")

    final_atlas_u = node(nodes, "ShaderNodeMath", "Final Atlas U", location=(1860, 200), properties={"operation": "MINIMUM"})
    link(links, clamp_u_min, "Value", final_atlas_u, "Value[0]")
    link(links, cell_max_u, "Value", final_atlas_u, "Value[1]")

    cell_max_v = node(nodes, "ShaderNodeMath", "Cell Max V", location=(1540, -70), properties={"operation": "ADD"})
    link(links, cell_min_v, "Value", cell_max_v, "Value[0]")
    link(links, step_v, "Value", cell_max_v, "Value[1]")

    clamp_v_min = node(nodes, "ShaderNodeMath", "Clamp Atlas V Min", location=(1700, 50), properties={"operation": "MAXIMUM"})
    link(links, raw_atlas_v, "Value", clamp_v_min, "Value[0]")
    link(links, cell_min_v, "Value", clamp_v_min, "Value[1]")

    final_atlas_v = node(nodes, "ShaderNodeMath", "Final Atlas V", location=(1860, 50), properties={"operation": "MINIMUM"})
    link(links, clamp_v_min, "Value", final_atlas_v, "Value[0]")
    link(links, cell_max_v, "Value", final_atlas_v, "Value[1]")

    comb_atlas = node(nodes, "ShaderNodeCombineXYZ", "Combine Atlas UV", location=(2020, 100))
    link(links, final_atlas_u, "Value", comb_atlas, "X")
    link(links, final_atlas_v, "Value", comb_atlas, "Y")

    # 12. Bypass Check: If transform is identity, bypass directly to input Vector
    diff_scale = node(
        nodes,
        "ShaderNodeVectorMath",
        "Scale Diff",
        location=(1400, -200),
        properties={"operation": "SUBTRACT"},
        inputs={"Vector[1]": (1.0, 1.0, 1.0)},
    )
    link(links, group_in, "Scale", diff_scale, "Vector[0]")

    len_scale = node(nodes, "ShaderNodeVectorMath", "Scale Diff Len", location=(1560, -200), properties={"operation": "LENGTH"})
    link(links, diff_scale, "Vector", len_scale, "Vector")

    len_loc = node(nodes, "ShaderNodeVectorMath", "Location Len", location=(1560, -320), properties={"operation": "LENGTH"})
    link(links, group_in, "Location", len_loc, "Vector")

    len_rot = node(nodes, "ShaderNodeVectorMath", "Rotation Len", location=(1560, -440), properties={"operation": "LENGTH"})
    link(links, group_in, "Rotation", len_rot, "Vector")

    sum_sl = node(nodes, "ShaderNodeMath", "Sum Scale Loc", location=(1720, -260), properties={"operation": "ADD"})
    link(links, len_scale, "Value", sum_sl, "Value[0]")
    link(links, len_loc, "Value", sum_sl, "Value[1]")

    sum_re = node(nodes, "ShaderNodeMath", "Sum Rot Ext", location=(1720, -380), properties={"operation": "ADD"})
    link(links, len_rot, "Value", sum_re, "Value[0]")
    link(links, group_in, "Use External Vector", sum_re, "Value[1]")

    total_activity = node(nodes, "ShaderNodeMath", "Total Activity", location=(1880, -320), properties={"operation": "ADD"})
    link(links, sum_sl, "Value", total_activity, "Value[0]")
    link(links, sum_re, "Value", total_activity, "Value[1]")

    is_transform_active = node(nodes, "ShaderNodeMath", "Is Transform Active", location=(2040, -320), properties={"operation": "GREATER_THAN"}, inputs={"Value[1]": 0.0001})
    link(links, total_activity, "Value", is_transform_active, "Value[0]")

    bypass_mix = node(nodes, "ShaderNodeMix", "Bypass Mix", location=(2220, 0), properties={"data_type": "VECTOR"})
    link(links, is_transform_active, "Value", bypass_mix, "Factor")
    link(links, group_in, "Vector", bypass_mix, "A[1]")
    link(links, comb_atlas, "Vector", bypass_mix, "B[1]")

    # 13. Output Final Atlas UV
    link(links, bypass_mix, "Result[1]", group_out, "Atlas UV")

    return finalize_group(tree)

"""Shader node group for Atlas UV Self-Tiling (Legacy / Standalone Fallback).

Retained for backward compatibility and specialized shader use cases.
Modern MoziToolKit pipelines bake UV rotation, 16x16 sampling windows, and
affine transformations directly into vertex/loop geometry UV coordinates,
achieving zero runtime shader overhead and saving mesh attribute slots under EEVEE.
"""


from __future__ import annotations

import bpy

from .core import add_sockets, ensure_group, finalize_group, link, node


ATLAS_UV_TILING_VERSION = 2


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
    group_out = node(nodes, "NodeGroupOutput", "Group Output", location=(1600, 0))

    # 1. Normalized step size per tile in UV space
    step_u = node(nodes, "ShaderNodeMath", "Step U", location=(-1200, 200), properties={"operation": "DIVIDE"})
    step_v = node(nodes, "ShaderNodeMath", "Step V", location=(-1200, 50), properties={"operation": "DIVIDE"})
    link(links, group_in, "Tile Width", step_u, "Value[0]")
    link(links, group_in, "Atlas Width", step_u, "Value[1]")
    link(links, group_in, "Tile Height", step_v, "Value[0]")
    link(links, group_in, "Atlas Height", step_v, "Value[1]")

    # 2. Separate incoming baked Atlas UV
    sep_baked = node(nodes, "ShaderNodeSeparateXYZ", "Separate Baked UV", location=(-1200, -150))
    link(links, group_in, "Vector", sep_baked, "Vector")

    # 3. Identify Atlas Cell Bounds (Cell Min U, Min V)
    u_div_step = node(nodes, "ShaderNodeMath", "U / Step U", location=(-1000, 200), properties={"operation": "DIVIDE"})
    link(links, sep_baked, "X", u_div_step, "Value[0]")
    link(links, step_u, "Value", u_div_step, "Value[1]")

    col_idx = node(nodes, "ShaderNodeMath", "Col Index", location=(-820, 200), properties={"operation": "FLOOR"})
    link(links, u_div_step, "Value", col_idx, "Value[0]")

    cell_min_u = node(nodes, "ShaderNodeMath", "Cell Min U", location=(-640, 200), properties={"operation": "MULTIPLY"})
    link(links, col_idx, "Value", cell_min_u, "Value[0]")
    link(links, step_u, "Value", cell_min_u, "Value[1]")

    v_div_step = node(nodes, "ShaderNodeMath", "V / Step V", location=(-1000, 50), properties={"operation": "DIVIDE"})
    link(links, sep_baked, "Y", v_div_step, "Value[0]")
    link(links, step_v, "Value", v_div_step, "Value[1]")

    row_idx = node(nodes, "ShaderNodeMath", "Row Index", location=(-820, 50), properties={"operation": "FLOOR"})
    link(links, v_div_step, "Value", row_idx, "Value[0]")

    cell_min_v = node(nodes, "ShaderNodeMath", "Cell Min V", location=(-640, 50), properties={"operation": "MULTIPLY"})
    link(links, row_idx, "Value", cell_min_v, "Value[0]")
    link(links, step_v, "Value", cell_min_v, "Value[1]")

    # 4. Normalized Local UV [0, 1) inside the cell
    local_u = node(nodes, "ShaderNodeMath", "Local U", location=(-820, -150), properties={"operation": "FRACT"})
    local_v = node(nodes, "ShaderNodeMath", "Local V", location=(-820, -300), properties={"operation": "FRACT"})
    link(links, u_div_step, "Value", local_u, "Value[0]")
    link(links, v_div_step, "Value", local_v, "Value[0]")

    comb_local = node(nodes, "ShaderNodeCombineXYZ", "Combine Local UV", location=(-640, -200))
    link(links, local_u, "Value", comb_local, "X")
    link(links, local_v, "Value", comb_local, "Y")
    link(links, comb_local, "Vector", group_out, "Local UV")

    # 5. Shift Origin to UV Center (0.5, 0.5) for Center-based Scaling & Rotation
    sub_center = node(
        nodes,
        "ShaderNodeVectorMath",
        "Subtract Center (0.5)",
        location=(-460, -200),
        properties={"operation": "SUBTRACT"},
        inputs={"Vector[1]": (0.5, 0.5, 0.0)},
    )
    link(links, comb_local, "Vector", sub_center, "Vector[0]")

    # 6. Internal Mapping Node (operating centered at (0, 0))
    mapping = node(nodes, "ShaderNodeMapping", "Internal Mapping", location=(-260, -200), properties={"vector_type": "POINT"})
    link(links, sub_center, "Vector", mapping, "Vector")
    link(links, group_in, "Location", mapping, "Location")
    link(links, group_in, "Rotation", mapping, "Rotation")
    link(links, group_in, "Scale", mapping, "Scale")

    # 7. Shift Back from Center (+0.5)
    add_center = node(
        nodes,
        "ShaderNodeVectorMath",
        "Add Center (0.5)",
        location=(-60, -200),
        properties={"operation": "ADD"},
        inputs={"Vector[1]": (0.5, 0.5, 0.0)},
    )
    link(links, mapping, "Vector", add_center, "Vector[0]")

    # 8. Mix between Internal Mapping Vector and External Mapped Vector
    mix_vec = node(nodes, "ShaderNodeMix", "Choose Mapping Vector", location=(160, -200), properties={"data_type": "VECTOR"})
    link(links, group_in, "Use External Vector", mix_vec, "Factor")
    link(links, add_center, "Vector", mix_vec, "A[1]")  # Vector A socket
    link(links, group_in, "Mapped Vector", mix_vec, "B[1]")  # Vector B socket

    # 9. Separate Transformed Local Coordinates
    sep_trans = node(nodes, "ShaderNodeSeparateXYZ", "Separate Transformed Vector", location=(360, -200))
    link(links, mix_vec, "Result[1]", sep_trans, "Vector")  # Vector Result socket

    # 10. Wrap Local UV within [0, 1) using FRACT
    wrap_u = node(nodes, "ShaderNodeMath", "Wrap Local U", location=(560, -100), properties={"operation": "FRACT"})
    wrap_v = node(nodes, "ShaderNodeMath", "Wrap Local V", location=(560, -250), properties={"operation": "FRACT"})
    link(links, sep_trans, "X", wrap_u, "Value[0]")
    link(links, sep_trans, "Y", wrap_v, "Value[0]")

    # 11. Project wrapped local coordinates back to Atlas UV space
    wrap_u_scaled = node(nodes, "ShaderNodeMath", "Scaled Wrap U", location=(760, 100), properties={"operation": "MULTIPLY"})
    link(links, wrap_u, "Value", wrap_u_scaled, "Value[0]")
    link(links, step_u, "Value", wrap_u_scaled, "Value[1]")

    final_atlas_u = node(nodes, "ShaderNodeMath", "Final Atlas U", location=(960, 100), properties={"operation": "ADD"})
    link(links, cell_min_u, "Value", final_atlas_u, "Value[0]")
    link(links, wrap_u_scaled, "Value", final_atlas_u, "Value[1]")

    wrap_v_scaled = node(nodes, "ShaderNodeMath", "Scaled Wrap V", location=(760, -50), properties={"operation": "MULTIPLY"})
    link(links, wrap_v, "Value", wrap_v_scaled, "Value[0]")
    link(links, step_v, "Value", wrap_v_scaled, "Value[1]")

    final_atlas_v = node(nodes, "ShaderNodeMath", "Final Atlas V", location=(960, -50), properties={"operation": "ADD"})
    link(links, cell_min_v, "Value", final_atlas_v, "Value[0]")
    link(links, wrap_v_scaled, "Value", final_atlas_v, "Value[1]")

    # 12. Output Final Atlas UV
    comb_atlas = node(nodes, "ShaderNodeCombineXYZ", "Combine Atlas UV", location=(1250, 0))
    link(links, final_atlas_u, "Value", comb_atlas, "X")
    link(links, final_atlas_v, "Value", comb_atlas, "Y")
    link(links, comb_atlas, "Vector", group_out, "Atlas UV")

    return finalize_group(tree)

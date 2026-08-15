"""Shader node group used by the Atlas material mode.

The group keeps the incoming (normalised) mesh UVs local to one atlas cell,
then chooses that cell from a face material id and the geometric face normal.
Minecraft's Y axis is Blender's Z axis, hence the face-order conversion below.
"""

from __future__ import annotations

import bpy

from .core import add_sockets, ensure_group, finalize_group, link, node


ATLAS_UV_DECODER_VERSION = 4


def build_atlas_uv_decoder_node_group() -> bpy.types.NodeTree:
    """Create or update the atlas UV decoder without breaking existing users.

    ``ensure_group`` clears a stale group *in place*.  Existing materials that
    reference it therefore receive the corrected node graph automatically.
    """
    tree = ensure_group("MC_Atlas_UV_Decoder", ATLAS_UV_DECODER_VERSION)
    if tree.nodes and tree.get("mozi_template_complete"):
        return tree

    add_sockets(tree, (
        ("Vector", "INPUT", "NodeSocketVector", None),
        ("Material ID", "INPUT", "NodeSocketFloat", 0.0, 0.0, 100000.0),
        # Optional explicit face choice.  Keeping automatic decoding as the
        # default means geometry nodes only need to write Material ID.
        ("Use Face Index", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0),
        ("Face Index", "INPUT", "NodeSocketFloat", 0.0, 0.0, 5.0),
        ("Is Animated", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0),
        ("Anim Column ID", "INPUT", "NodeSocketFloat", 0.0, 0.0, 100000.0),
        ("Current Frame", "INPUT", "NodeSocketFloat", 0.0, 0.0, 100000.0),
        ("Atlas Width", "INPUT", "NodeSocketFloat", 96.0, 1.0, 65536.0),
        ("Atlas Height", "INPUT", "NodeSocketFloat", 16.0, 1.0, 65536.0),
        ("Tile Size", "INPUT", "NodeSocketFloat", 16.0, 1.0, 16384.0),
        ("Static Material Columns", "INPUT", "NodeSocketFloat", 1.0, 1.0, 10000.0),
        ("Atlas UV", "OUTPUT", "NodeSocketVector", None),
    ))
    nodes, links = tree.nodes, tree.links
    group_in = node(nodes, "NodeGroupInput", "Group Input", location=(-1200, 0))
    group_out = node(nodes, "NodeGroupOutput", "Group Output", location=(900, 0))

    # Local UVs are repeated inside the selected cell.  This recreates the
    # Image Texture node's normal Repeat behaviour while preventing UV=1.0
    # from leaking into the next atlas cell.
    separate_uv = node(nodes, "ShaderNodeSeparateXYZ", "Separate UV", location=(-1000, -220))
    fract_u = node(nodes, "ShaderNodeMath", "Repeat Local U", location=(-820, -180), properties={"operation": "FRACT"})
    fract_v = node(nodes, "ShaderNodeMath", "Repeat Local V", location=(-820, -270), properties={"operation": "FRACT"})
    link(links, group_in, "Vector", separate_uv, "Vector")
    link(links, separate_uv, "X", fract_u, "Value[0]")
    link(links, separate_uv, "Y", fract_v, "Value[0]")

    u_step = node(nodes, "ShaderNodeMath", "Cell Width", location=(-820, -390), properties={"operation": "DIVIDE"})
    v_step = node(nodes, "ShaderNodeMath", "Cell Height", location=(-820, -480), properties={"operation": "DIVIDE"})
    link(links, group_in, "Tile Size", u_step, "Value[0]"); link(links, group_in, "Atlas Width", u_step, "Value[1]")
    link(links, group_in, "Tile Size", v_step, "Value[0]"); link(links, group_in, "Atlas Height", v_step, "Value[1]")

    # Blender axes -> atlas face order: +X, -X, +Z, -Z, +Y, -Y.
    geometry = node(nodes, "ShaderNodeNewGeometry", "Geometry", location=(-1200, 500))
    normal = node(nodes, "ShaderNodeSeparateXYZ", "Separate Normal", location=(-1020, 500))
    link(links, geometry, "Normal", normal, "Vector")
    checks = []
    for name, axis, operation, threshold, index, y in (
        ("-X", "X", "LESS_THAN", -0.5, 1.0, 620),
        ("+Z", "Z", "GREATER_THAN", 0.5, 2.0, 500),
        ("-Z", "Z", "LESS_THAN", -0.5, 3.0, 380),
        ("+Y", "Y", "GREATER_THAN", 0.5, 4.0, 260),
        ("-Y", "Y", "LESS_THAN", -0.5, 5.0, 140),
    ):
        check = node(nodes, "ShaderNodeMath", f"Normal is {name}", location=(-820, y), properties={"operation": operation}, inputs={"Value[1]": threshold})
        weighted = node(nodes, "ShaderNodeMath", f"{name} Face Index", location=(-650, y), properties={"operation": "MULTIPLY"}, inputs={"Value[1]": index})
        link(links, normal, axis, check, "Value[0]"); link(links, check, "Value", weighted, "Value[0]")
        checks.append(weighted)

    auto_face = checks[0]
    for index, weighted in enumerate(checks[1:], start=1):
        summed = node(nodes, "ShaderNodeMath", f"Auto Face Sum {index}", location=(-470 + index * 80, 500 - index * 45), properties={"operation": "ADD"})
        link(links, auto_face, "Value", summed, "Value[0]"); link(links, weighted, "Value", summed, "Value[1]")
        auto_face = summed

    chosen_face = node(nodes, "ShaderNodeMix", "Choose Face Index", location=(10, 360), properties={"data_type": "FLOAT"})
    link(links, group_in, "Use Face Index", chosen_face, "Factor")
    link(links, auto_face, "Value", chosen_face, "A")
    link(links, group_in, "Face Index", chosen_face, "B")

    # Static cells: materials are packed in a near-square grid, with six
    # consecutive face cells for each material.  PIL writes row zero at the
    # image top, while Blender UV V=0 is at the bottom.
    material_col = node(nodes, "ShaderNodeMath", "Material Grid Column", location=(0, 270), properties={"operation": "MODULO"})
    material_row = node(nodes, "ShaderNodeMath", "Material Grid Row", location=(0, 150), properties={"operation": "DIVIDE"})
    static_col_base = node(nodes, "ShaderNodeMath", "Material Face Start", location=(180, 270), properties={"operation": "MULTIPLY"}, inputs={"Value[1]": 6.0})
    static_col = node(nodes, "ShaderNodeMath", "Static Column", location=(360, 270), properties={"operation": "ADD"})
    static_row = node(nodes, "ShaderNodeMath", "Static Row", location=(180, 150), properties={"operation": "FLOOR"})
    link(links, group_in, "Material ID", material_col, "Value[0]"); link(links, group_in, "Static Material Columns", material_col, "Value[1]")
    link(links, group_in, "Material ID", material_row, "Value[0]"); link(links, group_in, "Static Material Columns", material_row, "Value[1]")
    link(links, material_col, "Value", static_col_base, "Value[0]")
    link(links, static_col_base, "Value", static_col, "Value[0]"); link(links, chosen_face, "Result", static_col, "Value[1]")
    link(links, material_row, "Value", static_row, "Value[0]")

    animated_start = node(nodes, "ShaderNodeMath", "Animated Region Start", location=(0, -10), properties={"operation": "MULTIPLY"}, inputs={"Value[1]": 6.0})
    anim_col_base = node(nodes, "ShaderNodeMath", "Animated Column Base", location=(180, -10), properties={"operation": "ADD"})
    anim_col = node(nodes, "ShaderNodeMath", "Animated Column", location=(360, -10), properties={"operation": "FLOOR"})
    anim_row = node(nodes, "ShaderNodeMath", "Animated Row", location=(180, -110), properties={"operation": "FLOOR"})
    link(links, group_in, "Static Material Columns", animated_start, "Value[0]")
    link(links, animated_start, "Value", anim_col_base, "Value[0]"); link(links, group_in, "Anim Column ID", anim_col_base, "Value[1]"); link(links, anim_col_base, "Value", anim_col, "Value[0]")
    link(links, group_in, "Current Frame", anim_row, "Value[0]")

    select_col = node(nodes, "ShaderNodeMix", "Choose Atlas Column", location=(530, 170), properties={"data_type": "FLOAT"})
    select_row = node(nodes, "ShaderNodeMix", "Choose Atlas Row", location=(530, 30), properties={"data_type": "FLOAT"})
    for selected, static, animated in ((select_col, static_col, anim_col), (select_row, static_row, anim_row)):
        link(links, group_in, "Is Animated", selected, "Factor")
        link(links, static, "Value", selected, "A")
        link(links, animated, "Value", selected, "B")

    # atlas_u = (column + local_u) * cell_width
    # atlas_v = 1 - (row + 1 - local_v) * cell_height
    u_local = node(nodes, "ShaderNodeMath", "Column + Local U", location=(700, 210), properties={"operation": "ADD"})
    u_final = node(nodes, "ShaderNodeMath", "Atlas U", location=(880, 210), properties={"operation": "MULTIPLY"})
    row_plus_one = node(nodes, "ShaderNodeMath", "Row + 1", location=(700, 70), properties={"operation": "ADD"}, inputs={"Value[1]": 1.0})
    row_minus_v = node(nodes, "ShaderNodeMath", "Row + 1 - Local V", location=(880, 70), properties={"operation": "SUBTRACT"})
    v_scaled = node(nodes, "ShaderNodeMath", "Atlas V Distance", location=(1060, 70), properties={"operation": "MULTIPLY"})
    v_final = node(nodes, "ShaderNodeMath", "Atlas V", location=(1240, 70), properties={"operation": "SUBTRACT"}, inputs={"Value[0]": 1.0})
    link(links, select_col, "Result", u_local, "Value[0]"); link(links, fract_u, "Value", u_local, "Value[1]"); link(links, u_local, "Value", u_final, "Value[0]"); link(links, u_step, "Value", u_final, "Value[1]")
    link(links, select_row, "Result", row_plus_one, "Value[0]"); link(links, row_plus_one, "Value", row_minus_v, "Value[0]"); link(links, fract_v, "Value", row_minus_v, "Value[1]"); link(links, row_minus_v, "Value", v_scaled, "Value[0]"); link(links, v_step, "Value", v_scaled, "Value[1]"); link(links, v_scaled, "Value", v_final, "Value[1]")

    combine = node(nodes, "ShaderNodeCombineXYZ", "Atlas UV", location=(1420, 140))
    link(links, u_final, "Value", combine, "X"); link(links, v_final, "Value", combine, "Y")
    link(links, combine, "Vector", group_out, "Atlas UV")
    return finalize_group(tree)

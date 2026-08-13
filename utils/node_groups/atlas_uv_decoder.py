"""
Blender Shader Node Group template for Atlas Mode UV Decoding.
Calculates exact atlas UV coordinates from Material ID, Face Index, and Animation frames.
"""

import bpy


def build_atlas_uv_decoder_node_group() -> bpy.types.NodeTree:
    """
    Creates or returns the ShaderNodeTree for 'MC_Atlas_UV_Decoder'.
    """
    group_name = "MC_Atlas_UV_Decoder"
    if group_name in bpy.data.node_groups:
        return bpy.data.node_groups[group_name]

    tree = bpy.data.node_groups.new(name=group_name, type="ShaderNodeTree")

    # Interface inputs
    tree.interface.new_socket("Vector", in_out="INPUT", socket_type="NodeSocketVector")
    tree.interface.new_socket("Material ID", in_out="INPUT", socket_type="NodeSocketFloat")
    tree.interface.new_socket("Face Index", in_out="INPUT", socket_type="NodeSocketFloat")
    tree.interface.new_socket("Is Animated", in_out="INPUT", socket_type="NodeSocketFloat")
    tree.interface.new_socket("Anim Column ID", in_out="INPUT", socket_type="NodeSocketFloat")
    tree.interface.new_socket("Current Frame", in_out="INPUT", socket_type="NodeSocketFloat")

    sock_w = tree.interface.new_socket("Atlas Width", in_out="INPUT", socket_type="NodeSocketFloat")
    sock_w.default_value = 1728.0

    sock_h = tree.interface.new_socket("Atlas Height", in_out="INPUT", socket_type="NodeSocketFloat")
    sock_h.default_value = 52352.0

    sock_tile = tree.interface.new_socket("Tile Size", in_out="INPUT", socket_type="NodeSocketFloat")
    sock_tile.default_value = 16.0

    # Interface output
    tree.interface.new_socket("Atlas UV", in_out="OUTPUT", socket_type="NodeSocketVector")

    nodes = tree.nodes
    links = tree.links

    group_in = nodes.new("NodeGroupInput")
    group_in.location = (-1000, 0)

    group_out = nodes.new("NodeGroupOutput")
    group_out.location = (1000, 0)

    # Separate Vector into UV components
    sep_uv = nodes.new("ShaderNodeSeparateXYZ")
    sep_uv.location = (-750, 400)
    links.new(group_in.outputs["Vector"], sep_uv.inputs["Vector"])

    # 1. Compute U_step and V_step
    # U_step = Tile Size / Atlas Width
    div_u_step = nodes.new("ShaderNodeMath")
    div_u_step.operation = "DIVIDE"
    div_u_step.name = "U_step"
    div_u_step.location = (-750, 100)
    links.new(group_in.outputs["Tile Size"], div_u_step.inputs[0])
    links.new(group_in.outputs["Atlas Width"], div_u_step.inputs[1])

    # V_step = Tile Size / Atlas Height
    div_v_step = nodes.new("ShaderNodeMath")
    div_v_step.operation = "DIVIDE"
    div_v_step.name = "V_step"
    div_v_step.location = (-750, -100)
    links.new(group_in.outputs["Tile Size"], div_v_step.inputs[0])
    links.new(group_in.outputs["Atlas Height"], div_v_step.inputs[1])

    # --- STATIC BRANCH ---
    # Col_X_static = Face Index (0..5)
    # Row_Y_static = Material ID
    # U_min_static = Face Index * U_step
    mul_u_static = nodes.new("ShaderNodeMath")
    mul_u_static.operation = "MULTIPLY"
    mul_u_static.location = (-500, 200)
    links.new(group_in.outputs["Face Index"], mul_u_static.inputs[0])
    links.new(div_u_step.outputs["Value"], mul_u_static.inputs[1])

    # Row_Y_static + 1.0
    add_row_static = nodes.new("ShaderNodeMath")
    add_row_static.operation = "ADD"
    add_row_static.location = (-500, 50)
    links.new(group_in.outputs["Material ID"], add_row_static.inputs[0])
    add_row_static.inputs[1].default_value = 1.0

    # (Row_Y_static + 1.0) * V_step
    mul_v_static = nodes.new("ShaderNodeMath")
    mul_v_static.operation = "MULTIPLY"
    mul_v_static.location = (-350, 50)
    links.new(add_row_static.outputs["Value"], mul_v_static.inputs[0])
    links.new(div_v_step.outputs["Value"], mul_v_static.inputs[1])

    # V_min_static = 1.0 - (Row_Y_static + 1.0) * V_step
    sub_v_static = nodes.new("ShaderNodeMath")
    sub_v_static.operation = "SUBTRACT"
    sub_v_static.location = (-200, 50)
    sub_v_static.inputs[0].default_value = 1.0
    links.new(mul_v_static.outputs["Value"], sub_v_static.inputs[1])

    # Final U_static = U_min_static + UV.X * U_step
    mul_offset_u_stat = nodes.new("ShaderNodeMath")
    mul_offset_u_stat.operation = "MULTIPLY"
    mul_offset_u_stat.location = (-350, 300)
    links.new(sep_uv.outputs["X"], mul_offset_u_stat.inputs[0])
    links.new(div_u_step.outputs["Value"], mul_offset_u_stat.inputs[1])

    u_static_final = nodes.new("ShaderNodeMath")
    u_static_final.operation = "ADD"
    u_static_final.location = (-50, 300)
    links.new(mul_u_static.outputs["Value"], u_static_final.inputs[0])
    links.new(mul_offset_u_stat.outputs["Value"], u_static_final.inputs[1])

    # Final V_static = V_min_static + UV.Y * V_step
    mul_offset_v_stat = nodes.new("ShaderNodeMath")
    mul_offset_v_stat.operation = "MULTIPLY"
    mul_offset_v_stat.location = (-350, -100)
    links.new(sep_uv.outputs["Y"], mul_offset_v_stat.inputs[0])
    links.new(div_v_step.outputs["Value"], mul_offset_v_stat.inputs[1])

    v_static_final = nodes.new("ShaderNodeMath")
    v_static_final.operation = "ADD"
    v_static_final.location = (-50, 50)
    links.new(sub_v_static.outputs["Value"], v_static_final.inputs[0])
    links.new(mul_offset_v_stat.outputs["Value"], v_static_final.inputs[1])

    # --- ANIMATED BRANCH ---
    # Col_X_anim = 6.0 + Anim Column ID
    add_col_anim = nodes.new("ShaderNodeMath")
    add_col_anim.operation = "ADD"
    add_col_anim.location = (-500, -300)
    add_col_anim.inputs[0].default_value = 6.0
    links.new(group_in.outputs["Anim Column ID"], add_col_anim.inputs[1])

    # U_min_anim = Col_X_anim * U_step
    mul_u_anim = nodes.new("ShaderNodeMath")
    mul_u_anim.operation = "MULTIPLY"
    mul_u_anim.location = (-350, -300)
    links.new(add_col_anim.outputs["Value"], mul_u_anim.inputs[0])
    links.new(div_u_step.outputs["Value"], mul_u_anim.inputs[1])

    # Row_Y_anim + 1.0
    add_row_anim = nodes.new("ShaderNodeMath")
    add_row_anim.operation = "ADD"
    add_row_anim.location = (-500, -450)
    links.new(group_in.outputs["Current Frame"], add_row_anim.inputs[0])
    add_row_anim.inputs[1].default_value = 1.0

    # (Row_Y_anim + 1.0) * V_step
    mul_v_anim = nodes.new("ShaderNodeMath")
    mul_v_anim.operation = "MULTIPLY"
    mul_v_anim.location = (-350, -450)
    links.new(add_row_anim.outputs["Value"], mul_v_anim.inputs[0])
    links.new(div_v_step.outputs["Value"], mul_v_anim.inputs[1])

    # V_min_anim = 1.0 - (Row_Y_anim + 1.0) * V_step
    sub_v_anim = nodes.new("ShaderNodeMath")
    sub_v_anim.operation = "SUBTRACT"
    sub_v_anim.location = (-200, -450)
    sub_v_anim.inputs[0].default_value = 1.0
    links.new(mul_v_anim.outputs["Value"], sub_v_anim.inputs[1])

    # Final U_anim = U_min_anim + UV.X * U_step
    u_anim_final = nodes.new("ShaderNodeMath")
    u_anim_final.operation = "ADD"
    u_anim_final.location = (-50, -300)
    links.new(mul_u_anim.outputs["Value"], u_anim_final.inputs[0])
    links.new(mul_offset_u_stat.outputs["Value"], u_anim_final.inputs[1])

    # Final V_anim = V_min_anim + UV.Y * V_step
    v_anim_final = nodes.new("ShaderNodeMath")
    v_anim_final.operation = "ADD"
    v_anim_final.location = (-50, -450)
    links.new(sub_v_anim.outputs["Value"], v_anim_final.inputs[0])
    links.new(mul_offset_v_stat.outputs["Value"], v_anim_final.inputs[1])

    # --- MIX BRANCHES (Is Animated > 0.5) ---
    mix_u = nodes.new("ShaderNodeMix")
    mix_u.data_type = "FLOAT"
    mix_u.location = (250, 200)
    links.new(group_in.outputs["Is Animated"], mix_u.inputs["Factor"])
    links.new(u_static_final.outputs["Value"], mix_u.inputs[2])
    links.new(u_anim_final.outputs["Value"], mix_u.inputs[3])

    mix_v = nodes.new("ShaderNodeMix")
    mix_v.data_type = "FLOAT"
    mix_v.location = (250, -100)
    links.new(group_in.outputs["Is Animated"], mix_v.inputs["Factor"])
    links.new(v_static_final.outputs["Value"], mix_v.inputs[2])
    links.new(v_anim_final.outputs["Value"], mix_v.inputs[3])

    # Combine XYZ
    comb_xyz = nodes.new("ShaderNodeCombineXYZ")
    comb_xyz.location = (550, 50)
    links.new(mix_u.outputs["Result"], comb_xyz.inputs["X"])
    links.new(mix_v.outputs["Result"], comb_xyz.inputs["Y"])

    links.new(comb_xyz.outputs["Vector"], group_out.inputs["Atlas UV"])

    return tree

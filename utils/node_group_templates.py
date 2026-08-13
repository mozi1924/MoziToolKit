import bpy


def ensure_labpbr_decoder() -> bpy.types.NodeTree:
    """Ensure LabPBR 1.3 Decoder node group exists in scene. Create if missing."""
    group_name = "LabPBR 1.3 Decoder"
    if group_name in bpy.data.node_groups and len(bpy.data.node_groups[group_name].nodes) > 0:
        return bpy.data.node_groups[group_name]

    if group_name in bpy.data.node_groups:
        ng = bpy.data.node_groups[group_name]
    else:
        ng = bpy.data.node_groups.new(name=group_name, type="ShaderNodeTree")


    # Interfaces (Sockets)
    if hasattr(ng, "interface"):
        # Blender 4.0+ interface API
        s1 = ng.interface.new_socket(name="Enable PBR (0-1)", in_out="INPUT", socket_type="NodeSocketFloat")
        s1.default_value = 1.0
        
        s2 = ng.interface.new_socket(name="Albedo Color", in_out="INPUT", socket_type="NodeSocketColor")
        s2.default_value = (1, 1, 1, 1)

        s3 = ng.interface.new_socket(name="Albedo Alpha", in_out="INPUT", socket_type="NodeSocketFloat")
        s3.default_value = 1.0

        s4 = ng.interface.new_socket(name="Normal (_n) Color", in_out="INPUT", socket_type="NodeSocketColor")
        s4.default_value = (0.5, 0.5, 1.0, 1.0)

        s5 = ng.interface.new_socket(name="Normal (_n) Alpha (Height)", in_out="INPUT", socket_type="NodeSocketFloat")
        s5.default_value = 0.0

        s6 = ng.interface.new_socket(name="Specular (_s) Color", in_out="INPUT", socket_type="NodeSocketColor")
        s6.default_value = (0, 0, 0, 1)

        s7 = ng.interface.new_socket(name="Specular (_s) Alpha (Emission)", in_out="INPUT", socket_type="NodeSocketFloat")
        s7.default_value = 1.0

        s8 = ng.interface.new_socket(name="Displacement Scale", in_out="INPUT", socket_type="NodeSocketFloat")
        s8.default_value = 0.05

        s9 = ng.interface.new_socket(name="Emission Strength", in_out="INPUT", socket_type="NodeSocketFloat")
        s9.default_value = 1.0

        ng.interface.new_socket(name="BSDF", in_out="OUTPUT", socket_type="NodeSocketShader")
        ng.interface.new_socket(name="Displacement", in_out="OUTPUT", socket_type="NodeSocketVector")
        ng.interface.new_socket(name="Porosity (0-1)", in_out="OUTPUT", socket_type="NodeSocketFloat")


    nodes = ng.nodes
    links = ng.links

    input_node = nodes.new("NodeGroupInput")
    output_node = nodes.new("NodeGroupOutput")
    input_node.location = (-600, 0)
    output_node.location = (600, 0)

    # Core BSDF
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 0)

    # Separate Color for _n
    sep_n = nodes.new("ShaderNodeSeparateColor")
    sep_n.name = "Decode _n (DirectX)"
    sep_n.location = (-300, 200)

    # Separate Color for _s
    sep_s = nodes.new("ShaderNodeSeparateColor")
    sep_s.name = "Decode _s"
    sep_s.location = (-300, -200)

    # Normal map node
    norm_map = nodes.new("ShaderNodeNormalMap")
    norm_map.location = (0, 100)

    # Displacement node
    disp = nodes.new("ShaderNodeDisplacement")
    disp.location = (300, -300)

    # Standard LabPBR decoding connections
    links.new(input_node.outputs["Albedo Color"], bsdf.inputs["Base Color"])
    links.new(input_node.outputs["Albedo Alpha"], bsdf.inputs["Alpha"])
    links.new(input_node.outputs["Normal (_n) Color"], sep_n.inputs["Color"])
    links.new(input_node.outputs["Specular (_s) Color"], sep_s.inputs["Color"])

    # Roughness / Smoothness decoding (Red channel of _s = Smoothness = 1 - Roughness)
    math_rough = nodes.new("ShaderNodeMath")
    math_rough.operation = 'SUBTRACT'
    math_rough.inputs[0].default_value = 1.0
    math_rough.location = (-100, -150)
    links.new(sep_s.outputs["Red"], math_rough.inputs[1])
    links.new(math_rough.outputs[0], bsdf.inputs["Roughness"])

    # Metallic decoding (Blue channel of _s)
    links.new(sep_s.outputs["Blue"], bsdf.inputs["Metallic"])

    # Normal map connection (DirectX normal decoding)
    links.new(sep_n.outputs["Red"], norm_map.inputs["Color"])
    links.new(norm_map.outputs["Normal"], bsdf.inputs["Normal"])

    # Emission setup (Alpha of _s < 1.0 = emissive)
    links.new(input_node.outputs["Albedo Color"], bsdf.inputs["Emission Color"])
    links.new(input_node.outputs["Emission Strength"], bsdf.inputs["Emission Strength"])

    # Displacement connection
    links.new(input_node.outputs["Normal (_n) Alpha (Height)"], disp.inputs["Height"])
    links.new(input_node.outputs["Displacement Scale"], disp.inputs["Scale"])

    # Outputs
    links.new(bsdf.outputs["BSDF"], output_node.inputs["BSDF"])
    links.new(disp.outputs["Displacement"], output_node.inputs["Displacement"])

    return ng


def ensure_animated_uv_mapping() -> bpy.types.NodeTree:
    """Ensure MC_Animated_UV_Mapping node group exists in scene. Create if missing."""
    group_name = "MC_Animated_UV_Mapping"
    if group_name in bpy.data.node_groups and len(bpy.data.node_groups[group_name].nodes) > 0:
        return bpy.data.node_groups[group_name]

    if group_name in bpy.data.node_groups:
        ng = bpy.data.node_groups[group_name]
    else:
        ng = bpy.data.node_groups.new(name=group_name, type="ShaderNodeTree")

    if hasattr(ng, "interface"):
        ng.interface.new_socket(name="Vector", in_out="INPUT", socket_type="NodeSocketVector")
        s_cf = ng.interface.new_socket(name="Current Frame", in_out="INPUT", socket_type="NodeSocketFloat")
        s_cf.default_value = 0.0
        s_nf = ng.interface.new_socket(name="Next Frame", in_out="INPUT", socket_type="NodeSocketFloat")
        s_nf.default_value = 1.0
        s_fw = ng.interface.new_socket(name="Frame Width", in_out="INPUT", socket_type="NodeSocketFloat")
        s_fw.default_value = 16.0
        s_fh = ng.interface.new_socket(name="Frame Height", in_out="INPUT", socket_type="NodeSocketFloat")
        s_fh.default_value = 16.0
        s_iw = ng.interface.new_socket(name="Image Width", in_out="INPUT", socket_type="NodeSocketFloat")
        s_iw.default_value = 16.0
        s_ih = ng.interface.new_socket(name="Image Height", in_out="INPUT", socket_type="NodeSocketFloat")
        s_ih.default_value = 1024.0

        ng.interface.new_socket(name="Current UV", in_out="OUTPUT", socket_type="NodeSocketVector")
        ng.interface.new_socket(name="Next UV", in_out="OUTPUT", socket_type="NodeSocketVector")

    nodes = ng.nodes
    links = ng.links

    input_node = nodes.new("NodeGroupInput")
    output_node = nodes.new("NodeGroupOutput")
    input_node.location = (-800, 0)
    output_node.location = (800, 0)

    sep_xyz = nodes.new("ShaderNodeSeparateXYZ")
    sep_xyz.location = (-600, 200)
    links.new(input_node.outputs["Vector"], sep_xyz.inputs["Vector"])

    # V scale = Frame Height / Image Height
    v_scale = nodes.new("ShaderNodeMath")
    v_scale.operation = 'DIVIDE'
    v_scale.location = (-500, -100)
    links.new(input_node.outputs["Frame Height"], v_scale.inputs[0])
    links.new(input_node.outputs["Image Height"], v_scale.inputs[1])

    # Scaled V = V_in * V_scale
    scaled_v = nodes.new("ShaderNodeMath")
    scaled_v.operation = 'MULTIPLY'
    scaled_v.location = (-350, 100)
    links.new(sep_xyz.outputs["Y"], scaled_v.inputs[0])
    links.new(v_scale.outputs[0], scaled_v.inputs[1])

    # --- Current Frame UV ---
    curr_v_offset = nodes.new("ShaderNodeMath")
    curr_v_offset.operation = 'MULTIPLY'
    curr_v_offset.location = (-150, 200)
    links.new(input_node.outputs["Current Frame"], curr_v_offset.inputs[0])
    links.new(v_scale.outputs[0], curr_v_offset.inputs[1])

    curr_v_final = nodes.new("ShaderNodeMath")
    curr_v_final.operation = 'ADD'
    curr_v_final.location = (100, 200)
    links.new(scaled_v.outputs[0], curr_v_final.inputs[0])
    links.new(curr_v_offset.outputs[0], curr_v_final.inputs[1])

    comb_curr = nodes.new("ShaderNodeCombineXYZ")
    comb_curr.location = (400, 200)
    links.new(sep_xyz.outputs["X"], comb_curr.inputs["X"])
    links.new(curr_v_final.outputs[0], comb_curr.inputs["Y"])

    # --- Next Frame UV ---
    next_v_offset = nodes.new("ShaderNodeMath")
    next_v_offset.operation = 'MULTIPLY'
    next_v_offset.location = (-150, -200)
    links.new(input_node.outputs["Next Frame"], next_v_offset.inputs[0])
    links.new(v_scale.outputs[0], next_v_offset.inputs[1])

    next_v_final = nodes.new("ShaderNodeMath")
    next_v_final.operation = 'ADD'
    next_v_final.location = (100, -200)
    links.new(scaled_v.outputs[0], next_v_final.inputs[0])
    links.new(next_v_offset.outputs[0], next_v_final.inputs[1])

    comb_next = nodes.new("ShaderNodeCombineXYZ")
    comb_next.location = (400, -200)
    links.new(sep_xyz.outputs["X"], comb_next.inputs["X"])
    links.new(next_v_final.outputs[0], comb_next.inputs["Y"])

    links.new(comb_curr.outputs["Vector"], output_node.inputs["Current UV"])
    links.new(comb_next.outputs["Vector"], output_node.inputs["Next UV"])

    return ng


def ensure_animation_scheduler() -> bpy.types.NodeTree:
    """Ensure MC_Animation_Scheduler_Default node group exists in scene. Create if missing."""
    group_name = "MC_Animation_Scheduler_Default"
    if group_name in bpy.data.node_groups and len(bpy.data.node_groups[group_name].nodes) > 0:
        return bpy.data.node_groups[group_name]

    if group_name in bpy.data.node_groups:
        ng = bpy.data.node_groups[group_name]
    else:
        ng = bpy.data.node_groups.new(name=group_name, type="ShaderNodeTree")

    if hasattr(ng, "interface"):
        s_tf = ng.interface.new_socket(name="Total Frames", in_out="INPUT", socket_type="NodeSocketInt")
        s_tf.default_value = 16
        s_ft = ng.interface.new_socket(name="Frametime", in_out="INPUT", socket_type="NodeSocketInt")
        s_ft.default_value = 2
        s_ip = ng.interface.new_socket(name="Interpolate", in_out="INPUT", socket_type="NodeSocketBool")
        s_ip.default_value = True

        ng.interface.new_socket(name="Current Frame", in_out="OUTPUT", socket_type="NodeSocketFloat")
        ng.interface.new_socket(name="Next Frame", in_out="OUTPUT", socket_type="NodeSocketFloat")
        ng.interface.new_socket(name="Blend Factor", in_out="OUTPUT", socket_type="NodeSocketFloat")

    nodes = ng.nodes
    links = ng.links

    input_node = nodes.new("NodeGroupInput")
    output_node = nodes.new("NodeGroupOutput")
    input_node.location = (-600, 0)
    output_node.location = (600, 0)

    # Timeline Frame value node
    time_frame = nodes.new("ShaderNodeValue")
    time_frame.name = "Timeline Frame"
    time_frame.location = (-500, 200)

    # Add driver to time_frame to follow scene frame_current
    driver = time_frame.outputs[0].driver_add("default_value").driver
    driver.expression = "frame"

    # Effective Phase: (Frame / Frametime)
    phase = nodes.new("ShaderNodeMath")
    phase.operation = 'DIVIDE'
    phase.location = (-300, 100)
    links.new(time_frame.outputs[0], phase.inputs[0])
    links.new(input_node.outputs["Frametime"], phase.inputs[1])

    # Current Frame Unwrapped = floor(Phase)
    curr_floor = nodes.new("ShaderNodeMath")
    curr_floor.operation = 'FLOOR'
    curr_floor.location = (-100, 200)
    links.new(phase.outputs[0], curr_floor.inputs[0])

    # Current Frame Wrapped = curr_floor % Total Frames
    curr_wrap = nodes.new("ShaderNodeMath")
    curr_wrap.operation = 'MODULO'
    curr_wrap.location = (100, 200)
    links.new(curr_floor.outputs[0], curr_wrap.inputs[0])
    links.new(input_node.outputs["Total Frames"], curr_wrap.inputs[1])

    # Next Frame Wrapped = (curr_floor + 1) % Total Frames
    next_raw = nodes.new("ShaderNodeMath")
    next_raw.operation = 'ADD'
    next_raw.inputs[1].default_value = 1.0
    next_raw.location = (-100, -100)
    links.new(curr_floor.outputs[0], next_raw.inputs[0])

    next_wrap = nodes.new("ShaderNodeMath")
    next_wrap.operation = 'MODULO'
    next_wrap.location = (100, -100)
    links.new(next_raw.outputs[0], next_wrap.inputs[0])
    links.new(input_node.outputs["Total Frames"], next_wrap.inputs[1])

    # Fraction = Phase - floor(Phase)
    fract = nodes.new("ShaderNodeMath")
    fract.operation = 'SUBTRACT'
    fract.location = (100, 0)
    links.new(phase.outputs[0], fract.inputs[0])
    links.new(curr_floor.outputs[0], fract.inputs[1])

    # Blend Factor = Interpolate ? Fraction : 0
    blend = nodes.new("ShaderNodeMath")
    blend.operation = 'MULTIPLY'
    blend.location = (300, 0)
    links.new(fract.outputs[0], blend.inputs[0])
    links.new(input_node.outputs["Interpolate"], blend.inputs[1])

    links.new(curr_wrap.outputs[0], output_node.inputs["Current Frame"])
    links.new(next_wrap.outputs[0], output_node.inputs["Next Frame"])
    links.new(blend.outputs[0], output_node.inputs["Blend Factor"])

    return ng


def ensure_animated_frame_blend() -> bpy.types.NodeTree:
    """Ensure MC_Animated_Frame_Blend node group exists in scene. Create if missing."""
    group_name = "MC_Animated_Frame_Blend"
    if group_name in bpy.data.node_groups and len(bpy.data.node_groups[group_name].nodes) > 0:
        return bpy.data.node_groups[group_name]

    if group_name in bpy.data.node_groups:
        ng = bpy.data.node_groups[group_name]
    else:
        ng = bpy.data.node_groups.new(name=group_name, type="ShaderNodeTree")

    if hasattr(ng, "interface"):
        s_cc = ng.interface.new_socket(name="Current Color", in_out="INPUT", socket_type="NodeSocketColor")
        s_cc.default_value = (1, 1, 1, 1)
        s_nc = ng.interface.new_socket(name="Next Color", in_out="INPUT", socket_type="NodeSocketColor")
        s_nc.default_value = (1, 1, 1, 1)
        s_ca = ng.interface.new_socket(name="Current Alpha", in_out="INPUT", socket_type="NodeSocketFloat")
        s_ca.default_value = 1.0
        s_na = ng.interface.new_socket(name="Next Alpha", in_out="INPUT", socket_type="NodeSocketFloat")
        s_na.default_value = 1.0
        s_bf = ng.interface.new_socket(name="Blend Factor", in_out="INPUT", socket_type="NodeSocketFloat")
        s_bf.default_value = 0.0

        ng.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
        ng.interface.new_socket(name="Alpha", in_out="OUTPUT", socket_type="NodeSocketFloat")

    nodes = ng.nodes
    links = ng.links

    input_node = nodes.new("NodeGroupInput")
    output_node = nodes.new("NodeGroupOutput")
    input_node.location = (-600, 0)
    output_node.location = (600, 0)

    # Color mix (Mix RGB)
    mix_color = nodes.new("ShaderNodeMixRGB")
    mix_color.location = (100, 100)
    links.new(input_node.outputs["Blend Factor"], mix_color.inputs["Factor"])
    links.new(input_node.outputs["Current Color"], mix_color.inputs["Color1"])
    links.new(input_node.outputs["Next Color"], mix_color.inputs["Color2"])

    # Alpha mix
    mix_alpha = nodes.new("ShaderNodeMath")
    mix_alpha.operation = 'MULTIPLY_ADD'
    mix_alpha.location = (100, -100)
    # Lerp: Current * (1 - Factor) + Next * Factor
    # Using Math nodes or simple lerp
    links.new(input_node.outputs["Current Alpha"], mix_alpha.inputs[0])
    links.new(input_node.outputs["Next Alpha"], mix_alpha.inputs[1])
    links.new(input_node.outputs["Blend Factor"], mix_alpha.inputs[2])

    links.new(mix_color.outputs["Color"], output_node.inputs["Color"])
    links.new(mix_alpha.outputs[0], output_node.inputs["Alpha"])

    return ng


def ensure_all_templates():
    """Ensure all 4 required Minecraft LabPBR / Animation node groups exist."""
    return {
        "LabPBR 1.3 Decoder": ensure_labpbr_decoder(),
        "MC_Animated_UV_Mapping": ensure_animated_uv_mapping(),
        "MC_Animation_Scheduler_Default": ensure_animation_scheduler(),
        "MC_Animated_Frame_Blend": ensure_animated_frame_blend(),
    }

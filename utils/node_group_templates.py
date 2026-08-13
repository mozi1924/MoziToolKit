import bpy


TEMPLATE_VERSION = 2
UV_TEMPLATE_VERSION = 4
SCHEDULER_TEMPLATE_VERSION = 3


def _group(name: str, version: int = TEMPLATE_VERSION) -> bpy.types.NodeTree:
    """Return a fresh, versioned template group.

    Templates used to be returned merely because a group with the same name
    existed.  This made old, incomplete groups persist in files after an addon
    update.  Rebuild groups created by this addon when their schema changes.
    """
    ng = bpy.data.node_groups.get(name)
    if ng is None:
        ng = bpy.data.node_groups.new(name=name, type="ShaderNodeTree")
    elif ng.get("mozi_template_version") == version:
        return ng
    else:
        ng.nodes.clear()
        ng.interface.clear()
    ng["mozi_template_version"] = version
    return ng


def _socket(ng, name, direction, socket_type, default=None):
    socket = ng.interface.new_socket(name=name, in_out=direction, socket_type=socket_type)
    if default is not None:
        socket.default_value = default
    return socket


def _math(nodes, operation, name, location, *defaults):
    node = nodes.new("ShaderNodeMath")
    node.operation, node.name, node.label, node.location = operation, name, name, location
    for index, value in enumerate(defaults):
        node.inputs[index].default_value = value
    return node


def ensure_labpbr_decoder() -> bpy.types.NodeTree:
    """Build the LabPBR 1.3 decoder used by the supplied reference file."""
    ng = _group("LabPBR 1.3 Decoder")
    if ng.nodes:
        return ng
    _socket(ng, "BSDF", "OUTPUT", "NodeSocketShader")
    _socket(ng, "Displacement", "OUTPUT", "NodeSocketVector")
    _socket(ng, "Porosity (0-1)", "OUTPUT", "NodeSocketFloat")
    _socket(ng, "Enable PBR (0-1)", "INPUT", "NodeSocketFloat", 1.0)
    _socket(ng, "Albedo Color", "INPUT", "NodeSocketColor", (1, 1, 1, 1))
    _socket(ng, "Albedo Alpha", "INPUT", "NodeSocketFloat", 1.0)
    _socket(ng, "Normal (_n) Color", "INPUT", "NodeSocketColor", (0.5, 0.5, 1, 1))
    _socket(ng, "Normal (_n) Alpha (Height)", "INPUT", "NodeSocketFloat", 1.0)
    _socket(ng, "Specular (_s) Color", "INPUT", "NodeSocketColor", (0, 0, 0, 1))
    _socket(ng, "Specular (_s) Alpha (Emission)", "INPUT", "NodeSocketFloat", 1.0)
    _socket(ng, "Displacement Scale", "INPUT", "NodeSocketFloat", 0.05)
    _socket(ng, "Emission Strength", "INPUT", "NodeSocketFloat", 1.0)

    n, l = ng.nodes, ng.links
    inp, out = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    inp.location, out.location = (-1100, 0), (1000, 0)
    bsdf = n.new("ShaderNodeBsdfPrincipled"); bsdf.name = "LabPBR Principled BSDF"; bsdf.location = (750, 180)
    disp = n.new("ShaderNodeDisplacement"); disp.name = "LabPBR Height Displacement"; disp.location = (750, -180)
    sep_n, sep_s = n.new("ShaderNodeSeparateColor"), n.new("ShaderNodeSeparateColor")
    sep_n.name, sep_s.name = "Decode _n (DirectX)", "Decode _s"
    sep_n.location, sep_s.location = (-850, 180), (-850, -220)
    l.new(inp.outputs["Normal (_n) Color"], sep_n.inputs["Color"])
    l.new(inp.outputs["Specular (_s) Color"], sep_s.inputs["Color"])

    # LabPBR normal maps are DirectX/X+Y- encoded: reconstruct Z before
    # passing it to Blender's Normal Map node (which handles Y inversion).
    x = _math(n, "MULTIPLY_ADD", "Normal X: 2R − 1", (-620, 220), 2.0, -1.0)
    y = _math(n, "MULTIPLY_ADD", "Normal Y: 1 − 2G", (-620, 140), -2.0, 1.0)
    x2, y2 = _math(n, "MULTIPLY", "X²", (-430, 250)), _math(n, "MULTIPLY", "Y²", (-430, 100))
    total = _math(n, "ADD", "X² + Y²", (-250, 180))
    z2, clamp_z, z = _math(n, "SUBTRACT", "1 − X² − Y²", (-80, 180), 1.0), _math(n, "MAXIMUM", "Clamp normal Z", (80, 180), 0.0), _math(n, "SQRT", "Reconstructed normal Z", (240, 180))
    enc_x, enc_y = _math(n, "MULTIPLY_ADD", "Encode X", (240, 280), 0.5, 0.5), _math(n, "MULTIPLY_ADD", "Encode Y", (240, 100), 0.5, 0.5)
    normal_color = n.new("ShaderNodeCombineColor"); normal_color.name = "Reconstructed DirectX Normal"; normal_color.location = (410, 190)
    normal = n.new("ShaderNodeNormalMap"); normal.name = "LabPBR Normal Map"; normal.location = (580, 200)
    l.new(sep_n.outputs["Red"], x.inputs[0]); l.new(sep_n.outputs["Green"], y.inputs[0])
    for source, square in ((x, x2), (y, y2)):
        l.new(source.outputs[0], square.inputs[0]); l.new(source.outputs[0], square.inputs[1])
    l.new(x2.outputs[0], total.inputs[0]); l.new(y2.outputs[0], total.inputs[1]); l.new(total.outputs[0], z2.inputs[1]); l.new(z2.outputs[0], clamp_z.inputs[1]); l.new(clamp_z.outputs[0], z.inputs[0])
    l.new(x.outputs[0], enc_x.inputs[0]); l.new(y.outputs[0], enc_y.inputs[0]); l.new(enc_x.outputs[0], normal_color.inputs["Red"]); l.new(enc_y.outputs[0], normal_color.inputs["Green"]); l.new(z.outputs[0], normal_color.inputs["Blue"]); l.new(normal_color.outputs["Color"], normal.inputs["Color"]); l.new(normal.outputs["Normal"], bsdf.inputs["Normal"])

    # Material AO is stored in _n blue.  Smoothness is _s red and Blender
    # expects linear roughness, hence (1 - smoothness)^2.
    ao = n.new("ShaderNodeMixRGB"); ao.blend_type = "MULTIPLY"; ao.name = "Albedo × Material AO"; ao.location = (420, 430); ao.inputs[0].default_value = 1.0
    l.new(inp.outputs["Albedo Color"], ao.inputs[1]); l.new(sep_n.outputs["Blue"], ao.inputs[2]); l.new(ao.outputs["Color"], bsdf.inputs["Base Color"]); l.new(inp.outputs["Albedo Alpha"], bsdf.inputs["Alpha"])
    rough = _math(n, "SUBTRACT", "1 − Smoothness", (-600, -200), 1.0)
    rough_sq = _math(n, "MULTIPLY", "Linear Roughness", (-420, -200))
    l.new(sep_s.outputs["Red"], rough.inputs[1]); l.new(rough.outputs[0], rough_sq.inputs[0]); l.new(rough.outputs[0], rough_sq.inputs[1]); l.new(rough_sq.outputs[0], bsdf.inputs["Roughness"])
    metal = _math(n, "GREATER_THAN", "Metal preset / custom metal", (-430, -320), 0.8980392157)
    l.new(sep_s.outputs["Blue"], metal.inputs[0]); l.new(metal.outputs[0], bsdf.inputs["Metallic"])
    f0 = _math(n, "MINIMUM", "Clamp dielectric F0", (-430, -410), 0.8980392157)
    sqrt_f0, add_f0, sub_f0 = _math(n, "SQRT", "sqrt(F0)", (-260, -410)), _math(n, "ADD", "1 + sqrt(F0)", (-80, -380), 1.0), _math(n, "SUBTRACT", "1 − sqrt(F0)", (-80, -440), 1.0)
    ior = _math(n, "DIVIDE", "IOR from F0", (100, -410))
    l.new(sep_s.outputs["Green"], f0.inputs[0]); l.new(f0.outputs[0], sqrt_f0.inputs[0]); l.new(sqrt_f0.outputs[0], add_f0.inputs[1]); l.new(sqrt_f0.outputs[0], sub_f0.inputs[1]); l.new(add_f0.outputs[0], ior.inputs[0]); l.new(sub_f0.outputs[0], ior.inputs[1]); l.new(ior.outputs[0], bsdf.inputs["IOR"])
    sss_offset = _math(n, "SUBTRACT", "SSS encoded offset", (-430, -510), 0.2549019608)
    sss = _math(n, "DIVIDE", "Subsurface Weight", (-250, -510), 0.7450980392)
    l.new(sep_s.outputs["Blue"], sss_offset.inputs[1]); l.new(sss_offset.outputs[0], sss.inputs[0]); l.new(sss.outputs[0], bsdf.inputs["Subsurface Weight"])
    porosity_scaled = _math(n, "MULTIPLY", "Porosity scaled", (-250, -610), 3.984375)
    porosity_range = _math(n, "LESS_THAN", "Is porosity range", (-430, -660), 0.2549019608)
    porosity = _math(n, "MULTIPLY", "Porosity (0-1)", (-70, -610))
    l.new(sep_s.outputs["Blue"], porosity_scaled.inputs[1]); l.new(sep_s.outputs["Blue"], porosity_range.inputs[1]); l.new(porosity_scaled.outputs[0], porosity.inputs[0]); l.new(porosity_range.outputs[0], porosity.inputs[1]); l.new(porosity.outputs[0], out.inputs["Porosity (0-1)"])
    emission_alpha = _math(n, "MINIMUM", "Clamp emission alpha", (-250, -730), 0.9960784314)
    emission = _math(n, "MULTIPLY", "Emission strength", (-70, -730))
    l.new(inp.outputs["Specular (_s) Alpha (Emission)"], emission_alpha.inputs[1]); l.new(emission_alpha.outputs[0], emission.inputs[0]); l.new(inp.outputs["Emission Strength"], emission.inputs[1]); l.new(inp.outputs["Albedo Color"], bsdf.inputs["Emission Color"]); l.new(emission.outputs[0], bsdf.inputs["Emission Strength"])
    height = _math(n, "SUBTRACT", "Height − 1", (250, -180), 1.0)
    depth = _math(n, "MULTIPLY", "LabPBR depth (25%)", (420, -180), 0.25)
    scale = _math(n, "MULTIPLY", "Effective displacement scale", (580, -180))
    l.new(inp.outputs["Normal (_n) Alpha (Height)"], height.inputs[1]); l.new(height.outputs[0], depth.inputs[1]); l.new(depth.outputs[0], scale.inputs[0]); l.new(inp.outputs["Displacement Scale"], scale.inputs[1]); l.new(scale.outputs[0], disp.inputs["Scale"]); l.new(disp.outputs["Displacement"], out.inputs["Displacement"])
    l.new(bsdf.outputs["BSDF"], out.inputs["BSDF"])
    return ng


def ensure_animated_uv_mapping() -> bpy.types.NodeTree:
    ng = _group("MC_Animated_UV_Mapping", version=UV_TEMPLATE_VERSION)
    if ng.nodes: return ng
    for name, typ, default in (("Vector", "NodeSocketVector", None), ("Current Frame", "NodeSocketFloat", 0.0), ("Next Frame", "NodeSocketFloat", 1.0), ("Blend Factor", "NodeSocketFloat", 0.0), ("Frame Width", "NodeSocketFloat", 16.0), ("Frame Height", "NodeSocketFloat", 16.0), ("Image Width", "NodeSocketFloat", 16.0), ("Image Height", "NodeSocketFloat", 16.0)):
        _socket(ng, name, "INPUT", typ, default)
    for name, typ in (("Current UV", "NodeSocketVector"), ("Next UV", "NodeSocketVector"), ("Blend Factor", "NodeSocketFloat")): _socket(ng, name, "OUTPUT", typ)
    n, l = ng.nodes, ng.links; inp, out = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    sep = n.new("ShaderNodeSeparateXYZ"); combine_current, combine_next = n.new("ShaderNodeCombineXYZ"), n.new("ShaderNodeCombineXYZ")
    combine_current.name, combine_next.name = "Current UV", "Next UV"
    u_scale, v_scale = _math(n, "DIVIDE", "U Frame Scale", (-500, 100)), _math(n, "DIVIDE", "V Frame Scale", (-500, -100))
    u, v = _math(n, "MULTIPLY", "U in Frame", (-300, 100)), _math(n, "MULTIPLY", "V in Frame", (-300, -100))
    l.new(inp.outputs["Vector"], sep.inputs["Vector"]); l.new(inp.outputs["Frame Width"], u_scale.inputs[0]); l.new(inp.outputs["Image Width"], u_scale.inputs[1]); l.new(inp.outputs["Frame Height"], v_scale.inputs[0]); l.new(inp.outputs["Image Height"], v_scale.inputs[1]); l.new(sep.outputs["X"], u.inputs[0]); l.new(u_scale.outputs[0], u.inputs[1]); l.new(sep.outputs["Y"], v.inputs[0]); l.new(v_scale.outputs[0], v.inputs[1])
    for frame_name, combine, label, yloc in (("Current Frame", combine_current, "Current", 80), ("Next Frame", combine_next, "Next", -200)):
        # Input 0 is linked to the frame number below, so the +1 constant
        # must be on input 1.  Leaving it on input 0 is overwritten by the
        # link and causes a half-frame UV offset (the node's default 0.5).
        plus = _math(n, "ADD", label + " + 1", (-100, yloc), 0.0, 1.0); scaled = _math(n, "MULTIPLY", label + " V Scale", (80, yloc)); offset = _math(n, "SUBTRACT", label + " V Offset", (260, yloc), 1.0); final = _math(n, "ADD", label + " V", (440, yloc))
        l.new(inp.outputs[frame_name], plus.inputs[0]); l.new(plus.outputs[0], scaled.inputs[0]); l.new(v_scale.outputs[0], scaled.inputs[1]); l.new(scaled.outputs[0], offset.inputs[1]); l.new(v.outputs[0], final.inputs[0]); l.new(offset.outputs[0], final.inputs[1]); l.new(u.outputs[0], combine.inputs["X"]); l.new(final.outputs[0], combine.inputs["Y"])
    # Image Texture uses XY for flat projection, but forwarding Z makes this
    # group a transparent UV transform and keeps it identical to the proven
    # reference tree for non-flat projections and future reuse.
    l.new(sep.outputs["Z"], combine_current.inputs["Z"]); l.new(sep.outputs["Z"], combine_next.inputs["Z"])
    l.new(combine_current.outputs["Vector"], out.inputs["Current UV"]); l.new(combine_next.outputs["Vector"], out.inputs["Next UV"]); l.new(inp.outputs["Blend Factor"], out.inputs["Blend Factor"])
    return ng


def ensure_animation_scheduler() -> bpy.types.NodeTree:
    ng = _group("MC_Animation_Scheduler_Default", version=SCHEDULER_TEMPLATE_VERSION)
    if ng.nodes: return ng
    _socket(ng, "Total Frames", "INPUT", "NodeSocketInt", 16); _socket(ng, "Frametime", "INPUT", "NodeSocketInt", 1); _socket(ng, "Interpolate", "INPUT", "NodeSocketBool", False)
    for name in ("Current Frame", "Next Frame", "Blend Factor"): _socket(ng, name, "OUTPUT", "NodeSocketFloat")
    n, l = ng.nodes, ng.links; inp, out = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    frame = n.new("ShaderNodeValue"); frame.name = "Timeline Frame"; frame.outputs[0].driver_add("default_value").driver.expression = "frame"
    start = n.new("ShaderNodeValue"); start.name = "Timeline Start"; start.outputs[0].default_value = 1.0
    start_driver = start.outputs[0].driver_add("default_value").driver
    start_driver.expression = "start"
    start_variable = start_driver.variables.new(); start_variable.name = "start"
    start_variable.targets[0].id_type = "SCENE"; start_variable.targets[0].id = bpy.context.scene; start_variable.targets[0].data_path = "frame_start"
    fps = n.new("ShaderNodeValue"); fps.name = "Effective FPS"
    fps_driver = fps.outputs[0].driver_add("default_value").driver
    fps_driver.expression = "fps / fps_base"
    for name, path in (("fps", "render.fps"), ("fps_base", "render.fps_base")):
        variable = fps_driver.variables.new(); variable.name = name
        variable.targets[0].id_type = "SCENE"; variable.targets[0].id = bpy.context.scene; variable.targets[0].data_path = path
    tick = n.new("ShaderNodeValue"); tick.name = "Minecraft Tick Rate"; tick.outputs[0].default_value = 20.0
    elapsed, ticks, mc_tick = _math(n, "SUBTRACT", "Elapsed Frames", (-300, 100)), _math(n, "MULTIPLY", "Ticks Numerator", (-120, 100)), _math(n, "DIVIDE", "MC Tick", (60, 100))
    phase, current_raw, fraction = _math(n, "DIVIDE", "Frame Phase", (240, 100)), _math(n, "FLOOR", "Current Unwrapped", (420, 150)), _math(n, "FRACT", "Frame Fraction", (420, 40))
    current = _math(n, "WRAP", "Current Frame", (600, 150), 0.0); next_raw = _math(n, "ADD", "Next Unwrapped", (600, 50), 0.0, 1.0); next_frame = _math(n, "WRAP", "Next Frame", (780, 50), 0.0); blend = _math(n, "MULTIPLY", "Blend Factor", (600, -80))
    l.new(frame.outputs[0], elapsed.inputs[0]); l.new(start.outputs[0], elapsed.inputs[1])
    l.new(elapsed.outputs[0], ticks.inputs[0]); l.new(tick.outputs[0], ticks.inputs[1])
    l.new(ticks.outputs[0], mc_tick.inputs[0]); l.new(fps.outputs[0], mc_tick.inputs[1])
    l.new(mc_tick.outputs[0], phase.inputs[0]); l.new(inp.outputs["Frametime"], phase.inputs[1])
    l.new(phase.outputs[0], current_raw.inputs[0]); l.new(phase.outputs[0], fraction.inputs[0])
    l.new(current_raw.outputs[0], current.inputs[0]); current.inputs[1].default_value = 0.0; l.new(inp.outputs["Total Frames"], current.inputs[2])
    l.new(current_raw.outputs[0], next_raw.inputs[0]); l.new(next_raw.outputs[0], next_frame.inputs[0]); next_frame.inputs[1].default_value = 0.0; l.new(inp.outputs["Total Frames"], next_frame.inputs[2])
    l.new(fraction.outputs[0], blend.inputs[0]); l.new(inp.outputs["Interpolate"], blend.inputs[1])
    l.new(current.outputs[0], out.inputs["Current Frame"]); l.new(next_frame.outputs[0], out.inputs["Next Frame"]); l.new(blend.outputs[0], out.inputs["Blend Factor"])
    return ng


def ensure_animated_frame_blend() -> bpy.types.NodeTree:
    ng = _group("MC_Animated_Frame_Blend")
    if ng.nodes: return ng
    for name, typ, default in (("Current Color", "NodeSocketColor", (1,1,1,1)), ("Next Color", "NodeSocketColor", (1,1,1,1)), ("Current Alpha", "NodeSocketFloat", 1.0), ("Next Alpha", "NodeSocketFloat", 1.0), ("Blend Factor", "NodeSocketFloat", 0.0)): _socket(ng, name, "INPUT", typ, default)
    _socket(ng, "Color", "OUTPUT", "NodeSocketColor"); _socket(ng, "Alpha", "OUTPUT", "NodeSocketFloat")
    n, l = ng.nodes, ng.links; inp, out = n.new("NodeGroupInput"), n.new("NodeGroupOutput"); color = n.new("ShaderNodeMixRGB"); color.name = "Frame Color Mix"; inverse = _math(n, "SUBTRACT", "Inverse Blend", (0, -100), 1.0); a = _math(n, "MULTIPLY", "Current Alpha Weight", (180, -100)); b = _math(n, "MULTIPLY", "Next Alpha Weight", (180, -200)); total = _math(n, "ADD", "Frame Alpha Mix", (360, -150))
    l.new(inp.outputs["Blend Factor"], color.inputs[0]); l.new(inp.outputs["Current Color"], color.inputs[1]); l.new(inp.outputs["Next Color"], color.inputs[2]); l.new(color.outputs["Color"], out.inputs["Color"]); l.new(inp.outputs["Blend Factor"], inverse.inputs[1]); l.new(inp.outputs["Current Alpha"], a.inputs[0]); l.new(inverse.outputs[0], a.inputs[1]); l.new(inp.outputs["Next Alpha"], b.inputs[0]); l.new(inp.outputs["Blend Factor"], b.inputs[1]); l.new(a.outputs[0], total.inputs[0]); l.new(b.outputs[0], total.inputs[1]); l.new(total.outputs[0], out.inputs["Alpha"])
    return ng


def ensure_all_templates():
    return {"LabPBR 1.3 Decoder": ensure_labpbr_decoder(), "MC_Animated_UV_Mapping": ensure_animated_uv_mapping(), "MC_Animation_Scheduler_Default": ensure_animation_scheduler(), "MC_Animated_Frame_Blend": ensure_animated_frame_blend()}

"""Minecraft animated-texture shader-node groups."""

from __future__ import annotations

import bpy

from .core import add_sockets, ensure_group, finalize_group, link, node


# Version 9 unifies Standalone and Atlas material modes:
# - In Baked UV Mode (Atlas Mode = 1.0, Default), Vector is already pre-mapped
#   into the texture's Frame 0 rectangle by mesh UV transformation.
# - In Unbaked Local Mode (Atlas Mode = 0.0), Vector is local quad UV (0..1, 0..1).
#   The UV is mapped into Frame 0 (top of strip) using Frame/Image dimensions.
# In both modes, Current Frame and Next Frame subtract vertical frame steps
# from the base Frame 0 coordinate.
UV_TEMPLATE_VERSION = 9
# Version 7 adds an explicit Scene frame_current driver variable so Blender's
# dependency graph reliably evaluates animation time during scrubbing and renders.
SCHEDULER_TEMPLATE_VERSION = 7
FRAME_BLEND_TEMPLATE_VERSION = 4


def ensure_animated_uv_mapping() -> bpy.types.NodeTree:
    group = ensure_group("MC_Animated_UV_Mapping", UV_TEMPLATE_VERSION)
    if group.nodes and group.get("mozi_template_complete"):
        return group
    add_sockets(group, (
        ("Vector", "INPUT", "NodeSocketVector", None),
        ("Current Frame", "INPUT", "NodeSocketFloat", 0.0, 0.0, 100000.0),
        ("Next Frame", "INPUT", "NodeSocketFloat", 1.0, 0.0, 100000.0),
        ("Blend Factor", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0),
        ("Frame Width", "INPUT", "NodeSocketFloat", 16.0, 1.0, 16384.0),
        ("Frame Height", "INPUT", "NodeSocketFloat", 16.0, 1.0, 16384.0),
        ("Image Width", "INPUT", "NodeSocketFloat", 16.0, 1.0, 16384.0),
        ("Image Height", "INPUT", "NodeSocketFloat", 16.0, 1.0, 16384.0),
        ("Atlas Mode", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0),
        ("Current UV", "OUTPUT", "NodeSocketVector", None),
        ("Next UV", "OUTPUT", "NodeSocketVector", None),
        ("Blend Factor", "OUTPUT", "NodeSocketFloat", 0.0, 0.0, 1.0),
    ))
    nodes, links = group.nodes, group.links
    group_input = node(nodes, "NodeGroupInput", "Group Input", location=(-1000, 0))
    group_output = node(nodes, "NodeGroupOutput", "Group Output", location=(900, 0))

    # Calculate normalized step size per frame
    frame_step_v = node(nodes, "ShaderNodeMath", "Frame V Step", location=(-750, -100), properties={"operation": "DIVIDE"})
    link(links, group_input, "Frame Height", frame_step_v, "Value[0]")
    link(links, group_input, "Image Height", frame_step_v, "Value[1]")

    frame_step_u = node(nodes, "ShaderNodeMath", "Frame U Step", location=(-750, 100), properties={"operation": "DIVIDE"})
    link(links, group_input, "Frame Width", frame_step_u, "Value[0]")
    link(links, group_input, "Image Width", frame_step_u, "Value[1]")

    # Standalone (Local UV) Branch: Map local 0..1 UV to Frame 0 at the top of the strip
    separate = node(nodes, "ShaderNodeSeparateXYZ", "Separate Local UV", location=(-750, 320))
    link(links, group_input, "Vector", separate, "Vector")

    local_u = node(nodes, "ShaderNodeMath", "Local Frame 0 U", location=(-550, 320), properties={"operation": "MULTIPLY"})
    link(links, separate, "X", local_u, "Value[0]")
    link(links, frame_step_u, "Value", local_u, "Value[1]")

    one_minus_v = node(nodes, "ShaderNodeMath", "1.0 - Local V", location=(-550, 150), properties={"operation": "SUBTRACT"}, inputs={"Value[0]": 1.0})
    link(links, separate, "Y", one_minus_v, "Value[1]")

    v_offset = node(nodes, "ShaderNodeMath", "Local Frame 0 V Offset", location=(-380, 150), properties={"operation": "MULTIPLY"})
    link(links, one_minus_v, "Value", v_offset, "Value[0]")
    link(links, frame_step_v, "Value", v_offset, "Value[1]")

    local_v = node(nodes, "ShaderNodeMath", "Local Frame 0 V", location=(-210, 150), properties={"operation": "SUBTRACT"}, inputs={"Value[0]": 1.0})
    link(links, v_offset, "Value", local_v, "Value[1]")

    local_frame0_vec = node(nodes, "ShaderNodeCombineXYZ", "Local Frame 0 Vector", location=(-40, 240))
    link(links, local_u, "Value", local_frame0_vec, "X")
    link(links, local_v, "Value", local_frame0_vec, "Y")
    link(links, separate, "Z", local_frame0_vec, "Z")

    # Select base Frame 0 UV: Local Frame 0 Vector when Atlas Mode is 0.0, or raw input Vector when Atlas Mode is 1.0
    mix_base = node(nodes, "ShaderNodeMix", "Choose Frame 0 UV", location=(140, 120), properties={"data_type": "VECTOR", "blend_type": "MIX"})
    link(links, group_input, "Atlas Mode", mix_base, "Factor[0]")
    link(links, local_frame0_vec, "Vector", mix_base, "A[1]")
    link(links, group_input, "Vector", mix_base, "B[1]")

    # Advance frames vertically from base Frame 0 UV
    for frame_socket, output_socket, offset_y in (("Current Frame", "Current UV", 120), ("Next Frame", "Next UV", -180)):
        offset = node(nodes, "ShaderNodeMath", f"{frame_socket} V Offset", location=(340, offset_y), properties={"operation": "MULTIPLY"})
        offset_vector = node(nodes, "ShaderNodeCombineXYZ", f"{frame_socket} Offset Vector", location=(510, offset_y))
        offset_vector.inputs["X"].default_value = 0.0
        offset_vector.inputs["Z"].default_value = 0.0
        final_uv = node(nodes, "ShaderNodeVectorMath", output_socket, location=(680, offset_y), properties={"operation": "SUBTRACT"})
        link(links, group_input, frame_socket, offset, "Value[0]")
        link(links, frame_step_v, "Value", offset, "Value[1]")
        link(links, offset, "Value", offset_vector, "Y")
        link(links, mix_base, "Result[1]", final_uv, "Vector[0]")
        link(links, offset_vector, "Vector", final_uv, "Vector[1]")
        link(links, final_uv, "Vector", group_output, output_socket)

    link(links, group_input, "Blend Factor", group_output, "Blend Factor")
    return finalize_group(group)


def ensure_animation_scheduler() -> bpy.types.NodeTree:
    group = ensure_group("MC_Animation_Scheduler_Default", SCHEDULER_TEMPLATE_VERSION)
    if group.nodes and group.get("mozi_template_complete"):
        return group
    add_sockets(group, (
        ("Total Frames", "INPUT", "NodeSocketInt", 16, 1, 100000),
        ("Frametime", "INPUT", "NodeSocketInt", 1, 1, 100000),
        ("Interpolate", "INPUT", "NodeSocketBool", False),
        ("Current Frame", "OUTPUT", "NodeSocketFloat", 0.0, 0.0, 100000.0),
        ("Next Frame", "OUTPUT", "NodeSocketFloat", 0.0, 0.0, 100000.0),
        ("Blend Factor", "OUTPUT", "NodeSocketFloat", 0.0, 0.0, 1.0),
    ))
    nodes, links = group.nodes, group.links
    group_input = node(nodes, "NodeGroupInput", "Group Input", location=(-700, 0)); group_output = node(nodes, "NodeGroupOutput", "Group Output", location=(700, 0))
    frame = node(nodes, "ShaderNodeValue", "Timeline Frame", location=(-700, 160))
    driver = frame.outputs["Value"].driver_add("default_value").driver
    driver.expression = "frame"
    variable = driver.variables.new()
    variable.name = "frame"
    variable.targets[0].id_type = "SCENE"
    variable.targets[0].id = bpy.context.scene
    variable.targets[0].data_path = "frame_current"
    start = node(nodes, "ShaderNodeValue", "Timeline Start", location=(-700, 80)); driver = start.outputs["Value"].driver_add("default_value").driver; driver.expression = "start"; variable = driver.variables.new(); variable.name = "start"; variable.targets[0].id_type = "SCENE"; variable.targets[0].id = bpy.context.scene; variable.targets[0].data_path = "frame_start"
    fps = node(nodes, "ShaderNodeValue", "Effective FPS", location=(-700, -20)); driver = fps.outputs["Value"].driver_add("default_value").driver; driver.expression = "fps / fps_base"
    for variable_name, data_path in (("fps", "render.fps"), ("fps_base", "render.fps_base")):
        variable = driver.variables.new(); variable.name = variable_name; variable.targets[0].id_type = "SCENE"; variable.targets[0].id = bpy.context.scene; variable.targets[0].data_path = data_path
    tick_rate = nodes.new("ShaderNodeValue"); tick_rate.name = "Minecraft Tick Rate"; tick_rate.label = "Minecraft Tick Rate"; tick_rate.location = (-700, -100); tick_rate.outputs["Value"].default_value = 20.0
    elapsed = node(nodes, "ShaderNodeMath", "Elapsed Frames", location=(-500, 120), properties={"operation": "SUBTRACT"}); ticks = node(nodes, "ShaderNodeMath", "Ticks Numerator", location=(-320, 120), properties={"operation": "MULTIPLY"}); mc_tick = node(nodes, "ShaderNodeMath", "MC Tick", location=(-140, 120), properties={"operation": "DIVIDE"}); phase = node(nodes, "ShaderNodeMath", "Frame Phase", location=(40, 120), properties={"operation": "DIVIDE"})
    current_raw = node(nodes, "ShaderNodeMath", "Current Unwrapped", location=(220, 170), properties={"operation": "FLOOR"}); fraction = node(nodes, "ShaderNodeMath", "Frame Fraction", location=(220, 50), properties={"operation": "FRACT"}); current = node(nodes, "ShaderNodeMath", "Current Frame", location=(400, 170), properties={"operation": "WRAP"}, inputs={"Value[2]": 0.0}); next_raw = node(nodes, "ShaderNodeMath", "Next Unwrapped", location=(400, 60), properties={"operation": "ADD"}, inputs={"Value[1]": 1.0}); next_frame = node(nodes, "ShaderNodeMath", "Next Frame", location=(570, 60), properties={"operation": "WRAP"}, inputs={"Value[2]": 0.0}); blend = node(nodes, "ShaderNodeMath", "Blend Factor", location=(400, -70), properties={"operation": "MULTIPLY"})
    link(links, frame, "Value", elapsed, "Value[0]"); link(links, start, "Value", elapsed, "Value[1]"); link(links, elapsed, "Value", ticks, "Value[0]"); link(links, tick_rate, "Value", ticks, "Value[1]"); link(links, ticks, "Value", mc_tick, "Value[0]"); link(links, fps, "Value", mc_tick, "Value[1]"); link(links, mc_tick, "Value", phase, "Value[0]"); link(links, group_input, "Frametime", phase, "Value[1]")
    link(links, phase, "Value", current_raw, "Value[0]"); link(links, phase, "Value", fraction, "Value[0]"); link(links, current_raw, "Value", current, "Value[0]"); link(links, group_input, "Total Frames", current, "Value[1]"); link(links, current_raw, "Value", next_raw, "Value[0]"); link(links, next_raw, "Value", next_frame, "Value[0]"); link(links, group_input, "Total Frames", next_frame, "Value[1]"); link(links, fraction, "Value", blend, "Value[0]"); link(links, group_input, "Interpolate", blend, "Value[1]")
    link(links, current, "Value", group_output, "Current Frame"); link(links, next_frame, "Value", group_output, "Next Frame"); link(links, blend, "Value", group_output, "Blend Factor")
    return finalize_group(group)


def ensure_animated_frame_blend() -> bpy.types.NodeTree:
    group = ensure_group("MC_Animated_Frame_Blend", FRAME_BLEND_TEMPLATE_VERSION)
    if group.nodes and group.get("mozi_template_complete"):
        return group
    add_sockets(group, (
        ("Current Color", "INPUT", "NodeSocketColor", (1, 1, 1, 1)),
        ("Next Color", "INPUT", "NodeSocketColor", (1, 1, 1, 1)),
        ("Current Alpha", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0),
        ("Next Alpha", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0),
        ("Blend Factor", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0),
        ("Color", "OUTPUT", "NodeSocketColor", None),
        ("Alpha", "OUTPUT", "NodeSocketFloat", 0.0, 0.0, 1.0),
    ))
    nodes, links = group.nodes, group.links; group_input = node(nodes, "NodeGroupInput", "Group Input", location=(-300, 0)); group_output = node(nodes, "NodeGroupOutput", "Group Output", location=(400, 0)); color = node(nodes, "ShaderNodeMixRGB", "Frame Color Mix", location=(0, 100)); inverse = node(nodes, "ShaderNodeMath", "Inverse Blend", location=(-30, -100), properties={"operation": "SUBTRACT"}, inputs={"Value[0]": 1.0}); current_weight = node(nodes, "ShaderNodeMath", "Current Alpha Weight", location=(150, -100), properties={"operation": "MULTIPLY"}); next_weight = node(nodes, "ShaderNodeMath", "Next Alpha Weight", location=(150, -200), properties={"operation": "MULTIPLY"}); alpha = node(nodes, "ShaderNodeMath", "Frame Alpha Mix", location=(300, -150), properties={"operation": "ADD"})
    link(links, group_input, "Blend Factor", color, "Factor"); link(links, group_input, "Current Color", color, "Color1"); link(links, group_input, "Next Color", color, "Color2"); link(links, color, "Color", group_output, "Color"); link(links, group_input, "Blend Factor", inverse, "Value[1]"); link(links, group_input, "Current Alpha", current_weight, "Value[0]"); link(links, inverse, "Value", current_weight, "Value[1]"); link(links, group_input, "Next Alpha", next_weight, "Value[0]"); link(links, group_input, "Blend Factor", next_weight, "Value[1]"); link(links, current_weight, "Value", alpha, "Value[0]"); link(links, next_weight, "Value", alpha, "Value[1]"); link(links, alpha, "Value", group_output, "Alpha")
    return finalize_group(group)

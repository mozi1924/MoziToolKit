"""
Foliage Geometry Nodes Generator for MoziToolKit.

Constructs the `MTK_Foliage_Wiggle` geometry node group with zero-drift in-place wiggle,
direction control, and vertex group weighting. Compatible across Blender 4.x and Blender 5.x.
"""

from __future__ import annotations

import bpy
from typing import Any, Optional

NODE_GROUP_NAME = "MTK_Foliage_Wiggle"
MODIFIER_NAME = "MTK_Foliage_Wiggle"


def get_modifier_input_value(mod: bpy.types.NodesModifier, socket_ident: str, default: Any = None) -> Any:
    """Read input value from NodesModifier across Blender versions (4.x IDProperties vs 5.x properties.inputs)."""
    if not mod or not socket_ident:
        return default

    # 1. Blender 5.0+ API: mod.properties.inputs[ident].value
    if hasattr(mod, "properties") and hasattr(mod.properties, "inputs"):
        try:
            sock_obj = getattr(mod.properties.inputs, socket_ident, None)
            if sock_obj is not None and hasattr(sock_obj, "value"):
                return sock_obj.value
        except Exception:
            pass

    # 2. Blender 4.x IDProperty API: mod[ident]
    try:
        if socket_ident in mod:
            return mod[socket_ident]
    except (TypeError, KeyError):
        pass

    return default


def set_modifier_input_value(mod: bpy.types.NodesModifier, socket_ident: str, value: Any) -> bool:
    """Set input value on NodesModifier across Blender versions (4.x IDProperties vs 5.x properties.inputs)."""
    if not mod or not socket_ident:
        return False

    # 1. Blender 5.0+ API: mod.properties.inputs[ident].value = value
    if hasattr(mod, "properties") and hasattr(mod.properties, "inputs"):
        try:
            sock_obj = getattr(mod.properties.inputs, socket_ident, None)
            if sock_obj is not None and hasattr(sock_obj, "value"):
                sock_obj.value = value
                return True
        except Exception:
            pass

    # 2. Blender 4.x IDProperty API: mod[ident] = value
    try:
        mod[socket_ident] = value
        return True
    except (TypeError, KeyError):
        pass

    return False


def get_or_create_foliage_node_group(rebuild: bool = False) -> bpy.types.GeometryNodeTree:
    """Get existing or generate new MTK_Foliage_Wiggle geometry node tree."""
    if not rebuild and NODE_GROUP_NAME in bpy.data.node_groups:
        return bpy.data.node_groups[NODE_GROUP_NAME]

    if NODE_GROUP_NAME in bpy.data.node_groups:
        ng = bpy.data.node_groups[NODE_GROUP_NAME]
    else:
        ng = bpy.data.node_groups.new(name=NODE_GROUP_NAME, type='GeometryNodeTree')

    ng.nodes.clear()
    ng.links.clear()

    group_in = ng.nodes.new("NodeGroupInput")
    group_in.location = (-1200, 0)
    group_out = ng.nodes.new("NodeGroupOutput")
    group_out.location = (1100, 0)

    interface = ng.interface if hasattr(ng, "interface") else None

    def add_input(name: str, in_type: str, default_val=None, min_val=None, max_val=None):
        if interface:
            sock = interface.new_socket(name=name, in_out='INPUT', socket_type=in_type)
            if default_val is not None:
                sock.default_value = default_val
            if min_val is not None:
                sock.min_value = min_val
            if max_val is not None:
                sock.max_value = max_val
            return sock
        else:
            sock = ng.inputs.new(in_type, name)
            if default_val is not None:
                sock.default_value = default_val
            return sock

    def add_output(name: str, out_type: str):
        if interface:
            return interface.new_socket(name=name, in_out='OUTPUT', socket_type=out_type)
        else:
            return ng.outputs.new(out_type, name)

    if interface:
        interface.clear()
    else:
        ng.inputs.clear()
        ng.outputs.clear()

    # Interface sockets
    add_input("Geometry", "NodeSocketGeometry")
    add_input("Selection Group", "NodeSocketString", default_val="MTK_Foliage_All")
    add_input("Wind Direction (Deg)", "NodeSocketFloat", default_val=45.0)
    add_input("Wiggle Amplitude", "NodeSocketFloat", default_val=0.06, min_val=0.0, max_val=0.5)
    add_input("Wiggle Speed", "NodeSocketFloat", default_val=3.0, min_val=0.0, max_val=20.0)
    add_input("Noise Scale", "NodeSocketFloat", default_val=1.2, min_val=0.05, max_val=10.0)
    add_output("Geometry", "NodeSocketGeometry")

    # Set Position Node
    set_pos = ng.nodes.new("GeometryNodeSetPosition")
    set_pos.location = (850, 0)

    # Named Attribute for vertex group weight
    named_attr = ng.nodes.new("GeometryNodeInputNamedAttribute")
    named_attr.data_type = 'FLOAT'
    named_attr.location = (-950, -350)

    # Time & Speed
    time_node = ng.nodes.new("GeometryNodeInputSceneTime")
    time_node.location = (-950, 450)
    time_mul = ng.nodes.new("ShaderNodeMath")
    time_mul.operation = 'MULTIPLY'
    time_mul.location = (-750, 450)

    # Position
    pos_node = ng.nodes.new("GeometryNodeInputPosition")
    pos_node.location = (-950, 200)

    # 4D Noise
    noise_node = ng.nodes.new("ShaderNodeTexNoise")
    noise_node.noise_dimensions = '4D'
    noise_node.location = (-550, 250)
    noise_node.inputs['Roughness'].default_value = 0.5
    noise_node.inputs['Detail'].default_value = 2.0

    # Center Noise [-0.5, 0.5]
    sub_half = ng.nodes.new("ShaderNodeVectorMath")
    sub_half.operation = 'SUBTRACT'
    sub_half.inputs[1].default_value = (0.5, 0.5, 0.5)
    sub_half.location = (-350, 250)

    sep_noise = ng.nodes.new("ShaderNodeSeparateXYZ")
    sep_noise.location = (-150, 250)

    # Wind direction math
    deg2rad = ng.nodes.new("ShaderNodeMath")
    deg2rad.operation = 'RADIANS'
    deg2rad.location = (-950, -50)

    cos_node = ng.nodes.new("ShaderNodeMath")
    cos_node.operation = 'COSINE'
    cos_node.location = (-750, 50)

    sin_node = ng.nodes.new("ShaderNodeMath")
    sin_node.operation = 'SINE'
    sin_node.location = (-750, -150)

    fwd_vec = ng.nodes.new("ShaderNodeCombineXYZ")
    fwd_vec.location = (-500, 50)
    fwd_vec.inputs['Z'].default_value = 0.0

    neg_sin = ng.nodes.new("ShaderNodeMath")
    neg_sin.operation = 'MULTIPLY'
    neg_sin.inputs[1].default_value = -1.0
    neg_sin.location = (-550, -150)

    cross_vec = ng.nodes.new("ShaderNodeCombineXYZ")
    cross_vec.location = (-350, -100)
    cross_vec.inputs['Z'].default_value = 0.0

    fwd_disp = ng.nodes.new("ShaderNodeVectorMath")
    fwd_disp.operation = 'SCALE'
    fwd_disp.location = (50, 150)

    cross_disp = ng.nodes.new("ShaderNodeVectorMath")
    cross_disp.operation = 'SCALE'
    cross_disp.location = (50, -50)

    combined_osc = ng.nodes.new("ShaderNodeVectorMath")
    combined_osc.operation = 'ADD'
    combined_osc.location = (250, 50)

    scale_amp = ng.nodes.new("ShaderNodeVectorMath")
    scale_amp.operation = 'SCALE'
    scale_amp.location = (450, 50)

    scale_weight = ng.nodes.new("ShaderNodeVectorMath")
    scale_weight.operation = 'SCALE'
    scale_weight.location = (650, 0)

    # Links
    links = ng.links
    links.new(group_in.outputs['Geometry'], set_pos.inputs['Geometry'])
    links.new(set_pos.outputs['Geometry'], group_out.inputs['Geometry'])

    links.new(group_in.outputs['Selection Group'], named_attr.inputs['Name'])
    weight_cmp = ng.nodes.new("FunctionNodeCompare")
    weight_cmp.data_type = 'FLOAT'
    weight_cmp.operation = 'GREATER_THAN'
    weight_cmp.inputs['B'].default_value = 0.001
    weight_cmp.location = (-750, -350)
    links.new(named_attr.outputs['Attribute'], weight_cmp.inputs['A'])
    links.new(weight_cmp.outputs['Result'], set_pos.inputs['Selection'])

    links.new(time_node.outputs['Seconds'], time_mul.inputs[0])
    links.new(group_in.outputs['Wiggle Speed'], time_mul.inputs[1])
    links.new(time_mul.outputs['Value'], noise_node.inputs['W'])

    links.new(pos_node.outputs['Position'], noise_node.inputs['Vector'])
    links.new(group_in.outputs['Noise Scale'], noise_node.inputs['Scale'])

    links.new(noise_node.outputs['Color'], sub_half.inputs[0])
    links.new(sub_half.outputs['Vector'], sep_noise.inputs['Vector'])

    links.new(group_in.outputs['Wind Direction (Deg)'], deg2rad.inputs[0])
    links.new(deg2rad.outputs['Value'], cos_node.inputs[0])
    links.new(deg2rad.outputs['Value'], sin_node.inputs[0])

    links.new(cos_node.outputs['Value'], fwd_vec.inputs['X'])
    links.new(sin_node.outputs['Value'], fwd_vec.inputs['Y'])

    links.new(sin_node.outputs['Value'], neg_sin.inputs[0])
    links.new(neg_sin.outputs['Value'], cross_vec.inputs['X'])
    links.new(cos_node.outputs['Value'], cross_vec.inputs['Y'])

    links.new(fwd_vec.outputs['Vector'], fwd_disp.inputs['Vector'])
    links.new(sep_noise.outputs['X'], fwd_disp.inputs['Scale'])

    links.new(cross_vec.outputs['Vector'], cross_disp.inputs['Vector'])
    links.new(sep_noise.outputs['Y'], cross_disp.inputs['Scale'])

    links.new(fwd_disp.outputs['Vector'], combined_osc.inputs[0])
    links.new(cross_disp.outputs['Vector'], combined_osc.inputs[1])

    links.new(combined_osc.outputs['Vector'], scale_amp.inputs['Vector'])
    links.new(group_in.outputs['Wiggle Amplitude'], scale_amp.inputs['Scale'])

    links.new(scale_amp.outputs['Vector'], scale_weight.inputs['Vector'])
    links.new(named_attr.outputs['Attribute'], scale_weight.inputs['Scale'])

    links.new(scale_weight.outputs['Vector'], set_pos.inputs['Offset'])

    return ng


def apply_foliage_modifier(
    obj: bpy.types.Object,
    node_group: Optional[bpy.types.GeometryNodeTree] = None,
    target_scope_group: str = "MTK_Foliage_All",
    wind_direction: Optional[float] = None,
    wiggle_amplitude: Optional[float] = None,
    wiggle_speed: Optional[float] = None,
    noise_scale: Optional[float] = None
) -> bpy.types.NodesModifier:
    """Ensure object has MTK_Foliage_Wiggle modifier and configure its input properties."""
    if not node_group:
        node_group = get_or_create_foliage_node_group()

    mod = None
    for m in obj.modifiers:
        if m.type == 'NODES' and m.node_group == node_group:
            mod = m
            break

    if not mod:
        mod = obj.modifiers.new(name=MODIFIER_NAME, type='NODES')
        mod.node_group = node_group

    if hasattr(node_group, "interface"):
        for item in node_group.interface.items_tree:
            if item.in_out != 'INPUT':
                continue
            ident = item.identifier
            name = item.name
            if name == "Selection Group" and target_scope_group:
                set_modifier_input_value(mod, ident, target_scope_group)
            elif name == "Wind Direction (Deg)" and wind_direction is not None:
                set_modifier_input_value(mod, ident, float(wind_direction))
            elif name == "Wiggle Amplitude" and wiggle_amplitude is not None:
                set_modifier_input_value(mod, ident, float(wiggle_amplitude))
            elif name == "Wiggle Speed" and wiggle_speed is not None:
                set_modifier_input_value(mod, ident, float(wiggle_speed))
            elif name == "Noise Scale" and noise_scale is not None:
                set_modifier_input_value(mod, ident, float(noise_scale))

    return mod

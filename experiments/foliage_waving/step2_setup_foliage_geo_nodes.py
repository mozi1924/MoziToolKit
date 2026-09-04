"""
Setup Foliage Wind / In-Place Wiggle Geometry Nodes.

Architecture of In-Place Wiggle (Zero Drift):
1. Pure Zero-Centered Oscillations:
   - Minecraft shaders (like BSL, Complementary, SEUS) do NOT translate entire blocks far away.
   - They use sine wave harmonics combined with 4D noise where the displacement mean is 0.
   - Wind Direction defines the ANISOTROPY of the wiggle (oscillating back and forth along the wind vector)
     rather than adding a static DC offset!
2. Micro-Wiggle (High Frequency):
   - Vertices wiggle slightly in XY based on sin(pos * freq + time * speed).
3. Wind Sway Modulation:
   - Wind Direction creates an oscillation axis: displacement = WindDir * sin(...) * Amplitude + Perpendicular * cos(...) * MicroAmp.
4. Scale & Clamping:
   - Amplitude is kept small and subtle (default 0.05 ~ 0.1 m), ensuring the leaf mesh stays attached to the tree.
"""

import bpy

def setup_foliage_geometry_nodes(node_group_name="MTK_Foliage_Wiggle", target_obj=None):
    if node_group_name in bpy.data.node_groups:
        ng = bpy.data.node_groups[node_group_name]
    else:
        ng = bpy.data.node_groups.new(name=node_group_name, type='GeometryNodeTree')

    ng.nodes.clear()
    ng.links.clear()

    # Create Group Input & Output nodes
    group_in = ng.nodes.new("NodeGroupInput")
    group_in.location = (-1200, 0)
    group_out = ng.nodes.new("NodeGroupOutput")
    group_out.location = (1100, 0)

    interface = ng.interface if hasattr(ng, "interface") else None

    def add_tree_input(name, in_type, default_val=None, min_val=None, max_val=None):
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

    def add_tree_output(name, out_type):
        if interface:
            return interface.new_socket(name=name, in_out='OUTPUT', socket_type=out_type)
        else:
            return ng.outputs.new(out_type, name)

    if interface:
        interface.clear()
    else:
        ng.inputs.clear()
        ng.outputs.clear()

    # Inputs
    add_tree_input("Geometry", "NodeSocketGeometry")
    add_tree_input("Selection Group", "NodeSocketString", default_val="MTK_Foliage_Leaves")
    add_tree_input("Wind Direction (Deg)", "NodeSocketFloat", default_val=45.0)
    add_tree_input("Wiggle Amplitude", "NodeSocketFloat", default_val=0.06, min_val=0.0, max_val=10)
    add_tree_input("Wiggle Speed", "NodeSocketFloat", default_val=3.0, min_val=0.0, max_val=20.0)
    add_tree_input("Noise Scale", "NodeSocketFloat", default_val=1.2, min_val=0.05, max_val=10.0)
    add_tree_output("Geometry", "NodeSocketGeometry")

    # 1. Set Position Node
    set_pos = ng.nodes.new("GeometryNodeSetPosition")
    set_pos.location = (850, 0)

    # 2. Named Attribute (Float, Vertex Group)
    named_attr = ng.nodes.new("GeometryNodeInputNamedAttribute")
    named_attr.data_type = 'FLOAT'
    named_attr.location = (-950, -350)

    # 3. Time input
    time_node = ng.nodes.new("GeometryNodeInputSceneTime")
    time_node.location = (-950, 450)

    # Time * Speed
    time_mul = ng.nodes.new("ShaderNodeMath")
    time_mul.operation = 'MULTIPLY'
    time_mul.location = (-750, 450)

    # 4. Position input
    pos_node = ng.nodes.new("GeometryNodeInputPosition")
    pos_node.location = (-950, 200)

    # 5. 4D Noise Texture (Pure zero-centered displacement)
    noise_node = ng.nodes.new("ShaderNodeTexNoise")
    noise_node.noise_dimensions = '4D'
    noise_node.location = (-550, 250)
    noise_node.inputs['Roughness'].default_value = 0.5
    noise_node.inputs['Detail'].default_value = 2.0

    # Center noise: subtract 0.5 so range is [-0.5, 0.5] (Strict Zero Mean -> No Drift!)
    sub_half = ng.nodes.new("ShaderNodeVectorMath")
    sub_half.operation = 'SUBTRACT'
    sub_half.inputs[1].default_value = (0.5, 0.5, 0.5)
    sub_half.location = (-350, 250)

    # Separate X and Y from centered noise
    sep_noise = ng.nodes.new("ShaderNodeSeparateXYZ")
    sep_noise.location = (-150, 250)

    # 6. Wind Direction Basis Vectors:
    # Forward Wind Dir: (cos(deg), sin(deg), 0)
    # Perpendicular Cross Wind: (-sin(deg), cos(deg), 0)
    deg2rad = ng.nodes.new("ShaderNodeMath")
    deg2rad.operation = 'RADIANS'
    deg2rad.location = (-950, -50)

    cos_node = ng.nodes.new("ShaderNodeMath")
    cos_node.operation = 'COSINE'
    cos_node.location = (-750, 50)

    sin_node = ng.nodes.new("ShaderNodeMath")
    sin_node.operation = 'SINE'
    sin_node.location = (-750, -150)

    # Forward vector (X=cos, Y=sin, Z=0)
    fwd_vec = ng.nodes.new("ShaderNodeCombineXYZ")
    fwd_vec.location = (-500, 50)
    fwd_vec.inputs['Z'].default_value = 0.0

    # Perpendicular vector (X=-sin, Y=cos, Z=0)
    neg_sin = ng.nodes.new("ShaderNodeMath")
    neg_sin.operation = 'MULTIPLY'
    neg_sin.inputs[1].default_value = -1.0
    neg_sin.location = (-550, -150)

    cross_vec = ng.nodes.new("ShaderNodeCombineXYZ")
    cross_vec.location = (-350, -100)
    cross_vec.inputs['Z'].default_value = 0.0

    # 7. Modulate along wind axes:
    # Main oscillation along wind direction: FwdVec * Noise.X
    fwd_disp = ng.nodes.new("ShaderNodeVectorMath")
    fwd_disp.operation = 'SCALE'
    fwd_disp.location = (50, 150)

    # Secondary cross-oscillation (flutter): CrossVec * (Noise.Y * 0.6)
    cross_disp = ng.nodes.new("ShaderNodeVectorMath")
    cross_disp.operation = 'SCALE'
    cross_disp.location = (50, -50)

    # Combine oscillations: Fwd + Cross
    combined_osc = ng.nodes.new("ShaderNodeVectorMath")
    combined_osc.operation = 'ADD'
    combined_osc.location = (250, 50)

    # 8. Scale by Wiggle Amplitude
    scale_amp = ng.nodes.new("ShaderNodeVectorMath")
    scale_amp.operation = 'SCALE'
    scale_amp.location = (450, 50)

    # 9. Scale by Vertex Group Weight
    scale_weight = ng.nodes.new("ShaderNodeVectorMath")
    scale_weight.operation = 'SCALE'
    scale_weight.location = (650, 0)

    # --- Connections ---
    links = ng.links

    # Geometry
    links.new(group_in.outputs['Geometry'], set_pos.inputs['Geometry'])
    links.new(set_pos.outputs['Geometry'], group_out.inputs['Geometry'])

    # Selection & Weight
    links.new(group_in.outputs['Selection Group'], named_attr.inputs['Name'])
    weight_cmp = ng.nodes.new("FunctionNodeCompare")
    weight_cmp.data_type = 'FLOAT'
    weight_cmp.operation = 'GREATER_THAN'
    weight_cmp.inputs['B'].default_value = 0.001
    weight_cmp.location = (-750, -350)
    links.new(named_attr.outputs['Attribute'], weight_cmp.inputs['A'])
    links.new(weight_cmp.outputs['Result'], set_pos.inputs['Selection'])

    # Time & Noise
    links.new(time_node.outputs['Seconds'], time_mul.inputs[0])
    links.new(group_in.outputs['Wiggle Speed'], time_mul.inputs[1])
    links.new(time_mul.outputs['Value'], noise_node.inputs['W'])

    links.new(pos_node.outputs['Position'], noise_node.inputs['Vector'])
    links.new(group_in.outputs['Noise Scale'], noise_node.inputs['Scale'])

    # Noise centering
    links.new(noise_node.outputs['Color'], sub_half.inputs[0])
    links.new(sub_half.outputs['Vector'], sep_noise.inputs['Vector'])

    # Direction Vectors
    links.new(group_in.outputs['Wind Direction (Deg)'], deg2rad.inputs[0])
    links.new(deg2rad.outputs['Value'], cos_node.inputs[0])
    links.new(deg2rad.outputs['Value'], sin_node.inputs[0])

    links.new(cos_node.outputs['Value'], fwd_vec.inputs['X'])
    links.new(sin_node.outputs['Value'], fwd_vec.inputs['Y'])

    links.new(sin_node.outputs['Value'], neg_sin.inputs[0])
    links.new(neg_sin.outputs['Value'], cross_vec.inputs['X'])
    links.new(cos_node.outputs['Value'], cross_vec.inputs['Y'])

    # Oscillations
    links.new(fwd_vec.outputs['Vector'], fwd_disp.inputs['Vector'])
    links.new(sep_noise.outputs['X'], fwd_disp.inputs['Scale'])

    links.new(cross_vec.outputs['Vector'], cross_disp.inputs['Vector'])
    links.new(sep_noise.outputs['Y'], cross_disp.inputs['Scale'])

    links.new(fwd_disp.outputs['Vector'], combined_osc.inputs[0])
    links.new(cross_disp.outputs['Vector'], combined_osc.inputs[1])

    # Amplitude & Weight Scaling
    links.new(combined_osc.outputs['Vector'], scale_amp.inputs['Vector'])
    links.new(group_in.outputs['Wiggle Amplitude'], scale_amp.inputs['Scale'])

    links.new(scale_amp.outputs['Vector'], scale_weight.inputs['Vector'])
    links.new(named_attr.outputs['Attribute'], scale_weight.inputs['Scale'])

    # Set Position Offset
    links.new(scale_weight.outputs['Vector'], set_pos.inputs['Offset'])

    if target_obj:
        for m in target_obj.modifiers:
            if m.type == 'NODES':
                m.node_group = ng
                break

    print("Updated MTK_Foliage_Wiggle node group with Zero-Drift In-Place Wiggle.")
    return ng

if __name__ == "__main__":
    obj = bpy.context.active_object
    setup_foliage_geometry_nodes(node_group_name="MTK_Foliage_Wiggle", target_obj=obj)

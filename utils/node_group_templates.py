"""Compatibility facade for Mozi shader-node group templates.

New groups live in :mod:`utils.node_groups`.  This module keeps the historic
public API used by the material builder and third-party scripts while the
verified LabPBR graph remains here until it is migrated from its generated
reference form to a declarative specification.
"""

import bpy

from .node_groups import (
    ensure_animated_frame_blend,
    ensure_animated_uv_mapping,
    ensure_animation_scheduler,
)


LABPBR_TEMPLATE_VERSION = 6


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


def _load_labpbr_reference_template() -> bpy.types.NodeTree | None:
    """Install the verified LabPBR graph bundled with the add-on.

    The decoder is a specification-heavy graph.  Keeping its proven Blender
    node tree as an appendable asset prevents the generated version from
    drifting through subtle input-index and node-semantic differences.
    """
    group_name = "LabPBR 1.3 Decoder"
    existing = bpy.data.node_groups.get(group_name)
    if existing and existing.get("mozi_template_version") == LABPBR_TEMPLATE_VERSION:
        return existing

    asset_path = Path(__file__).resolve().parent.parent / "assets" / "labpbr_1_3_decoder_template.blend"
    if not asset_path.exists():
        return None
    template_name = "MOZI_LabPBR_1_3_Decoder_Template"
    with bpy.data.libraries.load(str(asset_path), link=False) as (data_from, data_to):
        if template_name not in data_from.node_groups:
            return None
        data_to.node_groups = [template_name]
    source = bpy.data.node_groups.get(template_name)
    if not source:
        return None

    replacement = source.copy()
    replacement["mozi_template_version"] = LABPBR_TEMPLATE_VERSION
    replacement["mozi_template_source"] = template_name
    bpy.data.node_groups.remove(source)
    if existing:
        for tree in list(bpy.data.node_groups) + [m.node_tree for m in bpy.data.materials if m.use_nodes and m.node_tree]:
            for node in tree.nodes:
                if getattr(node, "node_tree", None) == existing:
                    node.node_tree = replacement
        existing.name = f"{group_name} (Legacy)"
    replacement.name = group_name
    return replacement


def ensure_labpbr_decoder() -> bpy.types.NodeTree:
    """Build the LabPBR 1.3 decoder used by the supplied reference file."""
    reference_template = _load_labpbr_reference_template()
    if reference_template:
        return reference_template
    ng = _group("LabPBR 1.3 Decoder", version=LABPBR_TEMPLATE_VERSION)
    if ng.nodes:
        return ng

    _socket(ng, "BSDF", "OUTPUT", "NodeSocketShader", None)
    _socket(ng, "Displacement", "OUTPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _socket(ng, "Porosity (0-1)", "OUTPUT", "NodeSocketFloat", 0.0)
    _socket(ng, "Enable PBR (0-1)", "INPUT", "NodeSocketFloat", 1.0)
    _socket(ng, "Albedo Color", "INPUT", "NodeSocketColor", (0.8, 0.8, 0.8, 1.0))
    _socket(ng, "Albedo Alpha", "INPUT", "NodeSocketFloat", 1.0)
    _socket(ng, "Normal (_n) Color", "INPUT", "NodeSocketColor", (0.5, 0.5, 1.0, 1.0))
    _socket(ng, "Normal (_n) Alpha (Height)", "INPUT", "NodeSocketFloat", 1.0)
    _socket(ng, "Specular (_s) Color", "INPUT", "NodeSocketColor", (0.292893, 0.04, 0.0, 1.0))
    _socket(ng, "Specular (_s) Alpha (Emission)", "INPUT", "NodeSocketFloat", 0.0)
    _socket(ng, "Displacement Scale", "INPUT", "NodeSocketFloat", 0.05)
    _socket(ng, "Emission Strength", "INPUT", "NodeSocketFloat", 1.0)

    n, l = ng.nodes, ng.links
    node_0 = n.new("NodeGroupInput")
    node_0.name = "组输入"
    node_0.location = (-1415.62, 806.92)

    node_1 = n.new("NodeGroupOutput")
    node_1.name = "组输出"
    node_1.location = (1501.88, 381.74)

    node_2 = n.new("ShaderNodeBsdfPrincipled")
    node_2.name = "LabPBR Principled BSDF"
    node_2.label = "LabPBR 1.3 Material"
    node_2.location = (1199.38, 324.4)
    node_2.inputs[5].default_value = False
    node_2.inputs[7].default_value = 0.0
    node_2.inputs[8].default_value = 0.0
    node_2.inputs[10].default_value = (1.0, 0.2, 0.1)
    node_2.inputs[11].default_value = 0.005
    node_2.inputs[12].default_value = 1.4
    node_2.inputs[13].default_value = 0.0
    node_2.inputs[14].default_value = 0.5
    node_2.inputs[15].default_value = (1.0, 1.0, 1.0, 1.0)
    node_2.inputs[16].default_value = 0.0
    node_2.inputs[17].default_value = 0.0
    node_2.inputs[18].default_value = (0.0, 0.0, 0.0)
    node_2.inputs[19].default_value = 0.0
    node_2.inputs[20].default_value = 0.0
    node_2.inputs[21].default_value = 0.03
    node_2.inputs[22].default_value = 1.5
    node_2.inputs[23].default_value = (1.0, 1.0, 1.0, 1.0)
    node_2.inputs[24].default_value = (0.0, 0.0, 0.0)
    node_2.inputs[25].default_value = 0.0
    node_2.inputs[26].default_value = 0.5
    node_2.inputs[27].default_value = (1.0, 1.0, 1.0, 1.0)
    node_2.inputs[30].default_value = 0.0
    node_2.inputs[31].default_value = 1.33

    node_3 = n.new("ShaderNodeDisplacement")
    node_3.name = "LabPBR Height Displacement"
    node_3.location = (601.88, 505.48)
    node_3.inputs[1].default_value = 0.0
    node_3.inputs[2].default_value = 0.01
    node_3.inputs[3].default_value = (0.0, 0.0, 0.0)

    node_4 = n.new("ShaderNodeSeparateColor")
    node_4.name = "Decode _n (DirectX)"
    node_4.location = (77.09, 2134.99)

    node_5 = n.new("ShaderNodeSeparateColor")
    node_5.name = "Decode _s"
    node_5.location = (-3.12, -3142.41)

    node_6 = n.new("ShaderNodeMixRGB")
    node_6.name = "Albedo × Material AO"
    node_6.blend_type = "MULTIPLY"
    node_6.location = (304.59, 2368.97)
    node_6.inputs[0].default_value = 1.0

    node_7 = n.new("ShaderNodeMath")
    node_7.name = "Normal X: 2R − 1"
    node_7.label = "Normal X: 2R − 1"
    node_7.location = (304.59, 1758.97)
    node_7.operation = "MULTIPLY_ADD"
    node_7.inputs[1].default_value = 2.0
    node_7.inputs[2].default_value = -1.0

    node_8 = n.new("ShaderNodeMath")
    node_8.name = "Normal Y: 1 − 2G"
    node_8.label = "Normal Y: 1 − 2G"
    node_8.location = (304.59, 2153.97)
    node_8.operation = "MULTIPLY_ADD"
    node_8.inputs[1].default_value = -2.0
    node_8.inputs[2].default_value = 1.0

    node_9 = n.new("ShaderNodeMath")
    node_9.name = "X²"
    node_9.label = "X²"
    node_9.location = (519.59, 1883.94)
    node_9.operation = "MULTIPLY"
    node_9.inputs[2].default_value = 0.5

    node_10 = n.new("ShaderNodeMath")
    node_10.name = "Y²"
    node_10.label = "Y²"
    node_10.location = (519.59, 2081.94)
    node_10.operation = "MULTIPLY"
    node_10.inputs[2].default_value = 0.5

    node_11 = n.new("ShaderNodeMath")
    node_11.name = "X² + Y²"
    node_11.label = "X² + Y²"
    node_11.location = (777.09, 1982.94)
    node_11.operation = "ADD"
    node_11.inputs[2].default_value = 0.5

    node_12 = n.new("ShaderNodeMath")
    node_12.name = "1 − X² − Y²"
    node_12.label = "1 − X² − Y²"
    node_12.location = (1042.09, 1982.94)
    node_12.operation = "SUBTRACT"
    node_12.inputs[0].default_value = 1.0
    node_12.inputs[2].default_value = 0.5

    node_13 = n.new("ShaderNodeMath")
    node_13.name = "Clamp normal Z"
    node_13.label = "Clamp normal Z"
    node_13.location = (1269.59, 1982.94)
    node_13.operation = "MAXIMUM"
    node_13.inputs[1].default_value = 0.0
    node_13.inputs[2].default_value = 0.5

    node_14 = n.new("ShaderNodeMath")
    node_14.name = "Reconstructed normal Z"
    node_14.label = "Reconstructed normal Z"
    node_14.location = (1559.59, 1982.94)
    node_14.operation = "SQRT"
    node_14.inputs[1].default_value = 0.5
    node_14.inputs[2].default_value = 0.5

    node_15 = n.new("ShaderNodeMath")
    node_15.name = "Encode X"
    node_15.label = "Encode X"
    node_15.location = (1559.59, 1751.44)
    node_15.operation = "MULTIPLY_ADD"
    node_15.inputs[1].default_value = 0.5
    node_15.inputs[2].default_value = 0.5

    node_16 = n.new("ShaderNodeMath")
    node_16.name = "Encode Y"
    node_16.label = "Encode Y"
    node_16.location = (1559.59, 2274.44)
    node_16.operation = "MULTIPLY_ADD"
    node_16.inputs[1].default_value = 0.5
    node_16.inputs[2].default_value = 0.5

    node_17 = n.new("ShaderNodeCombineColor")
    node_17.name = "Reconstructed DirectX Normal"
    node_17.location = (1787.09, 2003.94)

    node_18 = n.new("ShaderNodeNormalMap")
    node_18.name = "LabPBR Normal Map"
    node_18.location = (2044.59, 2003.94)

    node_19 = n.new("ShaderNodeMath")
    node_19.name = "1 − Smoothness"
    node_19.label = "1 − Smoothness"
    node_19.location = (261.88, -3061.98)
    node_19.operation = "SUBTRACT"
    node_19.inputs[0].default_value = 1.0
    node_19.inputs[2].default_value = 0.5

    node_20 = n.new("ShaderNodeMath")
    node_20.name = "Linear Roughness"
    node_20.label = "Linear Roughness"
    node_20.location = (489.38, -3061.98)
    node_20.operation = "MULTIPLY"
    node_20.inputs[2].default_value = 0.5

    node_21 = n.new("ShaderNodeMath")
    node_21.name = "Clamp dielectric F0"
    node_21.label = "Clamp dielectric F0"
    node_21.location = (261.88, -2687.98)
    node_21.operation = "MINIMUM"
    node_21.inputs[1].default_value = 0.8980392157
    node_21.inputs[2].default_value = 0.5

    node_22 = n.new("ShaderNodeMath")
    node_22.name = "sqrt(F0)"
    node_22.label = "sqrt(F0)"
    node_22.location = (489.38, -2687.98)
    node_22.operation = "SQRT"
    node_22.inputs[1].default_value = 0.5
    node_22.inputs[2].default_value = 0.5

    node_23 = n.new("ShaderNodeMath")
    node_23.name = "1 + sqrt(F0)"
    node_23.label = "1 + sqrt(F0)"
    node_23.location = (779.38, -2570.41)
    node_23.operation = "ADD"
    node_23.inputs[1].default_value = 1.0
    node_23.inputs[2].default_value = 0.5

    node_24 = n.new("ShaderNodeMath")
    node_24.name = "1 − sqrt(F0)"
    node_24.label = "1 − sqrt(F0)"
    node_24.location = (779.38, -2768.41)
    node_24.operation = "SUBTRACT"
    node_24.inputs[0].default_value = 1.0
    node_24.inputs[2].default_value = 0.5

    node_25 = n.new("ShaderNodeMath")
    node_25.name = "IOR from F0"
    node_25.label = "IOR from F0"
    node_25.location = (1006.88, -2687.98)
    node_25.operation = "DIVIDE"
    node_25.inputs[2].default_value = 0.5

    node_26 = n.new("ShaderNodeMath")
    node_26.name = "Metal preset / custom metal"
    node_26.label = "Metal preset / custom metal"
    node_26.location = (489.38, -2863.98)
    node_26.operation = "GREATER_THAN"
    node_26.inputs[1].default_value = 0.8980392157
    node_26.inputs[2].default_value = 0.5

    node_27 = n.new("ShaderNodeMath")
    node_27.name = "SSS encoded offset"
    node_27.label = "SSS encoded offset"
    node_27.location = (261.88, -3478.89)
    node_27.operation = "SUBTRACT"
    node_27.inputs[1].default_value = 0.2549019608
    node_27.inputs[2].default_value = 0.5

    node_28 = n.new("ShaderNodeMath")
    node_28.name = "Subsurface Weight"
    node_28.label = "Subsurface Weight"
    node_28.location = (489.38, -3457.98)
    node_28.operation = "DIVIDE"
    node_28.inputs[1].default_value = 0.7450980392
    node_28.inputs[2].default_value = 0.5

    node_29 = n.new("ShaderNodeMath")
    node_29.name = "Porosity scaled"
    node_29.label = "Porosity scaled"
    node_29.location = (261.88, -3280.89)
    node_29.operation = "MULTIPLY"
    node_29.inputs[1].default_value = 3.984375
    node_29.inputs[2].default_value = 0.5

    node_30 = n.new("ShaderNodeMath")
    node_30.name = "Is porosity range"
    node_30.label = "Is porosity range"
    node_30.location = (261.88, -3676.89)
    node_30.operation = "LESS_THAN"
    node_30.inputs[1].default_value = 0.2549019608
    node_30.inputs[2].default_value = 0.5

    node_31 = n.new("ShaderNodeMath")
    node_31.name = "Porosity (0-1)"
    node_31.label = "Porosity (0-1)"
    node_31.location = (489.38, -3655.98)
    node_31.operation = "MULTIPLY"
    node_31.inputs[2].default_value = 0.5

    node_32 = n.new("ShaderNodeMath")
    node_32.name = "Clamp emission alpha"
    node_32.label = "Clamp emission alpha"
    node_32.location = (-3.12, -3874.89)
    node_32.operation = "MINIMUM"
    node_32.inputs[1].default_value = 0.9960784314
    node_32.inputs[2].default_value = 0.5

    node_33 = n.new("ShaderNodeMath")
    node_33.name = "Emission strength"
    node_33.label = "Emission strength"
    node_33.location = (261.88, -3874.89)
    node_33.operation = "MULTIPLY"
    node_33.inputs[2].default_value = 0.5

    node_34 = n.new("ShaderNodeMath")
    node_34.name = "Height − 1"
    node_34.label = "Height − 1"
    node_34.location = (77.09, 1521.97)
    node_34.operation = "SUBTRACT"
    node_34.inputs[1].default_value = 1.0
    node_34.inputs[2].default_value = 0.5

    node_35 = n.new("ShaderNodeMath")
    node_35.name = "LabPBR depth (25%)"
    node_35.label = "LabPBR depth (25%)"
    node_35.location = (304.59, 1521.97)
    node_35.operation = "MULTIPLY"
    node_35.inputs[1].default_value = 0.25
    node_35.inputs[2].default_value = 0.5

    node_36 = n.new("ShaderNodeMath")
    node_36.name = "Effective displacement scale"
    node_36.label = "Effective displacement scale"
    node_36.location = (519.59, 1488.48)
    node_36.operation = "MULTIPLY"
    node_36.inputs[2].default_value = 0.5

    node_37 = n.new("NodeFrame")
    node_37.name = "Optional _n: DirectX normal, AO, height"
    node_37.label = "Optional _n: DirectX normal, AO, height"
    node_37.location = (-1185.22, -706.0)

    node_38 = n.new("NodeFrame")
    node_38.name = "Optional _s: smoothness, F0, metal, porosity / SSS, emission"
    node_38.label = "Optional _s: smoothness, F0, metal, porosity / SSS, emission"
    node_38.location = (-405.0, 1570.0)

    node_39 = n.new("ShaderNodeMath")
    node_39.name = "Enable LabPBR"
    node_39.label = "Enable LabPBR"
    node_39.location = (84.38, 35.08)
    node_39.operation = "MULTIPLY"
    node_39.inputs[1].default_value = 1.0
    node_39.inputs[2].default_value = 0.5

    node_40 = n.new("ShaderNodeMix")
    node_40.name = "Enable AO"
    node_40.label = "Enable AO"
    node_40.location = (374.38, 1992.97)
    node_40.data_type = "RGBA"
    node_40.blend_type = "MIX"
    node_40.inputs[1].default_value = (0.5, 0.5, 0.5)
    node_40.inputs[2].default_value = 0.0
    node_40.inputs[3].default_value = 0.0
    node_40.inputs[4].default_value = (0.0, 0.0, 0.0)
    node_40.inputs[5].default_value = (0.0, 0.0, 0.0)

    node_41 = n.new("ShaderNodeMix")
    node_41.name = "Enable Roughness"
    node_41.label = "Enable Roughness"
    node_41.location = (374.38, -266.5)
    node_41.data_type = "FLOAT"
    node_41.blend_type = "MIX"
    node_41.inputs[1].default_value = (0.5, 0.5, 0.5)
    node_41.inputs[2].default_value = 0.5
    node_41.inputs[4].default_value = (0.0, 0.0, 0.0)
    node_41.inputs[5].default_value = (0.0, 0.0, 0.0)
    node_41.inputs[6].default_value = (0.5, 0.5, 0.5, 1.0)
    node_41.inputs[7].default_value = (0.5, 0.5, 0.5, 1.0)

    node_42 = n.new("ShaderNodeMath")
    node_42.name = "Enable Metallic"
    node_42.label = "Enable Metallic"
    node_42.location = (374.38, -68.5)
    node_42.operation = "MULTIPLY"
    node_42.inputs[2].default_value = 0.5

    node_43 = n.new("ShaderNodeMix")
    node_43.name = "Enable F0 / IOR"
    node_43.label = "Enable F0 / IOR"
    node_43.location = (869.38, -359.75)
    node_43.data_type = "FLOAT"
    node_43.blend_type = "MIX"
    node_43.inputs[1].default_value = (0.5, 0.5, 0.5)
    node_43.inputs[2].default_value = 1.5
    node_43.inputs[4].default_value = (0.0, 0.0, 0.0)
    node_43.inputs[5].default_value = (0.0, 0.0, 0.0)
    node_43.inputs[6].default_value = (0.5, 0.5, 0.5, 1.0)
    node_43.inputs[7].default_value = (0.5, 0.5, 0.5, 1.0)

    node_44 = n.new("ShaderNodeMath")
    node_44.name = "Enable SSS"
    node_44.label = "Enable SSS"
    node_44.location = (374.38, -544.41)
    node_44.operation = "MULTIPLY"
    node_44.inputs[2].default_value = 0.5

    node_45 = n.new("ShaderNodeMath")
    node_45.name = "Enable Emission"
    node_45.label = "Enable Emission"
    node_45.location = (374.38, -2552.89)
    node_45.operation = "MULTIPLY"
    node_45.inputs[2].default_value = 0.5

    node_46 = n.new("ShaderNodeMath")
    node_46.name = "Enable Displacement"
    node_46.label = "Enable Displacement"
    node_46.location = (374.38, 505.48)
    node_46.operation = "MULTIPLY"
    node_46.inputs[2].default_value = 0.5

    node_47 = n.new("ShaderNodeMath")
    node_47.name = "Enable Porosity"
    node_47.label = "Enable Porosity"
    node_47.location = (374.38, -742.41)
    node_47.operation = "MULTIPLY"
    node_47.inputs[2].default_value = 0.5

    node_48 = n.new("ShaderNodeMath")
    node_48.name = "Emission alpha is data (not 255)"
    node_48.label = "Alpha 255 = no emission"
    node_48.location = (-408.12, -2552.89)
    node_48.operation = "LESS_THAN"
    node_48.inputs[1].default_value = 1.0
    node_48.inputs[2].default_value = 0.5

    node_49 = n.new("ShaderNodeMath")
    node_49.name = "Artist Emission Multiplier"
    node_49.label = "Artist emission multiplier"
    node_49.location = (84.38, -167.5)
    node_49.operation = "MULTIPLY"
    node_49.inputs[2].default_value = 0.5

    node_50 = n.new("ShaderNodeMath")
    node_50.name = "Enable emission after artist multiplier"
    node_50.label = "Enable emission"
    node_50.location = (374.38, 129.5)
    node_50.operation = "MULTIPLY"
    node_50.inputs[2].default_value = 0.5

    node_51 = n.new("NodeReroute"); node_51.name = "转接点"; node_51.location = (-1108.12, 2050.97)
    node_52 = n.new("NodeReroute"); node_52.name = "转接点.001"; node_52.location = (-968.12, 2050.97)
    node_53 = n.new("NodeReroute"); node_53.name = "转接点.002"; node_53.location = (-1108.12, -1700.75)
    node_54 = n.new("NodeReroute"); node_54.name = "转接点.003"; node_54.location = (444.59, 1323.97)
    node_55 = n.new("NodeReroute"); node_55.name = "转接点.004"; node_55.location = (261.88, -2973.32)
    node_56 = n.new("NodeReroute"); node_56.name = "转接点.005"; node_56.location = (84.38, -2662.23)
    node_57 = n.new("NodeReroute"); node_57.name = "转接点.006"; node_57.location = (-1108.12, -2661.65)
    node_58 = n.new("NodeReroute"); node_58.name = "转接点.007"; node_58.location = (-525.62, -2661.65)
    node_59 = n.new("NodeReroute"); node_59.name = "转接点.008"; node_59.location = (-1108.12, -74.14)
    node_60 = n.new("NodeReroute"); node_60.name = "转接点.009"; node_60.location = (-1108.12, -298.71)
    node_61 = n.new("NodeReroute"); node_61.name = "转接点.010"; node_61.location = (519.59, 1642.44)
    node_62 = n.new("NodeReroute"); node_62.name = "转接点.011"; node_62.location = (519.59, 2165.44)
    node_63 = n.new("NodeReroute"); node_63.name = "转接点.012"; node_63.location = (-408.12, 396.45)
    node_64 = n.new("NodeReroute"); node_64.name = "转接点.013"; node_64.location = (-665.62, 1789.71)
    node_65 = n.new("NodeReroute"); node_65.name = "转接点.014"; node_65.location = (374.38, 244.47)
    node_66 = n.new("NodeReroute"); node_66.name = "转接点.015"; node_66.location = (741.88, 244.47)
    node_67 = n.new("NodeReroute"); node_67.name = "转接点.016"; node_67.location = (1019.38, -301.75)
    node_68 = n.new("NodeReroute"); node_68.name = "转接点.017"; node_68.location = (1019.38, -579.75)
    node_69 = n.new("NodeReroute"); node_69.name = "转接点.018"; node_69.location = (1019.38, -103.75)
    node_70 = n.new("NodeReroute"); node_70.name = "转接点.019"; node_70.location = (224.38, 2050.97)
    node_71 = n.new("NodeReroute"); node_71.name = "转接点.020"; node_71.location = (1019.38, 94.29)
    node_72 = n.new("NodeReroute"); node_72.name = "转接点.021"; node_72.location = (1019.38, 1957.71)
    node_73 = n.new("NodeReroute"); node_73.name = "转接点.022"; node_73.location = (1439.38, 470.45)
    node_74 = n.new("NodeReroute"); node_74.name = "转接点.023"; node_74.location = (1439.38, -777.44)
    node_75 = n.new("NodeReroute"); node_75.name = "转接点.024"; node_75.location = (1019.38, 2050.97)
    node_76 = n.new("NodeReroute"); node_76.name = "转接点.025"; node_76.location = (-1108.12, 2108.97)
    node_77 = n.new("NodeReroute"); node_77.name = "转接点.026"; node_77.location = (1019.38, 2108.97)

    # Parents (Frames)
    for n_child in (node_4, node_6, node_7, node_8, node_9, node_10, node_11, node_12, node_13, node_14, node_15, node_16, node_17, node_18, node_34, node_35, node_36, node_54, node_61, node_62):
        n_child.parent = node_37
    for n_child in (node_5, node_19, node_20, node_21, node_22, node_23, node_24, node_25, node_26, node_27, node_28, node_29, node_30, node_31, node_32, node_33, node_55):
        n_child.parent = node_38

    # Links
    l.new(node_0.outputs[3], node_4.inputs[0])
    l.new(node_4.outputs[2], node_6.inputs[2])
    l.new(node_4.outputs[0], node_7.inputs[0])
    l.new(node_4.outputs[1], node_8.inputs[0])
    l.new(node_7.outputs[0], node_9.inputs[0])
    l.new(node_7.outputs[0], node_9.inputs[1])
    l.new(node_8.outputs[0], node_10.inputs[0])
    l.new(node_8.outputs[0], node_10.inputs[1])
    l.new(node_9.outputs[0], node_11.inputs[0])
    l.new(node_10.outputs[0], node_11.inputs[1])
    l.new(node_11.outputs[0], node_12.inputs[1])
    l.new(node_12.outputs[0], node_13.inputs[0])
    l.new(node_13.outputs[0], node_14.inputs[0])
    l.new(node_15.outputs[0], node_17.inputs[0])
    l.new(node_16.outputs[0], node_17.inputs[1])
    l.new(node_14.outputs[0], node_17.inputs[2])
    l.new(node_17.outputs[0], node_18.inputs[1])
    l.new(node_18.outputs[0], node_2.inputs[6])
    l.new(node_5.outputs[0], node_19.inputs[1])
    l.new(node_19.outputs[0], node_20.inputs[0])
    l.new(node_19.outputs[0], node_20.inputs[1])
    l.new(node_5.outputs[1], node_21.inputs[0])
    l.new(node_21.outputs[0], node_22.inputs[0])
    l.new(node_22.outputs[0], node_23.inputs[0])
    l.new(node_22.outputs[0], node_24.inputs[1])
    l.new(node_23.outputs[0], node_25.inputs[0])
    l.new(node_24.outputs[0], node_25.inputs[1])
    l.new(node_5.outputs[2], node_27.inputs[0])
    l.new(node_27.outputs[0], node_28.inputs[0])
    l.new(node_5.outputs[2], node_29.inputs[0])
    l.new(node_5.outputs[2], node_30.inputs[0])
    l.new(node_29.outputs[0], node_31.inputs[0])
    l.new(node_30.outputs[0], node_31.inputs[1])
    l.new(node_0.outputs[4], node_34.inputs[0])
    l.new(node_34.outputs[0], node_35.inputs[0])
    l.new(node_35.outputs[0], node_36.inputs[0])
    l.new(node_2.outputs[0], node_1.inputs[0])
    l.new(node_39.outputs[0], node_40.inputs[0])
    l.new(node_39.outputs[0], node_41.inputs[0])
    l.new(node_20.outputs[0], node_41.inputs[3])
    l.new(node_26.outputs[0], node_42.inputs[0])
    l.new(node_39.outputs[0], node_42.inputs[1])
    l.new(node_25.outputs[0], node_43.inputs[3])
    l.new(node_43.outputs[0], node_2.inputs[3])
    l.new(node_28.outputs[0], node_44.inputs[0])
    l.new(node_39.outputs[0], node_44.inputs[1])
    l.new(node_39.outputs[0], node_45.inputs[1])
    l.new(node_39.outputs[0], node_46.inputs[1])
    l.new(node_46.outputs[0], node_3.inputs[0])
    l.new(node_31.outputs[0], node_47.inputs[0])
    l.new(node_39.outputs[0], node_47.inputs[1])
    l.new(node_32.outputs[0], node_33.inputs[0])
    l.new(node_48.outputs[0], node_33.inputs[1])
    l.new(node_33.outputs[0], node_49.inputs[0])
    l.new(node_49.outputs[0], node_50.inputs[0])
    l.new(node_39.outputs[0], node_50.inputs[1])
    l.new(node_0.outputs[1], node_51.inputs[0])
    l.new(node_0.outputs[0], node_59.inputs[0])
    l.new(node_0.outputs[8], node_60.inputs[0])
    l.new(node_0.outputs[2], node_76.inputs[0])
    l.new(node_0.outputs[5], node_53.inputs[0])
    l.new(node_0.outputs[6], node_57.inputs[0])
    l.new(node_0.outputs[7], node_54.inputs[0])
    l.new(node_3.outputs[0], node_73.inputs[0])
    l.new(node_5.outputs[1], node_55.inputs[0])
    l.new(node_6.outputs[0], node_64.inputs[0])
    l.new(node_7.outputs[0], node_61.inputs[0])
    l.new(node_8.outputs[0], node_62.inputs[0])
    l.new(node_33.outputs[0], node_56.inputs[0])
    l.new(node_36.outputs[0], node_63.inputs[0])
    l.new(node_39.outputs[0], node_65.inputs[0])
    l.new(node_40.outputs[2], node_72.inputs[0])
    l.new(node_41.outputs[0], node_67.inputs[0])
    l.new(node_42.outputs[0], node_69.inputs[0])
    l.new(node_44.outputs[0], node_68.inputs[0])
    l.new(node_47.outputs[0], node_74.inputs[0])
    l.new(node_50.outputs[0], node_71.inputs[0])
    l.new(node_51.outputs[0], node_52.inputs[0])
    l.new(node_59.outputs[0], node_39.inputs[0])
    l.new(node_60.outputs[0], node_49.inputs[1])
    l.new(node_76.outputs[0], node_77.inputs[0])
    l.new(node_53.outputs[0], node_5.inputs[0])
    l.new(node_57.outputs[0], node_58.inputs[0])
    l.new(node_55.outputs[0], node_26.inputs[0])
    l.new(node_64.outputs[0], node_40.inputs[7])
    l.new(node_61.outputs[0], node_15.inputs[0])
    l.new(node_62.outputs[0], node_16.inputs[0])
    l.new(node_56.outputs[0], node_45.inputs[0])
    l.new(node_63.outputs[0], node_46.inputs[0])
    l.new(node_65.outputs[0], node_66.inputs[0])
    l.new(node_52.outputs[0], node_6.inputs[1])
    l.new(node_52.outputs[0], node_70.inputs[0])
    l.new(node_54.outputs[0], node_36.inputs[1])
    l.new(node_58.outputs[0], node_32.inputs[0])
    l.new(node_58.outputs[0], node_48.inputs[0])
    l.new(node_70.outputs[0], node_40.inputs[6])
    l.new(node_70.outputs[0], node_75.inputs[0])
    l.new(node_66.outputs[0], node_18.inputs[0])
    l.new(node_66.outputs[0], node_43.inputs[0])
    l.new(node_77.outputs[0], node_2.inputs[4])
    l.new(node_75.outputs[0], node_2.inputs[28])
    l.new(node_72.outputs[0], node_2.inputs[0])
    l.new(node_71.outputs[0], node_2.inputs[29])
    l.new(node_69.outputs[0], node_2.inputs[1])
    l.new(node_67.outputs[0], node_2.inputs[2])
    l.new(node_68.outputs[0], node_2.inputs[9])
    l.new(node_73.outputs[0], node_1.inputs[1])
    l.new(node_74.outputs[0], node_1.inputs[2])

    return ng


def ensure_all_templates():
    return {"LabPBR 1.3 Decoder": ensure_labpbr_decoder(), "MC_Animated_UV_Mapping": ensure_animated_uv_mapping(), "MC_Animation_Scheduler_Default": ensure_animation_scheduler(), "MC_Animated_Frame_Blend": ensure_animated_frame_blend()}

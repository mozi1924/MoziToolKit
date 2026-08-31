"""LabPBR decoder node group generator and reference contract verification."""

from __future__ import annotations

import bpy

from .core import add_sockets, ensure_group, finalize_group, link, node


LABPBR_GROUP_NAME = "LabPBR 1.3 Decoder"
LABPBR_TEMPLATE_VERSION = 14

# Captured from the verified in-Blender decoder and its appended reference.
# The graph contains 55 functional nodes and 91 effective links with Random Walk SSS,
# boolean Thin Wall transmission support, hardcoded emission direct input,
# Transmission Weight physical refraction decoding, perceptual roughness fix,
# and non-negative SSS clamping.
LABPBR_REFERENCE_LAYOUT_NODE_COUNT = 90
LABPBR_REFERENCE_LAYOUT_LINK_COUNT = 129
LABPBR_REFERENCE_NODE_COUNT = 59
LABPBR_REFERENCE_LINK_COUNT = 97
LABPBR_REFERENCE_FRAMES = frozenset({
    "Optional _n: DirectX normal, AO, height",
    "Optional _s: smoothness, F0, metal, porosity / SSS, emission",
})
LABPBR_INTERFACE = (
    ("BSDF", "OUTPUT", "NodeSocketShader"),
    ("Displacement", "OUTPUT", "NodeSocketVector"),
    ("Porosity (0-1)", "OUTPUT", "NodeSocketFloat"),
    ("Enable PBR (0-1)", "INPUT", "NodeSocketFloat"),
    ("Albedo Color", "INPUT", "NodeSocketColor"),
    ("Albedo Alpha", "INPUT", "NodeSocketFloat"),
    ("Normal (_n) Color", "INPUT", "NodeSocketColor"),
    ("Normal (_n) Alpha (Height)", "INPUT", "NodeSocketFloat"),
    ("Specular (_s) Color", "INPUT", "NodeSocketColor"),
    ("Specular (_s) Alpha (Emission)", "INPUT", "NodeSocketFloat"),
    ("Displacement Scale", "INPUT", "NodeSocketFloat"),
    ("Emission Strength", "INPUT", "NodeSocketFloat"),
    ("Hardcoded Emission", "INPUT", "NodeSocketFloat"),
    ("Thin Wall", "INPUT", "NodeSocketBool"),
    ("Subsurface Scale", "INPUT", "NodeSocketFloat"),
    ("Transmission Weight", "INPUT", "NodeSocketFloat"),
)


def interface_signature(group: bpy.types.NodeTree) -> tuple[tuple[str, str, str], ...]:
    """Return the public interface without relying on its positional order."""
    return tuple(
        (item.name, item.in_out, item.socket_type)
        for item in group.interface.items_tree
        if item.item_type == "SOCKET"
    )


def effective_link_signature(group: bpy.types.NodeTree) -> frozenset[tuple[str, str, str, str]]:
    """Return links after traversing layout-only reroute nodes."""
    def selector(socket, sockets):
        matches = [candidate for candidate in sockets if candidate.name == socket.name]
        if len(matches) == 1:
            return socket.name
        return f"{socket.name}[{matches.index(socket)}]"

    effective_links: set[tuple[str, str, str, str]] = set()
    for initial_link in group.links:
        if initial_link.from_node.bl_idname == "NodeReroute":
            continue
        pending = [(
            initial_link.from_node,
            initial_link.from_socket,
            initial_link.to_node,
            initial_link.to_socket,
        )]
        while pending:
            source, source_socket, target, target_socket = pending.pop()
            if target.bl_idname != "NodeReroute":
                effective_links.add((
                    source.name,
                    selector(source_socket, source.outputs),
                    target.name,
                    selector(target_socket, target.inputs),
                ))
                continue
            pending.extend(
                (source, source_socket, link.to_node, link.to_socket)
                for link in group.links
                if link.from_node == target
            )
    return frozenset(effective_links)


def reference_shape_errors(group: bpy.types.NodeTree) -> tuple[str, ...]:
    """Return structural differences from the verified LabPBR reference."""
    errors: list[str] = []
    functional_nodes = [node for node in group.nodes if node.bl_idname != "NodeReroute"]
    if len(functional_nodes) != LABPBR_REFERENCE_NODE_COUNT:
        errors.append(f"functional nodes: expected {LABPBR_REFERENCE_NODE_COUNT}, got {len(functional_nodes)}")
    effective_links = effective_link_signature(group)
    if len(effective_links) != LABPBR_REFERENCE_LINK_COUNT:
        errors.append(f"effective links: expected {LABPBR_REFERENCE_LINK_COUNT}, got {len(effective_links)}")
    frames = {node.name for node in group.nodes if node.bl_idname == "NodeFrame"}
    if frames != LABPBR_REFERENCE_FRAMES:
        errors.append(f"frames: expected {sorted(LABPBR_REFERENCE_FRAMES)}, got {sorted(frames)}")
    if interface_signature(group) != LABPBR_INTERFACE:
        errors.append("public interface differs from the LabPBR reference")
    return tuple(errors)


def assert_reference_shape(group: bpy.types.NodeTree) -> None:
    """Raise an actionable error when a decoder migration changes its contract."""
    if errors := reference_shape_errors(group):
        raise AssertionError("LabPBR decoder reference mismatch: " + "; ".join(errors))


def _math(nodes, name, operation, location, constants=None):
    """Create one named scalar operation with explicit non-linked constants."""
    return node(
        nodes, "ShaderNodeMath", name, location=location,
        properties={"operation": operation}, inputs=constants,
    )


def ensure_labpbr_decoder() -> bpy.types.NodeTree:
    """Build the LabPBR 1.3 decoder without layout-only reroute nodes.

    All links below state material intent directly.  In particular, Math and
    Mix sockets use their name plus occurrence (``Value[1]``, ``A[2]``), so a
    Blender UI reordering cannot silently redirect a constant or connection.
    """
    group = ensure_group(LABPBR_GROUP_NAME, LABPBR_TEMPLATE_VERSION)
    # A previous interrupted template migration can leave the version and
    # ``complete`` flags behind while the interface is empty or incomplete.
    # Do not hand that group to a material builder: accessing
    # ``decoder.outputs["BSDF"]`` would then fail, and assigning it to an
    # existing node instance can also discard its socket links.
    if group.nodes and group.get("mozi_template_complete"):
        if interface_signature(group) == LABPBR_INTERFACE:
            return group
        group.nodes.clear()
        group.interface.clear()
        group["mozi_template_complete"] = False
    add_sockets(group, (
        ("BSDF", "OUTPUT", "NodeSocketShader", None),
        ("Displacement", "OUTPUT", "NodeSocketVector", (0.0, 0.0, 0.0)),
        ("Porosity (0-1)", "OUTPUT", "NodeSocketFloat", 0.0, 0.0, 1.0),
        ("Enable PBR (0-1)", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0),
        ("Albedo Color", "INPUT", "NodeSocketColor", (0.8, 0.8, 0.8, 1.0)),
        ("Albedo Alpha", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0),
        ("Normal (_n) Color", "INPUT", "NodeSocketColor", (0.5, 0.5, 1.0, 1.0)),
        ("Normal (_n) Alpha (Height)", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0),
        ("Specular (_s) Color", "INPUT", "NodeSocketColor", (0.292893, 0.04, 0.0, 1.0)),
        ("Specular (_s) Alpha (Emission)", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0),
        ("Displacement Scale", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0),
        ("Emission Strength", "INPUT", "NodeSocketFloat", 5.0, 0.0, 1000.0),
        ("Hardcoded Emission", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1000.0),
        ("Thin Wall", "INPUT", "NodeSocketBool", False),
        ("Subsurface Scale", "INPUT", "NodeSocketFloat", 0.1, 0.0, 10.0),
        ("Transmission Weight", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0),
    ))
    nodes, links = group.nodes, group.links
    group_input = node(nodes, "NodeGroupInput", "Group Input", location=(-1400, 200))
    group_output = node(nodes, "NodeGroupOutput", "Group Output", location=(1400, 200))
    principled = node(nodes, "ShaderNodeBsdfPrincipled", "LabPBR Principled BSDF", label="LabPBR 1.3 Material", location=(1120, 300), properties={
        "subsurface_method": "RANDOM_WALK",
    }, inputs={
        "Thin Wall": False, "Weight": 0.0, "Diffuse Roughness": 0.0,
        "Subsurface Radius": (1.0, 1.0, 1.0), "Subsurface Scale": 0.1,
        "Subsurface IOR": 1.4, "Subsurface Anisotropy": 0.5,
        "Specular IOR Level": 0.5, "Specular Tint": (1, 1, 1, 1),
        "Anisotropic": 0.0, "Anisotropic Rotation": 0.0, "Tangent": (0, 0, 0),
        "Transmission Weight": 0.0, "Coat Weight": 0.0, "Coat Roughness": 0.03,
        "Coat IOR": 1.5, "Coat Tint": (1, 1, 1, 1), "Coat Normal": (0, 0, 0),
        "Sheen Weight": 0.0, "Sheen Roughness": 0.5, "Sheen Tint": (1, 1, 1, 1),
        "Thin Film Thickness": 0.0, "Thin Film IOR": 1.33,
    })
    displacement = node(nodes, "ShaderNodeDisplacement", "LabPBR Height Displacement", location=(800, -350), inputs={"Midlevel": 0.0, "Scale": 1.0, "Normal": (0, 0, 0)})

    normal_frame = node(nodes, "NodeFrame", "Optional _n: DirectX normal, AO, height")
    specular_frame = node(nodes, "NodeFrame", "Optional _s: smoothness, F0, metal, porosity / SSS, emission")
    decode_normal = node(nodes, "ShaderNodeSeparateColor", "Decode _n (DirectX)", location=(-1100, 700))
    decode_specular = node(nodes, "ShaderNodeSeparateColor", "Decode _s", location=(-1100, -500))
    albedo_ao = node(nodes, "ShaderNodeMixRGB", "Albedo × Material AO", location=(-550, 820), properties={"blend_type": "MULTIPLY"}, inputs={"Factor": 1.0})
    normal_x = _math(nodes, "Normal X: 2R − 1", "MULTIPLY_ADD", (-780, 620), {"Value[1]": 2.0, "Value[2]": -1.0})
    normal_y = _math(nodes, "Normal Y: 1 − 2G", "MULTIPLY_ADD", (-780, 420), {"Value[1]": -2.0, "Value[2]": 1.0})
    x_squared = _math(nodes, "X²", "MULTIPLY", (-560, 620))
    y_squared = _math(nodes, "Y²", "MULTIPLY", (-560, 420))
    xy_squared = _math(nodes, "X² + Y²", "ADD", (-350, 520))
    normal_z_base = _math(nodes, "1 − X² − Y²", "SUBTRACT", (-140, 520), {"Value[0]": 1.0})
    clamp_normal_z = _math(nodes, "Clamp normal Z", "MAXIMUM", (70, 520), {"Value[1]": 0.0})
    normal_z = _math(nodes, "Reconstructed normal Z", "SQRT", (280, 520))
    encode_x = _math(nodes, "Encode X", "MULTIPLY_ADD", (280, 700), {"Value[1]": 0.5, "Value[2]": 0.5})
    encode_y = _math(nodes, "Encode Y", "MULTIPLY_ADD", (280, 330), {"Value[1]": 0.5, "Value[2]": 0.5})
    encode_z = _math(nodes, "Encode Z", "MULTIPLY_ADD", (280, 520), {"Value[1]": 0.5, "Value[2]": 0.5})
    reconstructed_normal = node(nodes, "ShaderNodeCombineColor", "Reconstructed DirectX Normal", location=(500, 520))
    normal_map = node(nodes, "ShaderNodeNormalMap", "LabPBR Normal Map", location=(700, 520))
    height_bump = node(nodes, "ShaderNodeBump", "LabPBR Height Bump", location=(920, 520), inputs={"Distance": 1.0, "Strength": 1.0})

    smoothness_inverse = _math(nodes, "1 − Smoothness", "SUBTRACT", (-780, -620), {"Value[0]": 1.0})
    clamp_f0 = _math(nodes, "Clamp dielectric F0", "MINIMUM", (-780, -820), {"Value[1]": 0.8980392157})
    sqrt_f0 = _math(nodes, "sqrt(F0)", "SQRT", (-560, -820))
    one_plus_sqrt_f0 = _math(nodes, "1 + sqrt(F0)", "ADD", (-350, -750), {"Value[1]": 1.0})
    one_minus_sqrt_f0 = _math(nodes, "1 − sqrt(F0)", "SUBTRACT", (-350, -890), {"Value[0]": 1.0})
    ior_from_f0 = _math(nodes, "IOR from F0", "DIVIDE", (-120, -820))
    metal_preset = _math(nodes, "Metal preset / custom metal", "GREATER_THAN", (-560, -1020), {"Value[1]": 0.8980392157})
    sss_offset = _math(nodes, "SSS encoded offset", "SUBTRACT", (-780, -1120), {"Value[1]": 0.2549019608})
    sss_raw_weight = _math(nodes, "SSS raw weight", "DIVIDE", (-560, -1120), {"Value[1]": 0.7450980392})
    subsurface_weight = _math(nodes, "Subsurface Weight", "MAXIMUM", (-350, -1120), {"Value[1]": 0.0})
    porosity_scaled = _math(nodes, "Porosity scaled", "MULTIPLY", (-780, -1280), {"Value[1]": 3.984375})
    porosity_range = _math(nodes, "Is porosity range", "LESS_THAN", (-780, -1420), {"Value[1]": 0.2549019608})
    porosity = _math(nodes, "Porosity (0-1)", "MULTIPLY", (-560, -1420))
    clamp_emission = _math(nodes, "Clamp emission alpha", "MINIMUM", (-780, -1600), {"Value[1]": 0.9960784314})
    emission_data = _math(nodes, "Emission alpha is data (not 255)", "LESS_THAN", (-780, -1740), {"Value[1]": 1.0})
    emission_strength = _math(nodes, "Emission strength", "MULTIPLY", (-560, -1600))
    height_minus_one = _math(nodes, "Height − 1", "SUBTRACT", (-780, 120), {"Value[1]": 1.0})
    labpbr_depth = _math(nodes, "LabPBR depth (25%)", "MULTIPLY", (-560, 120), {"Value[1]": 0.25})
    effective_displacement = _math(nodes, "Effective displacement scale", "MULTIPLY", (-340, 120))

    enable_labpbr = _math(nodes, "Enable LabPBR", "MULTIPLY", (-500, -80), {"Value[1]": 1.0})
    enable_ao = node(nodes, "ShaderNodeMix", "Enable AO", location=(-200, 820), properties={"data_type": "RGBA", "blend_type": "MIX"})
    non_pbr_roughness = node(nodes, "ShaderNodeMix", "Non-PBR Default Roughness", location=(-400, -420), properties={"data_type": "FLOAT", "blend_type": "MIX"}, inputs={"A[0]": 0.5, "B[0]": 0.0})
    enable_roughness = node(nodes, "ShaderNodeMix", "Enable Roughness", location=(-200, -500), properties={"data_type": "FLOAT", "blend_type": "MIX"})
    enable_metallic = _math(nodes, "Enable Metallic", "MULTIPLY", (-200, -650))
    enable_ior = node(nodes, "ShaderNodeMix", "Enable F0 / IOR", location=(120, -820), properties={"data_type": "FLOAT", "blend_type": "MIX"}, inputs={"A[0]": 1.5})
    enable_sss = _math(nodes, "Enable SSS", "MULTIPLY", (-200, -1020))
    enable_displacement = _math(nodes, "Enable Displacement", "MULTIPLY", (120, 120))
    enable_porosity = _math(nodes, "Enable Porosity", "MULTIPLY", (-200, -1420))
    artist_emission = _math(nodes, "Artist Emission Multiplier", "MULTIPLY", (-500, -1740))
    final_emission = node(nodes, "ShaderNodeMix", "Select Emission Mode", location=(120, -1600), properties={"data_type": "FLOAT", "blend_type": "MIX"})

    has_alpha = _math(nodes, "Alpha > 0", "GREATER_THAN", (500, 200), {"Value[1]": 0.001})
    is_not_border = _math(nodes, "Alpha < 1", "LESS_THAN", (500, 50), {"Value[1]": 0.999})
    is_translucent_body = _math(nodes, "Translucent Body", "MULTIPLY", (700, 50))
    translucent_alpha = node(nodes, "ShaderNodeMix", "Translucent Alpha", location=(700, 200), properties={"data_type": "FLOAT", "blend_type": "MIX"}, inputs={"B[0]": 1.0})
    final_alpha = _math(nodes, "Final Alpha", "MULTIPLY", (900, 200))
    final_transmission = _math(nodes, "Final Transmission", "MULTIPLY", (900, 50))

    for child in (decode_normal, albedo_ao, normal_x, normal_y, x_squared, y_squared, xy_squared, normal_z_base, clamp_normal_z, normal_z, encode_x, encode_y, encode_z, reconstructed_normal, normal_map, height_bump, height_minus_one, labpbr_depth, effective_displacement):
        child.parent = normal_frame
    for child in (decode_specular, smoothness_inverse, clamp_f0, sqrt_f0, one_plus_sqrt_f0, one_minus_sqrt_f0, ior_from_f0, metal_preset, sss_offset, sss_raw_weight, subsurface_weight, porosity_scaled, porosity_range, porosity, clamp_emission, emission_data, emission_strength):
        child.parent = specular_frame

    # Decode _n: DirectX normal, AO, and height.
    link(links, group_input, "Normal (_n) Color", decode_normal, "Color")
    link(links, decode_normal, "Blue", albedo_ao, "Color2")
    link(links, group_input, "Albedo Color", albedo_ao, "Color1")
    link(links, decode_normal, "Red", normal_x, "Value[0]"); link(links, decode_normal, "Green", normal_y, "Value[0]")
    link(links, normal_x, "Value", x_squared, "Value[0]"); link(links, normal_x, "Value", x_squared, "Value[1]")
    link(links, normal_y, "Value", y_squared, "Value[0]"); link(links, normal_y, "Value", y_squared, "Value[1]")
    link(links, x_squared, "Value", xy_squared, "Value[0]"); link(links, y_squared, "Value", xy_squared, "Value[1]")
    link(links, xy_squared, "Value", normal_z_base, "Value[1]"); link(links, normal_z_base, "Value", clamp_normal_z, "Value[0]"); link(links, clamp_normal_z, "Value", normal_z, "Value[0]")
    link(links, normal_x, "Value", encode_x, "Value[0]"); link(links, normal_y, "Value", encode_y, "Value[0]"); link(links, normal_z, "Value", encode_z, "Value[0]")
    link(links, encode_x, "Value", reconstructed_normal, "Red"); link(links, encode_y, "Value", reconstructed_normal, "Green"); link(links, encode_z, "Value", reconstructed_normal, "Blue")
    link(links, reconstructed_normal, "Color", normal_map, "Color")
    link(links, group_input, "Normal (_n) Alpha (Height)", height_minus_one, "Value[0]"); link(links, height_minus_one, "Value", labpbr_depth, "Value[0]"); link(links, labpbr_depth, "Value", effective_displacement, "Value[0]"); link(links, group_input, "Displacement Scale", effective_displacement, "Value[1]")

    # Decode _s: smoothness, F0, metal, SSS/porosity, and emission.
    link(links, group_input, "Specular (_s) Color", decode_specular, "Color")
    link(links, decode_specular, "Red", smoothness_inverse, "Value[1]")
    link(links, decode_specular, "Green", clamp_f0, "Value[0]"); link(links, clamp_f0, "Value", sqrt_f0, "Value[0]"); link(links, sqrt_f0, "Value", one_plus_sqrt_f0, "Value[0]"); link(links, sqrt_f0, "Value", one_minus_sqrt_f0, "Value[1]"); link(links, one_plus_sqrt_f0, "Value", ior_from_f0, "Value[0]"); link(links, one_minus_sqrt_f0, "Value", ior_from_f0, "Value[1]")
    link(links, decode_specular, "Green", metal_preset, "Value[0]")
    link(links, decode_specular, "Blue", sss_offset, "Value[0]"); link(links, sss_offset, "Value", sss_raw_weight, "Value[0]"); link(links, sss_raw_weight, "Value", subsurface_weight, "Value[0]")
    link(links, decode_specular, "Blue", porosity_scaled, "Value[0]"); link(links, decode_specular, "Blue", porosity_range, "Value[0]"); link(links, porosity_scaled, "Value", porosity, "Value[0]"); link(links, porosity_range, "Value", porosity, "Value[1]")
    link(links, group_input, "Specular (_s) Alpha (Emission)", clamp_emission, "Value[0]"); link(links, group_input, "Specular (_s) Alpha (Emission)", emission_data, "Value[0]"); link(links, clamp_emission, "Value", emission_strength, "Value[0]"); link(links, emission_data, "Value", emission_strength, "Value[1]")

    # Feature gating and public outputs.
    link(links, group_input, "Enable PBR (0-1)", enable_labpbr, "Value[0]")
    link(links, enable_labpbr, "Value", enable_ao, "Factor[0]"); link(links, group_input, "Albedo Color", enable_ao, "A[2]"); link(links, albedo_ao, "Color", enable_ao, "B[2]")
    link(links, group_input, "Transmission Weight", non_pbr_roughness, "Factor[0]")
    link(links, non_pbr_roughness, "Result[0]", enable_roughness, "A[0]")
    link(links, enable_labpbr, "Value", enable_roughness, "Factor[0]"); link(links, smoothness_inverse, "Value", enable_roughness, "B[0]")
    link(links, metal_preset, "Value", enable_metallic, "Value[0]"); link(links, enable_labpbr, "Value", enable_metallic, "Value[1]")
    link(links, enable_labpbr, "Value", enable_ior, "Factor[0]"); link(links, ior_from_f0, "Value", enable_ior, "B[0]")
    link(links, subsurface_weight, "Value", enable_sss, "Value[0]"); link(links, enable_labpbr, "Value", enable_sss, "Value[1]")
    link(links, effective_displacement, "Value", enable_displacement, "Value[0]"); link(links, enable_labpbr, "Value", enable_displacement, "Value[1]")
    link(links, porosity, "Value", enable_porosity, "Value[0]"); link(links, enable_labpbr, "Value", enable_porosity, "Value[1]")
    link(links, emission_strength, "Value", artist_emission, "Value[0]"); link(links, group_input, "Emission Strength", artist_emission, "Value[1]")
    link(links, enable_labpbr, "Value", final_emission, "Factor[0]"); link(links, group_input, "Hardcoded Emission", final_emission, "A[0]"); link(links, artist_emission, "Value", final_emission, "B[0]")
    link(links, enable_labpbr, "Value", normal_map, "Strength")

    # Transmission and Alpha decoding (Zero-alpha cutout protected & 100% clear dielectric transmission)
    link(links, group_input, "Albedo Alpha", has_alpha, "Value[0]")
    link(links, group_input, "Albedo Alpha", is_not_border, "Value[0]")
    link(links, has_alpha, "Value", is_translucent_body, "Value[0]")
    link(links, is_not_border, "Value", is_translucent_body, "Value[1]")

    link(links, group_input, "Transmission Weight", translucent_alpha, "Factor[0]")
    link(links, group_input, "Albedo Alpha", translucent_alpha, "A[0]")
    link(links, translucent_alpha, "Result[0]", final_alpha, "Value[0]")
    link(links, has_alpha, "Value", final_alpha, "Value[1]")

    link(links, group_input, "Transmission Weight", final_transmission, "Value[0]")
    link(links, is_translucent_body, "Value", final_transmission, "Value[1]")

    link(links, enable_ao, "Result[2]", principled, "Base Color"); link(links, enable_roughness, "Result[0]", principled, "Roughness"); link(links, enable_metallic, "Value", principled, "Metallic"); link(links, enable_ior, "Result[0]", principled, "IOR")
    link(links, final_alpha, "Value", principled, "Alpha")
    link(links, final_transmission, "Value", principled, "Transmission Weight")
    link(links, normal_map, "Normal", height_bump, "Normal"); link(links, enable_displacement, "Value", height_bump, "Height"); link(links, height_bump, "Normal", principled, "Normal")
    link(links, enable_sss, "Value", principled, "Subsurface Weight"); link(links, group_input, "Albedo Color", principled, "Emission Color"); link(links, final_emission, "Result[0]", principled, "Emission Strength")
    link(links, group_input, "Thin Wall", principled, "Thin Wall")
    link(links, group_input, "Subsurface Scale", principled, "Subsurface Scale")
    link(links, principled, "BSDF", group_output, "BSDF"); link(links, enable_displacement, "Value", displacement, "Height"); link(links, displacement, "Displacement", group_output, "Displacement"); link(links, enable_porosity, "Value", group_output, "Porosity (0-1)")
    return finalize_group(group)


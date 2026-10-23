"""Standard Principled PBR graph built from ``MtkPackedV1`` sockets.

This module intentionally contains **no LabPBR decoding** and **no game-semantic
branches**. It only maps canonical channels to standard Principled inputs:

- ``base_color`` × ORM.R (AO) × Vertex AO (Mesh "color" attribute) -> Base Color
- ORM.G -> Roughness, ORM.B -> Metallic, ORM.A -> Emission Strength
- aux.R -> IOR via ``encoded * 7 + 1``, aux.B -> Subsurface Weight
- normal RGB -> Normal Map
- alpha -> Alpha

Height (``normal.A``) is preserved in the packed texture for future exporters and
custom shaders, but is not applied here: the legacy decoder's displacement scale
defaulted to 0, so wiring Bump/Displacement now would change existing visuals.
"""

from __future__ import annotations

from typing import Any, Optional

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from ...node_groups.core import input_socket, node, output_socket

DEFAULT_EMISSION_STRENGTH = 5.0


def build_pbr_shading(
    nodes: Any,
    links: Any,
    output_node: Any,
    frame_shading: Optional[Any],
    *,
    base_color: Any,
    alpha: Any,
    normal_color: Optional[Any] = None,
    orm_color: Optional[Any] = None,
    orm_alpha: Optional[Any] = None,
    aux_color: Optional[Any] = None,
    disable_subsurface: bool = False,
    emission_strength: float = DEFAULT_EMISSION_STRENGTH,
    subsurface_method: str = "BURLEY",
    enable_vertex_ao: bool = True,
) -> Any:
    """Create the Principled BSDF and wire canonical PBR sockets.

    Returns the Principled node. The caller owns texture loading, UV animation
    and biome tinting; this function only consumes final color/scalar sockets.
    """
    if not HAS_BPY:
        return None

    principled = node(
        nodes,
        "ShaderNodeBsdfPrincipled",
        "Principled BSDF",
        location=(900, 0),
        properties={"subsurface_method": subsurface_method},
        inputs={
            "Subsurface Radius": (1.0, 1.0, 1.0),
            "Subsurface Scale": 0.1,
            "Subsurface IOR": 1.4,
            "Subsurface Anisotropy": 0.5,
            "Specular IOR Level": 0.5,
            "Specular Tint": (1.0, 1.0, 1.0, 1.0),
            "Coat Weight": 0.0,
            "Sheen Weight": 0.0,
            "Emission Strength": 0.0,
            "Alpha": 1.0,
        },
    )
    if frame_shading is not None:
        principled.parent = frame_shading
    links.new(principled.outputs["BSDF"], output_node.inputs["Surface"])

    # Emission color reuses the tinted albedo *before* AO, matching the legacy
    # decoder's "clean albedo" emission color.
    emission_color = base_color
    base_out = base_color

    if orm_color is not None:
        orm_separate = node(
            nodes,
            "ShaderNodeSeparateColor",
            "Separate ORM",
            location=(300, 150),
        )
        if frame_shading is not None:
            orm_separate.parent = frame_shading
        links.new(orm_color, orm_separate.inputs["Color"])

        ao_mix = node(
            nodes,
            "ShaderNodeMix",
            "Albedo × AO",
            location=(600, 250),
            properties={"data_type": "RGBA", "blend_type": "MULTIPLY"},
        )
        if frame_shading is not None:
            ao_mix.parent = frame_shading
        input_socket(ao_mix, "Factor[0]").default_value = 1.0
        links.new(base_color, input_socket(ao_mix, "A[2]"))
        links.new(orm_separate.outputs["Red"], input_socket(ao_mix, "B[2]"))
        base_out = output_socket(ao_mix, "Result[2]")

        links.new(orm_separate.outputs["Green"], principled.inputs["Roughness"])
        links.new(orm_separate.outputs["Blue"], principled.inputs["Metallic"])

        if orm_alpha is not None:
            strength = node(
                nodes,
                "ShaderNodeMath",
                "Emission Strength × Mask",
                location=(600, -100),
                properties={"operation": "MULTIPLY"},
                inputs={"Value[1]": float(emission_strength)},
            )
            if frame_shading is not None:
                strength.parent = frame_shading
            links.new(orm_alpha, input_socket(strength, "Value[0]"))
            links.new(strength.outputs["Value"], principled.inputs["Emission Strength"])
    else:
        principled.inputs["Roughness"].default_value = 0.5
        principled.inputs["Metallic"].default_value = 0.0

    if enable_vertex_ao:
        attr_ao = node(
            nodes,
            "ShaderNodeAttribute",
            "Vertex AO",
            location=(500, 360),
            properties={"attribute_name": "color"},
        )
        if frame_shading is not None:
            attr_ao.parent = frame_shading

        # In Blender, when an attribute is missing on the mesh, ShaderNodeAttribute outputs
        # Color=(0,0,0,0) and Alpha=1.0. A factor driven solely by Alpha would select Color B,
        # resulting in (0,0,0,0) and turning uncolored meshes pitch black.
        # We calculate the vector length of the sampled Color: if length > 0.01, valid AO exists;
        # otherwise, we safely fall back to pure White (1,1,1,1) so the mesh stays properly lit.
        ao_len = node(
            nodes,
            "ShaderNodeVectorMath",
            "AO Presence",
            location=(500, 480),
            properties={"operation": "LENGTH"},
        )
        if frame_shading is not None:
            ao_len.parent = frame_shading
        links.new(attr_ao.outputs["Color"], ao_len.inputs[0])

        ao_active = node(
            nodes,
            "ShaderNodeMath",
            "AO Active",
            location=(640, 480),
            properties={"operation": "GREATER_THAN"},
            inputs={"Value[1]": 0.01},
        )
        if frame_shading is not None:
            ao_active.parent = frame_shading
        links.new(ao_len.outputs["Value"], input_socket(ao_active, "Value[0]"))

        safe_ao = node(
            nodes,
            "ShaderNodeMix",
            "Safe Vertex AO",
            location=(640, 360),
            properties={"data_type": "RGBA", "blend_type": "MIX"},
            inputs={"A[2]": (1.0, 1.0, 1.0, 1.0)},
        )
        if frame_shading is not None:
            safe_ao.parent = frame_shading
        links.new(ao_active.outputs["Value"], input_socket(safe_ao, "Factor[0]"))
        links.new(attr_ao.outputs["Color"], input_socket(safe_ao, "B[2]"))

        vertex_ao_mix = node(
            nodes,
            "ShaderNodeMix",
            "Base Color × Vertex AO",
            location=(780, 250),
            properties={"data_type": "RGBA", "blend_type": "MULTIPLY"},
        )
        if frame_shading is not None:
            vertex_ao_mix.parent = frame_shading
        input_socket(vertex_ao_mix, "Factor[0]").default_value = 1.0
        links.new(base_out, input_socket(vertex_ao_mix, "A[2]"))
        links.new(output_socket(safe_ao, "Result[2]"), input_socket(vertex_ao_mix, "B[2]"))
        base_out = output_socket(vertex_ao_mix, "Result[2]")

    links.new(base_out, principled.inputs["Base Color"])
    links.new(emission_color, principled.inputs["Emission Color"])
    links.new(alpha, principled.inputs["Alpha"])

    if aux_color is not None:
        aux_separate = node(
            nodes,
            "ShaderNodeSeparateColor",
            "Separate Aux",
            location=(300, -350),
        )
        if frame_shading is not None:
            aux_separate.parent = frame_shading
        links.new(aux_color, aux_separate.inputs["Color"])

        ior = node(
            nodes,
            "ShaderNodeMath",
            "IOR from Aux",
            location=(600, -350),
            properties={"operation": "MULTIPLY_ADD"},
            inputs={"Value[1]": 7.0, "Value[2]": 1.0},
        )
        if frame_shading is not None:
            ior.parent = frame_shading
        links.new(aux_separate.outputs["Red"], input_socket(ior, "Value[0]"))
        links.new(ior.outputs["Value"], principled.inputs["IOR"])

        if not disable_subsurface:
            links.new(aux_separate.outputs["Blue"], principled.inputs["Subsurface Weight"])
    else:
        principled.inputs["IOR"].default_value = 1.5

    if normal_color is not None:
        normal_map = node(
            nodes,
            "ShaderNodeNormalMap",
            "Normal Map",
            location=(600, 450),
            inputs={"Strength": 1.0},
        )
        if frame_shading is not None:
            normal_map.parent = frame_shading
        links.new(normal_color, normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])

    return principled

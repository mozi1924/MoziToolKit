"""
Shader node group templates for Minecraft Biome Tinting and Color Blending.
Integrates between Albedo / Animated Frame Blend and LabPBR 1.3 Decoder.
"""

from __future__ import annotations

import bpy

from .core import add_sockets, ensure_group, finalize_group, link, node


BIOME_TINT_VERSION = 4


def ensure_biome_tint() -> bpy.types.NodeTree:
    """
    Create or return the reusable MC_Biome_Tint node group.
    Blends Base Albedo and Overlay Albedo with the resolved Biome Tint Color.
    """
    tree = ensure_group("MC_Biome_Tint", BIOME_TINT_VERSION)
    if tree.nodes and tree.get("mozi_template_complete"):
        return tree

    add_sockets(tree, (
        ("Base Color", "INPUT", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0)),
        ("Base Alpha", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0),
        ("Overlay Color", "INPUT", "NodeSocketColor", (0.0, 0.0, 0.0, 0.0)),
        ("Overlay Alpha", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0),
        ("Base Tint Weight", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0),
        ("Overlay Tint Weight", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0),
        ("Tint Weight", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0),
        ("Tint Color", "INPUT", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0)),
        ("Enable Tint", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0),
        ("Color", "OUTPUT", "NodeSocketColor", None),
        ("Alpha", "OUTPUT", "NodeSocketFloat", None),
    ))

    nodes, links = tree.nodes, tree.links
    group_in = node(nodes, "NodeGroupInput", "Group Input", location=(-1200, 0))
    group_out = node(nodes, "NodeGroupOutput", "Group Output", location=(1200, 0))

    # 1. Global Enable Factor: Tint Weight * Enable Tint
    mult_global = node(
        nodes,
        "ShaderNodeMath",
        "Global Tint Factor",
        location=(-900, 100),
        properties={"operation": "MULTIPLY"},
    )
    link(links, group_in, "Tint Weight", mult_global, "Value[0]")
    link(links, group_in, "Enable Tint", mult_global, "Value[1]")

    # 2. Base Factor = Base Tint Weight * Global Tint Factor
    mult_base_fac = node(
        nodes,
        "ShaderNodeMath",
        "Base Tint Factor",
        location=(-680, 200),
        properties={"operation": "MULTIPLY"},
    )
    link(links, group_in, "Base Tint Weight", mult_base_fac, "Value[0]")
    link(links, mult_global, "Value", mult_base_fac, "Value[1]")

    # 3. Overlay Factor = Overlay Tint Weight * Global Tint Factor
    mult_overlay_fac = node(
        nodes,
        "ShaderNodeMath",
        "Overlay Tint Factor",
        location=(-680, -50),
        properties={"operation": "MULTIPLY"},
    )
    link(links, group_in, "Overlay Tint Weight", mult_overlay_fac, "Value[0]")
    link(links, mult_global, "Value", mult_overlay_fac, "Value[1]")

    # 4. Effective Base Tint = Mix(White, Tint Color, Base Factor)
    mix_base_tint = node(
        nodes,
        "ShaderNodeMix",
        "Effective Base Tint",
        location=(-460, 200),
        properties={"data_type": "RGBA", "blend_type": "MIX"},
        inputs={"A[2]": (1.0, 1.0, 1.0, 1.0)},
    )
    link(links, mult_base_fac, "Value", mix_base_tint, "Factor[0]")
    link(links, group_in, "Tint Color", mix_base_tint, "B[2]")

    # 5. Effective Overlay Tint = Mix(White, Tint Color, Overlay Factor)
    mix_overlay_tint = node(
        nodes,
        "ShaderNodeMix",
        "Effective Overlay Tint",
        location=(-460, -50),
        properties={"data_type": "RGBA", "blend_type": "MIX"},
        inputs={"A[2]": (1.0, 1.0, 1.0, 1.0)},
    )
    link(links, mult_overlay_fac, "Value", mix_overlay_tint, "Factor[0]")
    link(links, group_in, "Tint Color", mix_overlay_tint, "B[2]")

    # 6. Tinted Base RGB = Base Color * Effective Base Tint
    mult_base_col = node(
        nodes,
        "ShaderNodeMix",
        "Tinted Base Color",
        location=(-220, 200),
        properties={"data_type": "RGBA", "blend_type": "MULTIPLY"},
        inputs={"Factor[0]": 1.0},
    )
    link(links, group_in, "Base Color", mult_base_col, "A[2]")
    link(links, mix_base_tint, "Result[2]", mult_base_col, "B[2]")

    # 7. Tinted Overlay RGB = Overlay Color * Effective Overlay Tint
    mult_overlay_col = node(
        nodes,
        "ShaderNodeMix",
        "Tinted Overlay Color",
        location=(-220, -50),
        properties={"data_type": "RGBA", "blend_type": "MULTIPLY"},
        inputs={"Factor[0]": 1.0},
    )
    link(links, group_in, "Overlay Color", mult_overlay_col, "A[2]")
    link(links, mix_overlay_tint, "Result[2]", mult_overlay_col, "B[2]")

    # 8. Composite Final Color = Mix(Tinted Base, Tinted Overlay, Overlay Alpha)
    comp_color = node(
        nodes,
        "ShaderNodeMix",
        "Composite Color",
        location=(150, 100),
        properties={"data_type": "RGBA", "blend_type": "MIX"},
    )
    link(links, group_in, "Overlay Alpha", comp_color, "Factor[0]")
    link(links, mult_base_col, "Result[2]", comp_color, "A[2]")
    link(links, mult_overlay_col, "Result[2]", comp_color, "B[2]")
    link(links, comp_color, "Result[2]", group_out, "Color")

    # 9. Composite Final Alpha = Max(Base Alpha, Overlay Alpha)
    max_alpha = node(
        nodes,
        "ShaderNodeMath",
        "Composite Alpha",
        location=(150, -150),
        properties={"operation": "MAXIMUM"},
    )
    link(links, group_in, "Base Alpha", max_alpha, "Value[0]")
    link(links, group_in, "Overlay Alpha", max_alpha, "Value[1]")
    link(links, max_alpha, "Value", group_out, "Alpha")

    return finalize_group(tree)

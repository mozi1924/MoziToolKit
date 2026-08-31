"""
Shader node group templates for Minecraft Biome Tinting and Color Blending.
Integrates between Albedo / Animated Frame Blend and LabPBR 1.3 Decoder.
"""

from __future__ import annotations

import bpy

from .core import add_sockets, ensure_group, finalize_group, link, node


BIOME_TINT_VERSION = 3
COLORMAP_SAMPLER_VERSION = 2


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
        "ShaderNodeMixRGB",
        "Effective Base Tint",
        location=(-460, 200),
        properties={"blend_type": "MIX"},
        inputs={"Color1": (1.0, 1.0, 1.0, 1.0)},
    )
    link(links, mult_base_fac, "Value", mix_base_tint, "Factor")
    link(links, group_in, "Tint Color", mix_base_tint, "Color2")

    # 5. Effective Overlay Tint = Mix(White, Tint Color, Overlay Factor)
    mix_overlay_tint = node(
        nodes,
        "ShaderNodeMixRGB",
        "Effective Overlay Tint",
        location=(-460, -50),
        properties={"blend_type": "MIX"},
        inputs={"Color1": (1.0, 1.0, 1.0, 1.0)},
    )
    link(links, mult_overlay_fac, "Value", mix_overlay_tint, "Factor")
    link(links, group_in, "Tint Color", mix_overlay_tint, "Color2")

    # 6. Tinted Base RGB = Base Color * Effective Base Tint
    mult_base_col = node(
        nodes,
        "ShaderNodeMixRGB",
        "Tinted Base Color",
        location=(-220, 200),
        properties={"blend_type": "MULTIPLY"},
        inputs={"Factor": 1.0},
    )
    link(links, group_in, "Base Color", mult_base_col, "Color1")
    link(links, mix_base_tint, "Color", mult_base_col, "Color2")

    # 7. Tinted Overlay RGB = Overlay Color * Effective Overlay Tint
    mult_overlay_col = node(
        nodes,
        "ShaderNodeMixRGB",
        "Tinted Overlay Color",
        location=(-220, -50),
        properties={"blend_type": "MULTIPLY"},
        inputs={"Factor": 1.0},
    )
    link(links, group_in, "Overlay Color", mult_overlay_col, "Color1")
    link(links, mix_overlay_tint, "Color", mult_overlay_col, "Color2")

    # 8. Composite Final Color = Mix(Tinted Base, Tinted Overlay, Overlay Alpha)
    comp_color = node(
        nodes,
        "ShaderNodeMixRGB",
        "Composite Color",
        location=(150, 100),
        properties={"blend_type": "MIX"},
    )
    link(links, group_in, "Overlay Alpha", comp_color, "Factor")
    link(links, mult_base_col, "Color", comp_color, "Color1")
    link(links, mult_overlay_col, "Color", comp_color, "Color2")
    link(links, comp_color, "Color", group_out, "Color")

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


def ensure_colormap_sampler() -> bpy.types.NodeTree:
    """
    Create or return the reusable MC_Biome_Colormap_Sampler node group.
    Computes standard Minecraft triangular UV coordinates from Temperature and Humidity for Blender Image Texture sampling:
      U = 1.0 - clamp(Temperature, 0.0, 1.0)
      V = clamp(Humidity, 0.0, 1.0) * clamp(Temperature, 0.0, 1.0)
    """
    tree = ensure_group("MC_Biome_Colormap_Sampler", COLORMAP_SAMPLER_VERSION)
    if tree.nodes and tree.get("mozi_template_complete"):
        return tree

    add_sockets(tree, (
        ("Temperature", "INPUT", "NodeSocketFloat", 0.8, 0.0, 1.0),
        ("Humidity", "INPUT", "NodeSocketFloat", 0.4, 0.0, 1.0),
        ("Colormap UV", "OUTPUT", "NodeSocketVector", None),
    ))

    nodes, links = tree.nodes, tree.links
    group_in = node(nodes, "NodeGroupInput", "Group Input", location=(-800, 0))
    group_out = node(nodes, "NodeGroupOutput", "Group Output", location=(600, 0))

    # Clamp Temperature [0, 1]
    clamp_temp = node(
        nodes,
        "ShaderNodeMath",
        "Clamp Temperature",
        location=(-600, 100),
        properties={"operation": "MINIMUM"},
    )
    link(links, group_in, "Temperature", clamp_temp, "Value[0]")
    clamp_temp.inputs[1].default_value = 1.0

    max_temp = node(
        nodes,
        "ShaderNodeMath",
        "Max 0 Temperature",
        location=(-420, 100),
        properties={"operation": "MAXIMUM"},
    )
    link(links, clamp_temp, "Value", max_temp, "Value[0]")
    max_temp.inputs[1].default_value = 0.0

    # Clamp Humidity [0, 1]
    clamp_hum = node(
        nodes,
        "ShaderNodeMath",
        "Clamp Humidity",
        location=(-600, -100),
        properties={"operation": "MINIMUM"},
    )
    link(links, group_in, "Humidity", clamp_hum, "Value[0]")
    clamp_hum.inputs[1].default_value = 1.0

    max_hum = node(
        nodes,
        "ShaderNodeMath",
        "Max 0 Humidity",
        location=(-420, -100),
        properties={"operation": "MAXIMUM"},
    )
    link(links, clamp_hum, "Value", max_hum, "Value[0]")
    max_hum.inputs[1].default_value = 0.0

    # Minecraft triangular mapping for Blender UV (origin bottom-left):
    # U = 1.0 - Temperature
    # V = Humidity * Temperature
    sub_u = node(
        nodes,
        "ShaderNodeMath",
        "1 - Temperature (U)",
        location=(-220, 100),
        properties={"operation": "SUBTRACT"},
    )
    sub_u.inputs[0].default_value = 1.0
    link(links, max_temp, "Value", sub_u, "Value[1]")

    mult_v = node(
        nodes,
        "ShaderNodeMath",
        "Humidity * Temp (V)",
        location=(-220, -100),
        properties={"operation": "MULTIPLY"},
    )
    link(links, max_hum, "Value", mult_v, "Value[0]")
    link(links, max_temp, "Value", mult_v, "Value[1]")

    # Combine UV
    comb_uv = node(nodes, "ShaderNodeCombineXYZ", "Combine Colormap UV", location=(200, 0))
    link(links, sub_u, "Value", comb_uv, "X")
    link(links, mult_v, "Value", comb_uv, "Y")
    link(links, comb_uv, "Vector", group_out, "Colormap UV")

    return finalize_group(tree)


COLORMAP_DECODER_VERSION = 1


def ensure_colormap_decoder() -> bpy.types.NodeTree:
    """
    Create or return the reusable MC_Biome_Colormap_Decoder node group.
    Dynamically routes between Grass, Foliage, Dry Foliage, Water, Hardcoded, or Fallback colors
    based on the input integer/float Tint Type:
      0 = None / Fallback (White)
      1 = Grass Colormap
      2 = Foliage Colormap
      3 = Water Color
      4 = Hardcoded Color
      5 = Dry Foliage Colormap
    """
    tree = ensure_group("MC_Biome_Colormap_Decoder", COLORMAP_DECODER_VERSION)
    if tree.nodes and tree.get("mozi_template_complete"):
        return tree

    add_sockets(tree, (
        ("Tint Type", "INPUT", "NodeSocketFloat", 1.0, 0.0, 5.0),
        ("Grass Color", "INPUT", "NodeSocketColor", (0.57, 0.74, 0.35, 1.0)),
        ("Foliage Color", "INPUT", "NodeSocketColor", (0.47, 0.67, 0.18, 1.0)),
        ("Dry Foliage Color", "INPUT", "NodeSocketColor", (0.64, 0.46, 0.27, 1.0)),
        ("Water Color", "INPUT", "NodeSocketColor", (0.25, 0.46, 0.89, 1.0)),
        ("Hardcoded Color", "INPUT", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0)),
        ("Fallback Color", "INPUT", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0)),
        ("Color", "OUTPUT", "NodeSocketColor", None),
    ))

    nodes, links = tree.nodes, tree.links
    group_in = node(nodes, "NodeGroupInput", "Group Input", location=(-1200, 0))
    group_out = node(nodes, "NodeGroupOutput", "Group Output", location=(700, 200))

    def create_range_mask(name, min_v, max_v, x_pos, y_pos):
        step_min = node(nodes, "ShaderNodeMath", f"Step Min {name}", location=(x_pos, y_pos), properties={"operation": "GREATER_THAN"})
        link(links, group_in, "Tint Type", step_min, "Value[0]")
        step_min.inputs[1].default_value = min_v

        if max_v is not None:
            step_max = node(nodes, "ShaderNodeMath", f"Step Max {name}", location=(x_pos, y_pos - 80), properties={"operation": "GREATER_THAN"})
            link(links, group_in, "Tint Type", step_max, "Value[0]")
            step_max.inputs[1].default_value = max_v

            mask = node(nodes, "ShaderNodeMath", f"Mask {name}", location=(x_pos + 180, y_pos - 40), properties={"operation": "SUBTRACT"})
            link(links, step_min, "Value", mask, "Value[0]")
            link(links, step_max, "Value", mask, "Value[1]")
            return mask
        return step_min

    mask_grass = create_range_mask("Grass", 0.5, 1.5, -900, 400)
    mask_foliage = create_range_mask("Foliage", 1.5, 2.5, -900, 200)
    mask_water = create_range_mask("Water", 2.5, 3.5, -900, 0)
    mask_hardcoded = create_range_mask("Hardcoded", 3.5, 4.5, -900, -200)
    mask_dry = create_range_mask("Dry Foliage", 4.5, None, -900, -400)

    # Chain Mix nodes
    mix1 = node(nodes, "ShaderNodeMixRGB", "Mix Grass", location=(-400, 200), properties={"blend_type": "MIX"})
    link(links, mask_grass, "Value", mix1, "Factor")
    link(links, group_in, "Fallback Color", mix1, "Color1")
    link(links, group_in, "Grass Color", mix1, "Color2")

    mix2 = node(nodes, "ShaderNodeMixRGB", "Mix Foliage", location=(-200, 200), properties={"blend_type": "MIX"})
    link(links, mask_foliage, "Value", mix2, "Factor")
    link(links, mix1, "Color", mix2, "Color1")
    link(links, group_in, "Foliage Color", mix2, "Color2")

    mix3 = node(nodes, "ShaderNodeMixRGB", "Mix Water", location=(0, 200), properties={"blend_type": "MIX"})
    link(links, mask_water, "Value", mix3, "Factor")
    link(links, mix2, "Color", mix3, "Color1")
    link(links, group_in, "Water Color", mix3, "Color2")

    mix4 = node(nodes, "ShaderNodeMixRGB", "Mix Hardcoded", location=(200, 200), properties={"blend_type": "MIX"})
    link(links, mask_hardcoded, "Value", mix4, "Factor")
    link(links, mix3, "Color", mix4, "Color1")
    link(links, group_in, "Hardcoded Color", mix4, "Color2")

    mix5 = node(nodes, "ShaderNodeMixRGB", "Mix Dry Foliage", location=(400, 200), properties={"blend_type": "MIX"})
    link(links, mask_dry, "Value", mix5, "Factor")
    link(links, mix4, "Color", mix5, "Color1")
    link(links, group_in, "Dry Foliage Color", mix5, "Color2")

    link(links, mix5, "Color", group_out, "Color")

    return finalize_group(tree)

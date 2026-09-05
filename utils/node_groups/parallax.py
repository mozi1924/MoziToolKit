from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import bpy

from .core import add_sockets, ensure_group, finalize_group, link, node


PARALLAX_GROUP_NAME = "MC_Parallax_UV_Offset"
PARALLAX_TEMPLATE_VERSION = 1


def ensure_parallax_uv_offset() -> bpy.types.NodeTree:
    """Build the tangent-space parallax UV offset generator with cell clamping.

    Calculates the view ray projection in tangent space and offsets the input UV
    based on the height map while clamping within the cell bounds to prevent
    atlas/tile bleeding.
    """
    group = ensure_group(PARALLAX_GROUP_NAME, PARALLAX_TEMPLATE_VERSION)
    if group.nodes and group.get("mozi_template_complete"):
        return group

    add_sockets(group, (
        ("Parallax UV", "OUTPUT", "NodeSocketVector", (0.0, 0.0, 0.0)),
        ("Delta UV", "OUTPUT", "NodeSocketVector", (0.0, 0.0, 0.0)),
        ("Vector", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0)),
        ("Height (0-1)", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0),
        ("Parallax Scale", "INPUT", "NodeSocketFloat", 1.0, 0.0, 10.0),
        ("Depth Offset (0-1)", "INPUT", "NodeSocketFloat", 0.25, 0.0, 1.0),
        ("Clamp to Cell (0-1)", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0),
        ("Min UV", "INPUT", "NodeSocketVector", (0.0001, 0.0001, 0.0)),
        ("Max UV", "INPUT", "NodeSocketVector", (0.9999, 0.9999, 0.0)),
    ))
    nodes, links = group.nodes, group.links

    group_in = node(nodes, "NodeGroupInput", "Group Input", location=(-1200, 0))
    group_out = node(nodes, "NodeGroupOutput", "Group Output", location=(1200, 0))

    # 1. Geometry & Tangent Basis
    geom = node(nodes, "ShaderNodeNewGeometry", "Geometry", location=(-1200, 400))
    tangent = node(nodes, "ShaderNodeTangent", "Tangent", location=(-1200, 200), properties={"direction_type": "UV_MAP", "uv_map": "UVMap"})

    # Surface to camera direction: V = -Incoming
    view_vec = node(nodes, "ShaderNodeVectorMath", "View Vector (-Incoming)", location=(-980, 400), properties={"operation": "SCALE"}, inputs={"Scale": -1.0})
    link(links, geom, "Incoming", view_vec, "Vector")

    norm_normal = node(nodes, "ShaderNodeVectorMath", "Normalize Normal", location=(-980, 280), properties={"operation": "NORMALIZE"})
    norm_tangent = node(nodes, "ShaderNodeVectorMath", "Normalize Tangent", location=(-980, 160), properties={"operation": "NORMALIZE"})
    link(links, geom, "Normal", norm_normal, "Vector")
    link(links, tangent, "Tangent", norm_tangent, "Vector")

    # Bitangent = Normal × Tangent
    bitangent = node(nodes, "ShaderNodeVectorMath", "Bitangent", location=(-780, 220), properties={"operation": "CROSS_PRODUCT"})
    link(links, norm_normal, "Vector", bitangent, "Vector[0]")
    link(links, norm_tangent, "Vector", bitangent, "Vector[1]")
    norm_bitangent = node(nodes, "ShaderNodeVectorMath", "Normalize Bitangent", location=(-600, 220), properties={"operation": "NORMALIZE"})
    link(links, bitangent, "Vector", norm_bitangent, "Vector")

    # 2. Tangent Space Projection: Vx = V · T, Vy = V · B, Vz = V · N
    dot_vx = node(nodes, "ShaderNodeVectorMath", "Vx (V · T)", location=(-400, 360), properties={"operation": "DOT_PRODUCT"})
    dot_vy = node(nodes, "ShaderNodeVectorMath", "Vy (V · B)", location=(-400, 220), properties={"operation": "DOT_PRODUCT"})
    dot_vz = node(nodes, "ShaderNodeVectorMath", "Vz (V · N)", location=(-400, 80), properties={"operation": "DOT_PRODUCT"})
    link(links, view_vec, "Vector", dot_vx, "Vector[0]"); link(links, norm_tangent, "Vector", dot_vx, "Vector[1]")
    link(links, view_vec, "Vector", dot_vy, "Vector[0]"); link(links, norm_bitangent, "Vector", dot_vy, "Vector[1]")
    link(links, view_vec, "Vector", dot_vz, "Vector[0]"); link(links, norm_normal, "Vector", dot_vz, "Vector[1]")

    # Safe Vz: clamp to minimum 0.15 to avoid grazing angle division explosion
    safe_vz = node(nodes, "ShaderNodeMath", "Safe Vz", location=(-200, 80), properties={"operation": "MAXIMUM"}, inputs={"Value[1]": 0.15})
    link(links, dot_vz, "Value", safe_vz, "Value[0]")

    slope_x = node(nodes, "ShaderNodeMath", "Slope X (Vx / Vz)", location=(-20, 360), properties={"operation": "DIVIDE"})
    slope_y = node(nodes, "ShaderNodeMath", "Slope Y (Vy / Vz)", location=(-20, 220), properties={"operation": "DIVIDE"})
    link(links, dot_vx, "Value", slope_x, "Value[0]"); link(links, safe_vz, "Value", slope_x, "Value[1]")
    link(links, dot_vy, "Value", slope_y, "Value[0]"); link(links, safe_vz, "Value", slope_y, "Value[1]")

    # 3. Depth Scale Calculation: depth = (1.0 - Height) * DepthOffset * ParallaxScale
    inv_height = node(nodes, "ShaderNodeMath", "1 − Height", location=(-600, -100), properties={"operation": "SUBTRACT"}, inputs={"Value[0]": 1.0})
    link(links, group_in, "Height (0-1)", inv_height, "Value[1]")

    scaled_depth_base = node(nodes, "ShaderNodeMath", "Depth × Offset", location=(-400, -100), properties={"operation": "MULTIPLY"})
    link(links, inv_height, "Value", scaled_depth_base, "Value[0]")
    link(links, group_in, "Depth Offset (0-1)", scaled_depth_base, "Value[1]")

    effective_depth = node(nodes, "ShaderNodeMath", "Effective Depth", location=(-200, -100), properties={"operation": "MULTIPLY"})
    link(links, scaled_depth_base, "Value", effective_depth, "Value[0]")
    link(links, group_in, "Parallax Scale", effective_depth, "Value[1]")

    # 4. Delta UV = -Slope * EffectiveDepth
    delta_x = node(nodes, "ShaderNodeMath", "Delta X", location=(160, 360), properties={"operation": "MULTIPLY"})
    delta_y = node(nodes, "ShaderNodeMath", "Delta Y", location=(160, 220), properties={"operation": "MULTIPLY"})
    link(links, slope_x, "Value", delta_x, "Value[0]"); link(links, effective_depth, "Value", delta_x, "Value[1]")
    link(links, slope_y, "Value", delta_y, "Value[0]"); link(links, effective_depth, "Value", delta_y, "Value[1]")

    neg_delta_x = node(nodes, "ShaderNodeMath", "−Delta X", location=(320, 360), properties={"operation": "MULTIPLY"}, inputs={"Value[1]": -1.0})
    neg_delta_y = node(nodes, "ShaderNodeMath", "−Delta Y", location=(320, 220), properties={"operation": "MULTIPLY"}, inputs={"Value[1]": -1.0})
    link(links, delta_x, "Value", neg_delta_x, "Value[0]")
    link(links, delta_y, "Value", neg_delta_y, "Value[0]")

    delta_uv = node(nodes, "ShaderNodeCombineXYZ", "Delta UV", location=(500, 300))
    link(links, neg_delta_x, "Value", delta_uv, "X")
    link(links, neg_delta_y, "Value", delta_uv, "Y")
    link(links, delta_uv, "Vector", group_out, "Delta UV")

    # 5. Apply Offset & Boundary Clamping
    sep_uv = node(nodes, "ShaderNodeSeparateXYZ", "Separate Input UV", location=(-200, -300))
    link(links, group_in, "Vector", sep_uv, "Vector")

    raw_u = node(nodes, "ShaderNodeMath", "U + Delta X", location=(500, -200), properties={"operation": "ADD"})
    raw_v = node(nodes, "ShaderNodeMath", "V + Delta Y", location=(500, -320), properties={"operation": "ADD"})
    link(links, sep_uv, "X", raw_u, "Value[0]"); link(links, neg_delta_x, "Value", raw_u, "Value[1]")
    link(links, sep_uv, "Y", raw_v, "Value[0]"); link(links, neg_delta_y, "Value", raw_v, "Value[1]")

    sep_min = node(nodes, "ShaderNodeSeparateXYZ", "Separate Min UV", location=(320, -450))
    sep_max = node(nodes, "ShaderNodeSeparateXYZ", "Separate Max UV", location=(320, -580))
    link(links, group_in, "Min UV", sep_min, "Vector")
    link(links, group_in, "Max UV", sep_max, "Vector")

    clamp_u_min = node(nodes, "ShaderNodeMath", "Clamp U Min", location=(680, -200), properties={"operation": "MAXIMUM"})
    clamp_u_max = node(nodes, "ShaderNodeMath", "Clamp U Max", location=(840, -200), properties={"operation": "MINIMUM"})
    link(links, raw_u, "Value", clamp_u_min, "Value[0]"); link(links, sep_min, "X", clamp_u_min, "Value[1]")
    link(links, clamp_u_min, "Value", clamp_u_max, "Value[0]"); link(links, sep_max, "X", clamp_u_max, "Value[1]")

    clamp_v_min = node(nodes, "ShaderNodeMath", "Clamp V Min", location=(680, -320), properties={"operation": "MAXIMUM"})
    clamp_v_max = node(nodes, "ShaderNodeMath", "Clamp V Max", location=(840, -320), properties={"operation": "MINIMUM"})
    link(links, raw_v, "Value", clamp_v_min, "Value[0]"); link(links, sep_min, "Y", clamp_v_min, "Value[1]")
    link(links, clamp_v_min, "Value", clamp_v_max, "Value[0]"); link(links, sep_max, "Y", clamp_v_max, "Value[1]")

    final_u = node(nodes, "ShaderNodeMix", "Mix Clamped U", location=(1000, -200), properties={"data_type": "FLOAT"})
    final_v = node(nodes, "ShaderNodeMix", "Mix Clamped V", location=(1000, -320), properties={"data_type": "FLOAT"})
    link(links, group_in, "Clamp to Cell (0-1)", final_u, "Factor"); link(links, raw_u, "Value", final_u, "A"); link(links, clamp_u_max, "Value", final_u, "B")
    link(links, group_in, "Clamp to Cell (0-1)", final_v, "Factor"); link(links, raw_v, "Value", final_v, "A"); link(links, clamp_v_max, "Value", final_v, "B")

    combine_final = node(nodes, "ShaderNodeCombineXYZ", "Parallax UV", location=(1160, -250))
    link(links, final_u, "Result", combine_final, "X")
    link(links, final_v, "Result", combine_final, "Y")
    link(links, combine_final, "Vector", group_out, "Parallax UV")

    return finalize_group(group)

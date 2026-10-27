"""
Texture sampling and animated frame blend helpers for Atlas materials.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Tuple


def _create_tex_node(
    nodes: Any,
    image: Any,
    name: str,
    location: Tuple[float, float],
    frame: Any,
) -> Any:
    node = nodes.new("ShaderNodeTexImage")
    node.name = name
    node.image = image
    node.interpolation = "Closest"
    node.extension = "CLIP"
    node.location = location
    node.parent = frame
    return node


def sample_color_channel(
    nodes: Any,
    links: Any,
    frame_tex: Any,
    image: Any,
    name_prefix: str,
    is_animated: bool,
    anim_curr_uv: Any,
    anim_next_uv: Any,
    blend_factor_sock: Any,
    static_uv: Any,
    y_current: float,
    y_next: float,
    y_blend: float,
    y_static: float,
    blend_group_getter: Callable[[], Any],
    blend_group_name: str = "Animated Frame Blend",
) -> Tuple[Optional[Any], Optional[Any], Optional[Any]]:
    """
    Sample an RGBA color texture (albedo or overlay) with optional animated frame blending.
    Returns `(out_color, out_alpha, primary_tex_node)`.
    """
    if not image:
        return None, None, None

    blend_group = blend_group_getter() if is_animated and anim_curr_uv is not None else None
    if blend_group:
        curr_node = _create_tex_node(
            nodes, image, f"{name_prefix} (Current)", (-1150, y_current), frame_tex
        )
        links.new(anim_curr_uv, curr_node.inputs["Vector"])

        next_node = _create_tex_node(
            nodes, image, f"{name_prefix} (Next)", (-1150, y_next), frame_tex
        )
        links.new(anim_next_uv, next_node.inputs["Vector"])

        blend_node = nodes.new("ShaderNodeGroup")
        blend_node.name = blend_group_name
        blend_node.node_tree = blend_group
        blend_node.location = (-880, y_blend)
        blend_node.parent = frame_tex

        links.new(curr_node.outputs["Color"], blend_node.inputs["Current Color"])
        links.new(next_node.outputs["Color"], blend_node.inputs["Next Color"])
        links.new(curr_node.outputs["Alpha"], blend_node.inputs["Current Alpha"])
        links.new(next_node.outputs["Alpha"], blend_node.inputs["Next Alpha"])
        if blend_factor_sock:
            links.new(blend_factor_sock, blend_node.inputs["Blend Factor"])

        return blend_node.outputs["Color"], blend_node.outputs["Alpha"], curr_node

    tex_node = _create_tex_node(nodes, image, name_prefix, (-1150, y_static), frame_tex)
    links.new(static_uv, tex_node.inputs["Vector"])
    return tex_node.outputs["Color"], tex_node.outputs["Alpha"], tex_node


def sample_normal_channel(
    nodes: Any,
    links: Any,
    frame_tex: Any,
    image: Any,
    is_animated: bool,
    anim_curr_uv: Any,
    anim_next_uv: Any,
    blend_factor_sock: Any,
    active_sample_uv: Any,
    blend_group_getter: Callable[[], Any],
) -> Optional[Any]:
    """
    Sample a normal+height texture with optional animated normal frame blending.
    Returns `out_normal_color`.
    """
    if not image:
        return None

    norm_blend_group = blend_group_getter() if is_animated and anim_curr_uv is not None else None
    if norm_blend_group:
        curr_node = _create_tex_node(
            nodes, image, "Atlas Normal Texture (Current)", (-1150, 20), frame_tex
        )
        links.new(anim_curr_uv, curr_node.inputs["Vector"])

        next_node = _create_tex_node(
            nodes, image, "Atlas Normal Texture (Next)", (-1150, -240), frame_tex
        )
        links.new(anim_next_uv, next_node.inputs["Vector"])

        anim_norm_blend = nodes.new("ShaderNodeGroup")
        anim_norm_blend.name = "Animated Normal Blend"
        anim_norm_blend.node_tree = norm_blend_group
        anim_norm_blend.location = (-880, -100)
        anim_norm_blend.parent = frame_tex

        links.new(curr_node.outputs["Color"], anim_norm_blend.inputs["Current Normal"])
        links.new(next_node.outputs["Color"], anim_norm_blend.inputs["Next Normal"])
        links.new(curr_node.outputs["Alpha"], anim_norm_blend.inputs["Current Height"])
        links.new(next_node.outputs["Alpha"], anim_norm_blend.inputs["Next Height"])
        if blend_factor_sock:
            links.new(blend_factor_sock, anim_norm_blend.inputs["Blend Factor"])

        return anim_norm_blend.outputs["Normal"]

    norm_node = _create_tex_node(
        nodes, image, "Atlas Normal Texture", (-1150, 20), frame_tex
    )
    links.new(active_sample_uv, norm_node.inputs["Vector"])
    return norm_node.outputs["Color"]


def sample_specular_channel(
    nodes: Any,
    links: Any,
    frame_tex: Any,
    image: Any,
    name_prefix: str,
    blend_group_name: str,
    is_animated: bool,
    anim_curr_uv: Any,
    anim_next_uv: Any,
    blend_factor_sock: Any,
    active_sample_uv: Any,
    y_current: float,
    y_next: float,
    y_blend: float,
    y_static: float,
    blend_group_getter: Callable[[], Any],
) -> Tuple[Optional[Any], Optional[Any]]:
    """
    Sample an ORM or Aux texture with optional animated frame blending.
    Returns `(out_color, out_alpha)`.
    """
    if not image:
        return None, None

    blend_group = blend_group_getter() if is_animated and anim_curr_uv is not None else None
    if blend_group:
        curr_node = _create_tex_node(
            nodes, image, f"{name_prefix} (Current)", (-1150, y_current), frame_tex
        )
        links.new(anim_curr_uv, curr_node.inputs["Vector"])

        next_node = _create_tex_node(
            nodes, image, f"{name_prefix} (Next)", (-1150, y_next), frame_tex
        )
        links.new(anim_next_uv, next_node.inputs["Vector"])

        blend_node = nodes.new("ShaderNodeGroup")
        blend_node.name = blend_group_name
        blend_node.node_tree = blend_group
        blend_node.location = (-880, y_blend)
        blend_node.parent = frame_tex

        links.new(curr_node.outputs["Color"], blend_node.inputs["Current Specular"])
        links.new(next_node.outputs["Color"], blend_node.inputs["Next Specular"])
        links.new(curr_node.outputs["Alpha"], blend_node.inputs["Current Emission"])
        links.new(next_node.outputs["Alpha"], blend_node.inputs["Next Emission"])
        if blend_factor_sock:
            links.new(blend_factor_sock, blend_node.inputs["Blend Factor"])

        return blend_node.outputs["Specular"], blend_node.outputs["Emission"]

    tex_node = _create_tex_node(nodes, image, name_prefix, (-1150, y_static), frame_tex)
    links.new(active_sample_uv, tex_node.inputs["Vector"])
    return tex_node.outputs["Color"], tex_node.outputs["Alpha"]

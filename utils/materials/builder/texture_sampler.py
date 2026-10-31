"""
Texture sampling and animated frame blend helpers for Atlas materials.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from ...node_groups.animated import (
    ensure_animated_frame_blend,
    ensure_animated_normal_blend,
    ensure_animated_specular_blend,
)


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


@dataclass
class SampledAtlasChannels:
    """Output sockets and nodes resulting from sampling all atlas channels."""
    albedo_color: Optional[Any] = None
    albedo_alpha: Optional[Any] = None
    albedo_node: Optional[Any] = None
    overlay_color: Optional[Any] = None
    overlay_alpha: Optional[Any] = None
    overlay_node: Optional[Any] = None
    normal_color: Optional[Any] = None
    orm_color: Optional[Any] = None
    orm_alpha: Optional[Any] = None
    aux_color: Optional[Any] = None


def sample_all_atlas_channels(
    nodes: Any,
    links: Any,
    frame_tex: Any,
    images: Dict[str, Any],
    *,
    is_animated: bool,
    target_uv_output: Any,
    anim_curr_uv: Any,
    anim_next_uv: Any,
    blend_factor_sock: Any,
    active_sample_uv: Any,
) -> SampledAtlasChannels:
    """Sample all active atlas texture channels and return their output sockets."""
    albedo_out_color, albedo_out_alpha, albedo_node = sample_color_channel(
        nodes,
        links,
        frame_tex,
        images.get("albedo_img"),
        name_prefix="Atlas Albedo Texture",
        is_animated=is_animated,
        anim_curr_uv=anim_curr_uv,
        anim_next_uv=anim_next_uv,
        blend_factor_sock=blend_factor_sock,
        static_uv=target_uv_output,
        y_current=420,
        y_next=160,
        y_blend=300,
        y_static=300,
        blend_group_getter=ensure_animated_frame_blend,
        blend_group_name="Animated Frame Blend",
    )

    overlay_out_color, overlay_out_alpha, overlay_node = sample_color_channel(
        nodes,
        links,
        frame_tex,
        images.get("overlay_img"),
        name_prefix="Atlas Overlay Texture",
        is_animated=is_animated,
        anim_curr_uv=anim_curr_uv,
        anim_next_uv=anim_next_uv,
        blend_factor_sock=blend_factor_sock,
        static_uv=target_uv_output,
        y_current=940,
        y_next=680,
        y_blend=810,
        y_static=580,
        blend_group_getter=ensure_animated_frame_blend,
        blend_group_name="Animated Overlay Blend",
    )

    normal_out_color = sample_normal_channel(
        nodes,
        links,
        frame_tex,
        images.get("normal_img"),
        is_animated=is_animated,
        anim_curr_uv=anim_curr_uv,
        anim_next_uv=anim_next_uv,
        blend_factor_sock=blend_factor_sock,
        active_sample_uv=active_sample_uv,
        blend_group_getter=ensure_animated_normal_blend,
    )

    orm_out_color, orm_out_alpha = sample_specular_channel(
        nodes,
        links,
        frame_tex,
        images.get("orm_img"),
        name_prefix="Atlas ORM Texture",
        blend_group_name="Animated ORM Blend",
        is_animated=is_animated,
        anim_curr_uv=anim_curr_uv,
        anim_next_uv=anim_next_uv,
        blend_factor_sock=blend_factor_sock,
        active_sample_uv=active_sample_uv,
        y_current=-520,
        y_next=-780,
        y_blend=-650,
        y_static=-520,
        blend_group_getter=ensure_animated_specular_blend,
    )

    aux_out_color, _ = sample_specular_channel(
        nodes,
        links,
        frame_tex,
        images.get("aux_img"),
        name_prefix="Atlas Aux Texture",
        blend_group_name="Animated Aux Blend",
        is_animated=is_animated,
        anim_curr_uv=anim_curr_uv,
        anim_next_uv=anim_next_uv,
        blend_factor_sock=blend_factor_sock,
        active_sample_uv=active_sample_uv,
        y_current=-1040,
        y_next=-1300,
        y_blend=-1170,
        y_static=-1040,
        blend_group_getter=ensure_animated_specular_blend,
    )

    return SampledAtlasChannels(
        albedo_color=albedo_out_color,
        albedo_alpha=albedo_out_alpha,
        albedo_node=albedo_node,
        overlay_color=overlay_out_color,
        overlay_alpha=overlay_out_alpha,
        overlay_node=overlay_node,
        normal_color=normal_out_color,
        orm_color=orm_out_color,
        orm_alpha=orm_out_alpha,
        aux_color=aux_out_color,
    )

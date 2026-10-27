"""
Pipeline stage builders for Atlas materials: UV tiling, animation scheduling, and biome tinting.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from ...node_groups.atlas_uv_tiling import ensure_atlas_uv_tiling
from ...node_groups.biome import ensure_biome_tint
from ...node_groups.animated import (
    ensure_animation_scheduler,
    ensure_animated_uv_mapping,
)
from ..constants import (
    ATTR_UV_TRANSFORM,
    ATTR_UV_ROTATION,
    ATTR_BIOME_TINT_DATA,
    ATTR_BIOME_TINT_COLOR,
)


def build_atlas_uv_pipeline(
    nodes: Any,
    links: Any,
    frame_uv: Any,
    target_uv_map: str,
    use_attribute_node: bool,
    atlas_width: float,
    atlas_height: float,
    tile_width: float,
    tile_height: float,
    is_animated: bool,
) -> Tuple[Any, Any, Any, Optional[Any], Any]:
    """
    Build UV map, attribute tiling decoding, and optional animation scheduler/UV mapping.
    Returns `(target_uv_output, anim_curr_uv, anim_next_uv, blend_factor_sock, active_sample_uv)`.
    """
    uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.name = "UV Map"
    uv_node.location = (-2200, 150)
    uv_node.uv_map = target_uv_map
    uv_node.parent = frame_uv

    target_uv_output = uv_node.outputs["UV"]

    if use_attribute_node:
        tiling_group = ensure_atlas_uv_tiling()
        if tiling_group:
            attr_transform = nodes.new("ShaderNodeAttribute")
            attr_transform.name = "MTK UV Transform"
            attr_transform.location = (-2200, -50)
            attr_transform.attribute_name = ATTR_UV_TRANSFORM
            attr_transform.attribute_type = "GEOMETRY"
            attr_transform.parent = frame_uv

            attr_rotation = nodes.new("ShaderNodeAttribute")
            attr_rotation.name = "MTK UV Rotation"
            attr_rotation.location = (-2200, -280)
            attr_rotation.attribute_name = ATTR_UV_ROTATION
            attr_rotation.attribute_type = "GEOMETRY"
            attr_rotation.parent = frame_uv

            sep_tf = nodes.new("ShaderNodeSeparateColor")
            sep_tf.name = "Separate UV Transform"
            sep_tf.location = (-1950, -50)
            sep_tf.parent = frame_uv
            links.new(attr_transform.outputs["Color"], sep_tf.inputs["Color"])

            red_sock = sep_tf.outputs.get("Red") or sep_tf.outputs[0]
            green_sock = sep_tf.outputs.get("Green") or sep_tf.outputs[1]
            blue_sock = sep_tf.outputs.get("Blue") or sep_tf.outputs[2]

            scale_comb = nodes.new("ShaderNodeCombineXYZ")
            scale_comb.name = "Combine Scale"
            scale_comb.location = (-1720, 100)
            scale_comb.inputs["Z"].default_value = 1.0
            scale_comb.parent = frame_uv
            links.new(red_sock, scale_comb.inputs["X"])
            links.new(green_sock, scale_comb.inputs["Y"])

            loc_comb = nodes.new("ShaderNodeCombineXYZ")
            loc_comb.name = "Combine Location"
            loc_comb.location = (-1720, -70)
            loc_comb.inputs["Z"].default_value = 0.0
            loc_comb.parent = frame_uv
            links.new(blue_sock, loc_comb.inputs["X"])
            links.new(attr_transform.outputs["Alpha"], loc_comb.inputs["Y"])

            rot_comb = nodes.new("ShaderNodeCombineXYZ")
            rot_comb.name = "Combine Rotation"
            rot_comb.location = (-1720, -240)
            rot_comb.inputs["X"].default_value = 0.0
            rot_comb.inputs["Y"].default_value = 0.0
            rot_comb.parent = frame_uv
            rot_factor = (
                attr_rotation.outputs.get("Factor")
                or attr_rotation.outputs.get("Fac")
                or attr_rotation.outputs[2]
            )
            links.new(rot_factor, rot_comb.inputs["Z"])

            tiling_node = nodes.new("ShaderNodeGroup")
            tiling_node.name = "Atlas UV Tiling"
            tiling_node.node_tree = tiling_group
            tiling_node.location = (-1450, 0)
            tiling_node.inputs["Atlas Width"].default_value = float(atlas_width)
            tiling_node.inputs["Atlas Height"].default_value = float(atlas_height)
            tiling_node.inputs["Tile Width"].default_value = float(tile_width)
            tiling_node.inputs["Tile Height"].default_value = float(tile_height)
            tiling_node.parent = frame_uv

            links.new(uv_node.outputs["UV"], tiling_node.inputs["Vector"])
            links.new(scale_comb.outputs["Vector"], tiling_node.inputs["Scale"])
            links.new(loc_comb.outputs["Vector"], tiling_node.inputs["Location"])
            links.new(rot_comb.outputs["Vector"], tiling_node.inputs["Rotation"])

            target_uv_output = tiling_node.outputs["Atlas UV"]

    anim_curr_uv = target_uv_output
    anim_next_uv = target_uv_output
    blend_factor_sock = None

    if (
        is_animated
        and ensure_animated_uv_mapping is not None
        and ensure_animation_scheduler is not None
    ):
        sched_group = ensure_animation_scheduler()
        uv_map_group = ensure_animated_uv_mapping()
        if sched_group and uv_map_group:
            attr_anim = nodes.new("ShaderNodeAttribute")
            attr_anim.name = "Face Anim Timing"
            attr_anim.attribute_type = "GEOMETRY"
            attr_anim.attribute_name = "mtk_anim_timing"
            attr_anim.location = (-2150, 350)
            attr_anim.parent = frame_uv

            sep_anim = nodes.new("ShaderNodeSeparateXYZ")
            sep_anim.name = "Separate Anim Timing"
            sep_anim.location = (-1920, 350)
            sep_anim.parent = frame_uv
            links.new(attr_anim.outputs["Vector"], sep_anim.inputs["Vector"])

            attr_fsize = nodes.new("ShaderNodeAttribute")
            attr_fsize.name = "Face Anim Frame Size"
            attr_fsize.attribute_type = "GEOMETRY"
            attr_fsize.attribute_name = "mtk_anim_frame_size"
            attr_fsize.location = (-2150, 100)
            attr_fsize.parent = frame_uv

            sep_fsize = nodes.new("ShaderNodeSeparateXYZ")
            sep_fsize.name = "Separate Anim Frame Size"
            sep_fsize.location = (-1920, 100)
            sep_fsize.parent = frame_uv
            links.new(attr_fsize.outputs["Vector"], sep_fsize.inputs["Vector"])

            sched_node = nodes.new("ShaderNodeGroup")
            sched_node.name = "Animation Scheduler"
            sched_node.node_tree = sched_group
            sched_node.location = (-1700, 350)
            sched_node.parent = frame_uv
            links.new(sep_anim.outputs["X"], sched_node.inputs["Total Frames"])
            links.new(sep_anim.outputs["Y"], sched_node.inputs["Frametime"])
            links.new(sep_anim.outputs["Z"], sched_node.inputs["Interpolate"])

            anim_uv_node = nodes.new("ShaderNodeGroup")
            anim_uv_node.name = "Animated UV Mapping"
            anim_uv_node.node_tree = uv_map_group
            anim_uv_node.location = (-1450, 350)
            anim_uv_node.inputs["Frame Width"].default_value = float(tile_width)
            anim_uv_node.inputs["Frame Height"].default_value = float(tile_height)
            anim_uv_node.inputs["Image Width"].default_value = float(atlas_width)
            anim_uv_node.inputs["Image Height"].default_value = float(atlas_height)
            anim_uv_node.inputs["Atlas Mode"].default_value = 1.0
            anim_uv_node.parent = frame_uv

            links.new(sep_fsize.outputs["X"], anim_uv_node.inputs["Frame Width"])
            links.new(sep_fsize.outputs["Y"], anim_uv_node.inputs["Frame Height"])
            links.new(target_uv_output, anim_uv_node.inputs["Vector"])
            links.new(sched_node.outputs["Current Frame"], anim_uv_node.inputs["Current Frame"])
            links.new(sched_node.outputs["Next Frame"], anim_uv_node.inputs["Next Frame"])
            links.new(sched_node.outputs["Blend Factor"], anim_uv_node.inputs["Blend Factor"])

            anim_curr_uv = anim_uv_node.outputs["Current UV"]
            anim_next_uv = anim_uv_node.outputs["Next UV"]
            blend_factor_sock = anim_uv_node.outputs["Blend Factor"]

    active_sample_uv = anim_curr_uv if is_animated else target_uv_output
    return target_uv_output, anim_curr_uv, anim_next_uv, blend_factor_sock, active_sample_uv


def build_biome_tint_pipeline(
    nodes: Any,
    links: Any,
    frame_biome: Any,
    enable_biome_tint: bool,
    albedo_out_color: Any,
    albedo_out_alpha: Any,
    overlay_out_color: Optional[Any],
    overlay_out_alpha: Optional[Any],
) -> Optional[Any]:
    """
    Build biome tint decoding nodes and hook up tint data / color attributes.
    Returns `tint_node` (or None).
    """
    if not enable_biome_tint or albedo_out_color is None:
        return None

    biome_tint_group = ensure_biome_tint()
    if not biome_tint_group:
        return None

    tint_node = nodes.new("ShaderNodeGroup")
    tint_node.name = "MC Biome Tint"
    tint_node.node_tree = biome_tint_group
    tint_node.location = (200, 350)
    if frame_biome:
        tint_node.parent = frame_biome

    links.new(albedo_out_color, tint_node.inputs["Base Color"])
    links.new(albedo_out_alpha, tint_node.inputs["Base Alpha"])
    if overlay_out_color is not None:
        links.new(overlay_out_color, tint_node.inputs["Overlay Color"])
        links.new(overlay_out_alpha, tint_node.inputs["Overlay Alpha"])

    attr_tint_data = nodes.new("ShaderNodeAttribute")
    attr_tint_data.name = "Attr Biome Tint Data"
    attr_tint_data.attribute_name = ATTR_BIOME_TINT_DATA
    attr_tint_data.attribute_type = "GEOMETRY"
    attr_tint_data.location = (-700, 350)
    if frame_biome:
        attr_tint_data.parent = frame_biome

    sep_tint_data = nodes.new("ShaderNodeSeparateColor")
    sep_tint_data.name = "Separate Biome Tint Data"
    sep_tint_data.location = (-450, 350)
    if frame_biome:
        sep_tint_data.parent = frame_biome
    links.new(attr_tint_data.outputs["Color"], sep_tint_data.inputs["Color"])

    red_w = sep_tint_data.outputs.get("Red") or sep_tint_data.outputs[0]
    green_w = sep_tint_data.outputs.get("Green") or sep_tint_data.outputs[1]
    blue_w = sep_tint_data.outputs.get("Blue") or sep_tint_data.outputs[2]
    links.new(red_w, tint_node.inputs["Base Tint Weight"])
    links.new(green_w, tint_node.inputs["Overlay Tint Weight"])
    links.new(blue_w, tint_node.inputs["Tint Weight"])

    attr_tint_col = nodes.new("ShaderNodeAttribute")
    attr_tint_col.name = "Attr Biome Tint Color"
    attr_tint_col.attribute_name = ATTR_BIOME_TINT_COLOR
    attr_tint_col.attribute_type = "GEOMETRY"
    attr_tint_col.location = (-450, 100)
    if frame_biome:
        attr_tint_col.parent = frame_biome

    links.new(attr_tint_col.outputs["Color"], tint_node.inputs["Tint Color"])
    return tint_node

"""
Atlas Chunk Material Builder (MtkPackedV1 standard PBR).

Builds a standard Principled BSDF material from the Rust-predecoded atlas sheets:

- ``{stem}.png``      albedo (sRGB, alpha = opacity)
- ``{stem}_n.png``    OpenGL normal RGB + height A (Non-Color)
- ``{stem}_orm.png``  AO / roughness / metallic / emission mask (Non-Color)
- ``{stem}_aux.png``  encoded IOR / porosity / SSS / transmission (Non-Color)
- ``{stem}_overlay.png`` albedo overlay (sRGB)

There is no LabPBR decoder and no per-face game-semantic branch here. The only
Minecraft-specific stages that remain are UV tiling, biome tinting and animation.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from ...node_groups.atlas_uv_tiling import ensure_atlas_uv_tiling
from ...node_groups.biome import ensure_biome_tint
from ...node_groups.animated import (
    ensure_animation_scheduler,
    ensure_animated_uv_mapping,
    ensure_animated_frame_blend,
    ensure_animated_normal_blend,
    ensure_animated_specular_blend,
)
from ..constants import (
    ATTR_UV_TRANSFORM,
    ATTR_UV_ROTATION,
    ATTR_BIOME_TINT_DATA,
    ATTR_BIOME_TINT_COLOR,
)
from .image_utils import (
    ensure_material_node_tree,
    get_or_create_image,
    _create_frame,
    set_material_displacement_method,
)
from .layout import auto_layout_material
from .pbr_graph import build_pbr_shading
from .shading_config import resolve_material_shading_config
from .template import (
    preload_atlas_images,
    register_archetype_material,
    try_clone_material,
)

PBR_LAYOUT_VERSION = "mtk_packed_v1"


def build_atlas_chunk_material(
    chunk_id: int,
    albedo_path: str | Path,
    normal_path: Optional[str | Path] = None,
    orm_path: Optional[str | Path] = None,
    aux_path: Optional[str | Path] = None,
    overlay_path: Optional[str | Path] = None,
    category: str = "blocks",
    category_chunk_index: int = 1,
    is_animated: bool = False,
    stack_fingerprint: Optional[str] = None,
    material_name: Optional[str] = None,
    use_attribute_node: bool = True,
    atlas_width: float = 4096.0,
    atlas_height: float = 4096.0,
    tile_width: float = 16.0,
    tile_height: float = 16.0,
    force_rebuild: bool = False,
    uv_map_name: Optional[str] = None,
    render_engine: Optional[str] = None,
    disable_subsurface: Optional[bool] = None,
    chunk_stem: Optional[str] = None,
    enable_vertex_ao: Optional[bool] = None,
    enable_biome_tint: Optional[bool] = None,
) -> Optional[Any]:
    """Build or update an Atlas Chunk material with standard Principled PBR."""
    if not HAS_BPY:
        return None

    if enable_biome_tint is None:
        # Minecraft biome tinting only applies to 'blocks' category atlases
        # (grass, foliage, water, etc.). Other categories (items, chests, entities,
        # particles, etc.) never have biome tint.
        enable_biome_tint = (category == "blocks")
    else:
        enable_biome_tint = bool(enable_biome_tint)

    if material_name:
        mat_name = material_name
    elif is_animated:
        mat_name = f"MTK:Atlas:{category}:anim:{category_chunk_index:03}"
    else:
        mat_name = f"MTK:Atlas:{category}:{category_chunk_index:03}"

    mat = bpy.data.materials.get(mat_name)
    target_uv_map = uv_map_name or "UVMap"
    is_stale_fingerprint = bool(
        mat is not None
        and stack_fingerprint
        and mat.get("mtk_stack_fingerprint") != stack_fingerprint
    )
    is_stale_layout = bool(
        mat is not None and mat.get("mtk_pbr_layout") != PBR_LAYOUT_VERSION
    )
    is_stale_biome_tint = bool(
        mat is not None
        and mat.get("mtk_has_biome_tint") is not None
        and mat.get("mtk_has_biome_tint") != enable_biome_tint
    )
    if (
        not force_rebuild
        and not is_stale_fingerprint
        and not is_stale_layout
        and not is_stale_biome_tint
        and mat is not None
        and getattr(mat, "node_tree", None)
        and len(mat.node_tree.nodes) > 0
    ):
        if (
            mat.get("mtk_atlas_chunk_id") == chunk_id
            and mat.get("mtk_uv_map_name", "UVMap") == target_uv_map
        ):
            return mat

    image_reload_needed = force_rebuild or is_stale_fingerprint or is_stale_layout

    images = preload_atlas_images(
        category=category,
        category_chunk_index=category_chunk_index,
        is_animated=is_animated,
        albedo_path=albedo_path,
        overlay_path=overlay_path,
        normal_path=normal_path,
        orm_path=orm_path,
        aux_path=aux_path,
        image_reload_needed=image_reload_needed,
        chunk_stem=chunk_stem,
    )
    has_overlay = images["has_overlay"]
    has_normal = images["has_normal"]
    has_orm = images["has_orm"]
    has_aux = images["has_aux"]
    albedo_img = images["albedo_img"]
    overlay_img = images["overlay_img"]
    normal_img = images["normal_img"]
    orm_img = images["orm_img"]
    aux_img = images["aux_img"]

    cloned, template_key = try_clone_material(
        mat_name,
        chunk_id=chunk_id,
        category=category,
        category_chunk_index=category_chunk_index,
        is_animated=is_animated,
        use_attribute_node=use_attribute_node,
        target_uv_map=target_uv_map,
        stack_fingerprint=stack_fingerprint,
        has_overlay=has_overlay,
        normal_path=normal_path,
        orm_path=orm_path,
        aux_path=aux_path,
        images=images,
        atlas_width=atlas_width,
        atlas_height=atlas_height,
        tile_width=tile_width,
        tile_height=tile_height,
        render_engine=render_engine,
        disable_subsurface=disable_subsurface,
        enable_vertex_ao=enable_vertex_ao,
        enable_biome_tint=enable_biome_tint,
    )
    if cloned is not None:
        return cloned

    if mat is None:
        mat = bpy.data.materials.new(name=mat_name)

    # Authoritative lightweight custom properties.
    mat["mtk_material_mode"] = "ATLAS"
    mat["mtk_pbr_layout"] = PBR_LAYOUT_VERSION
    mat["mtk_has_pbr"] = bool(has_normal or has_orm or has_aux)
    mat["mtk_atlas_category"] = category
    mat["mtk_atlas_chunk_id"] = chunk_id
    mat["mtk_atlas_chunk_index"] = category_chunk_index
    mat["mtk_is_animated"] = is_animated
    mat["mtk_uv_map_name"] = target_uv_map
    mat["mtk_has_overlay"] = has_overlay
    mat["mtk_has_biome_tint"] = enable_biome_tint
    mat["mtk_template_key"] = template_key
    if stack_fingerprint:
        mat["mtk_stack_fingerprint"] = stack_fingerprint

    ensure_material_node_tree(mat)
    mat.use_fake_user = False
    set_material_displacement_method(mat, "BOTH")

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # -------------------------------------------------------------------------
    # 0. Layout frames
    # -------------------------------------------------------------------------
    frame_uv = _create_frame(nodes, "Frame_UV", "UV Coordinates & Tiling", (0.15, 0.25, 0.40))
    frame_tex = _create_frame(nodes, "Frame_Textures", "Texture Maps Input", (0.15, 0.35, 0.25))
    frame_biome = (
        _create_frame(nodes, "Frame_Biome", "Biome Tint & Colormap Decoding", (0.35, 0.25, 0.15))
        if enable_biome_tint
        else None
    )
    frame_shading = _create_frame(nodes, "Frame_Shading", "Standard PBR Shading", (0.30, 0.20, 0.35))
    frame_output = _create_frame(nodes, "Frame_Output", "Material Output", (0.20, 0.20, 0.20))

    output_node = nodes.new("ShaderNodeOutputMaterial")
    output_node.name = "Material Output"
    output_node.location = (1400, 0)
    output_node.parent = frame_output

    # -------------------------------------------------------------------------
    # 1. UV & coordinate pipeline
    # -------------------------------------------------------------------------
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
            rot_factor = attr_rotation.outputs.get("Factor") or attr_rotation.outputs.get("Fac") or attr_rotation.outputs[2]
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

    # -------------------------------------------------------------------------
    # 2. Animated UV mapping (all maps share one frame clock)
    # -------------------------------------------------------------------------
    anim_uv_node = None
    anim_curr_uv = target_uv_output
    anim_next_uv = target_uv_output
    blend_factor_sock = None

    if is_animated and ensure_animated_uv_mapping is not None and ensure_animation_scheduler is not None:
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

    # -------------------------------------------------------------------------
    # 3. Albedo + overlay
    # -------------------------------------------------------------------------
    albedo_node = None
    albedo_out_color = None
    albedo_out_alpha = None
    if albedo_img:
        if is_animated and anim_uv_node is not None and ensure_animated_frame_blend is not None:
            albedo_node = nodes.new("ShaderNodeTexImage")
            albedo_node.name = "Atlas Albedo Texture (Current)"
            albedo_node.image = albedo_img
            albedo_node.interpolation = "Closest"
            albedo_node.extension = "CLIP"
            albedo_node.location = (-1150, 420)
            albedo_node.parent = frame_tex
            links.new(anim_curr_uv, albedo_node.inputs["Vector"])

            albedo_next_node = nodes.new("ShaderNodeTexImage")
            albedo_next_node.name = "Atlas Albedo Texture (Next)"
            albedo_next_node.image = albedo_img
            albedo_next_node.interpolation = "Closest"
            albedo_next_node.extension = "CLIP"
            albedo_next_node.location = (-1150, 160)
            albedo_next_node.parent = frame_tex
            links.new(anim_next_uv, albedo_next_node.inputs["Vector"])

            blend_group = ensure_animated_frame_blend()
            if blend_group:
                anim_blend_node = nodes.new("ShaderNodeGroup")
                anim_blend_node.name = "Animated Frame Blend"
                anim_blend_node.node_tree = blend_group
                anim_blend_node.location = (-880, 300)
                anim_blend_node.parent = frame_tex
                links.new(albedo_node.outputs["Color"], anim_blend_node.inputs["Current Color"])
                links.new(albedo_next_node.outputs["Color"], anim_blend_node.inputs["Next Color"])
                links.new(albedo_node.outputs["Alpha"], anim_blend_node.inputs["Current Alpha"])
                links.new(albedo_next_node.outputs["Alpha"], anim_blend_node.inputs["Next Alpha"])
                if blend_factor_sock:
                    links.new(blend_factor_sock, anim_blend_node.inputs["Blend Factor"])
                albedo_out_color = anim_blend_node.outputs["Color"]
                albedo_out_alpha = anim_blend_node.outputs["Alpha"]
            else:
                albedo_out_color = albedo_node.outputs["Color"]
                albedo_out_alpha = albedo_node.outputs["Alpha"]
        else:
            albedo_node = nodes.new("ShaderNodeTexImage")
            albedo_node.name = "Atlas Albedo Texture"
            albedo_node.image = albedo_img
            albedo_node.interpolation = "Closest"
            albedo_node.extension = "CLIP"
            albedo_node.location = (-1150, 300)
            albedo_node.parent = frame_tex
            links.new(target_uv_output, albedo_node.inputs["Vector"])
            albedo_out_color = albedo_node.outputs["Color"]
            albedo_out_alpha = albedo_node.outputs["Alpha"]

    overlay_node = None
    overlay_out_color = None
    overlay_out_alpha = None
    if overlay_img:
            if is_animated and anim_uv_node is not None and ensure_animated_frame_blend is not None:
                overlay_node = nodes.new("ShaderNodeTexImage")
                overlay_node.name = "Atlas Overlay Texture (Current)"
                overlay_node.image = overlay_img
                overlay_node.interpolation = "Closest"
                overlay_node.extension = "CLIP"
                overlay_node.location = (-1150, 940)
                overlay_node.parent = frame_tex
                links.new(anim_curr_uv, overlay_node.inputs["Vector"])

                overlay_next_node = nodes.new("ShaderNodeTexImage")
                overlay_next_node.name = "Atlas Overlay Texture (Next)"
                overlay_next_node.image = overlay_img
                overlay_next_node.interpolation = "Closest"
                overlay_next_node.extension = "CLIP"
                overlay_next_node.location = (-1150, 680)
                overlay_next_node.parent = frame_tex
                links.new(anim_next_uv, overlay_next_node.inputs["Vector"])

                blend_group = ensure_animated_frame_blend()
                if blend_group:
                    anim_overlay_blend = nodes.new("ShaderNodeGroup")
                    anim_overlay_blend.name = "Animated Overlay Blend"
                    anim_overlay_blend.node_tree = blend_group
                    anim_overlay_blend.location = (-880, 810)
                    anim_overlay_blend.parent = frame_tex
                    links.new(overlay_node.outputs["Color"], anim_overlay_blend.inputs["Current Color"])
                    links.new(overlay_next_node.outputs["Color"], anim_overlay_blend.inputs["Next Color"])
                    links.new(overlay_node.outputs["Alpha"], anim_overlay_blend.inputs["Current Alpha"])
                    links.new(overlay_next_node.outputs["Alpha"], anim_overlay_blend.inputs["Next Alpha"])
                    if blend_factor_sock:
                        links.new(blend_factor_sock, anim_overlay_blend.inputs["Blend Factor"])
                    overlay_out_color = anim_overlay_blend.outputs["Color"]
                    overlay_out_alpha = anim_overlay_blend.outputs["Alpha"]
                else:
                    overlay_out_color = overlay_node.outputs["Color"]
                    overlay_out_alpha = overlay_node.outputs["Alpha"]
            else:
                overlay_node = nodes.new("ShaderNodeTexImage")
                overlay_node.name = "Atlas Overlay Texture"
                overlay_node.image = overlay_img
                overlay_node.interpolation = "Closest"
                overlay_node.extension = "CLIP"
                overlay_node.location = (-1150, 580)
                overlay_node.parent = frame_tex
                links.new(target_uv_output, overlay_node.inputs["Vector"])
                overlay_out_color = overlay_node.outputs["Color"]
                overlay_out_alpha = overlay_node.outputs["Alpha"]

    # -------------------------------------------------------------------------
    # 4. Canonical PBR maps: normal+height, ORM+emission, aux
    # -------------------------------------------------------------------------
    normal_out_color = None
    if normal_img:
            if is_animated and anim_uv_node is not None and ensure_animated_normal_blend is not None:
                normal_node = nodes.new("ShaderNodeTexImage")
                normal_node.name = "Atlas Normal Texture (Current)"
                normal_node.image = normal_img
                normal_node.interpolation = "Closest"
                normal_node.extension = "CLIP"
                normal_node.location = (-1150, 20)
                normal_node.parent = frame_tex
                links.new(anim_curr_uv, normal_node.inputs["Vector"])

                normal_next_node = nodes.new("ShaderNodeTexImage")
                normal_next_node.name = "Atlas Normal Texture (Next)"
                normal_next_node.image = normal_img
                normal_next_node.interpolation = "Closest"
                normal_next_node.extension = "CLIP"
                normal_next_node.location = (-1150, -240)
                normal_next_node.parent = frame_tex
                links.new(anim_next_uv, normal_next_node.inputs["Vector"])

                norm_blend_group = ensure_animated_normal_blend()
                if norm_blend_group:
                    anim_norm_blend = nodes.new("ShaderNodeGroup")
                    anim_norm_blend.name = "Animated Normal Blend"
                    anim_norm_blend.node_tree = norm_blend_group
                    anim_norm_blend.location = (-880, -100)
                    anim_norm_blend.parent = frame_tex
                    links.new(normal_node.outputs["Color"], anim_norm_blend.inputs["Current Normal"])
                    links.new(normal_next_node.outputs["Color"], anim_norm_blend.inputs["Next Normal"])
                    links.new(normal_node.outputs["Alpha"], anim_norm_blend.inputs["Current Height"])
                    links.new(normal_next_node.outputs["Alpha"], anim_norm_blend.inputs["Next Height"])
                    if blend_factor_sock:
                        links.new(blend_factor_sock, anim_norm_blend.inputs["Blend Factor"])
                    normal_out_color = anim_norm_blend.outputs["Normal"]
                else:
                    normal_out_color = normal_node.outputs["Color"]
            else:
                normal_node = nodes.new("ShaderNodeTexImage")
                normal_node.name = "Atlas Normal Texture"
                normal_node.image = normal_img
                normal_node.interpolation = "Closest"
                normal_node.extension = "CLIP"
                normal_node.location = (-1150, 20)
                normal_node.parent = frame_tex
                links.new(active_sample_uv, normal_node.inputs["Vector"])
                normal_out_color = normal_node.outputs["Color"]

    orm_out_color = None
    orm_out_alpha = None
    if orm_img:
            if is_animated and anim_uv_node is not None and ensure_animated_specular_blend is not None:
                orm_node = nodes.new("ShaderNodeTexImage")
                orm_node.name = "Atlas ORM Texture (Current)"
                orm_node.image = orm_img
                orm_node.interpolation = "Closest"
                orm_node.extension = "CLIP"
                orm_node.location = (-1150, -520)
                orm_node.parent = frame_tex
                links.new(anim_curr_uv, orm_node.inputs["Vector"])

                orm_next_node = nodes.new("ShaderNodeTexImage")
                orm_next_node.name = "Atlas ORM Texture (Next)"
                orm_next_node.image = orm_img
                orm_next_node.interpolation = "Closest"
                orm_next_node.extension = "CLIP"
                orm_next_node.location = (-1150, -780)
                orm_next_node.parent = frame_tex
                links.new(anim_next_uv, orm_next_node.inputs["Vector"])

                # The legacy Specular Blend group is a generic RGB+alpha frame blend;
                # reuse it for ORM/Aux instead of introducing another node group.
                orm_blend_group = ensure_animated_specular_blend()
                if orm_blend_group:
                    anim_orm_blend = nodes.new("ShaderNodeGroup")
                    anim_orm_blend.name = "Animated ORM Blend"
                    anim_orm_blend.node_tree = orm_blend_group
                    anim_orm_blend.location = (-880, -650)
                    anim_orm_blend.parent = frame_tex
                    links.new(orm_node.outputs["Color"], anim_orm_blend.inputs["Current Specular"])
                    links.new(orm_next_node.outputs["Color"], anim_orm_blend.inputs["Next Specular"])
                    links.new(orm_node.outputs["Alpha"], anim_orm_blend.inputs["Current Emission"])
                    links.new(orm_next_node.outputs["Alpha"], anim_orm_blend.inputs["Next Emission"])
                    if blend_factor_sock:
                        links.new(blend_factor_sock, anim_orm_blend.inputs["Blend Factor"])
                    orm_out_color = anim_orm_blend.outputs["Specular"]
                    orm_out_alpha = anim_orm_blend.outputs["Emission"]
                else:
                    orm_out_color = orm_node.outputs["Color"]
                    orm_out_alpha = orm_node.outputs["Alpha"]
            else:
                orm_node = nodes.new("ShaderNodeTexImage")
                orm_node.name = "Atlas ORM Texture"
                orm_node.image = orm_img
                orm_node.interpolation = "Closest"
                orm_node.extension = "CLIP"
                orm_node.location = (-1150, -520)
                orm_node.parent = frame_tex
                links.new(active_sample_uv, orm_node.inputs["Vector"])
                orm_out_color = orm_node.outputs["Color"]
                orm_out_alpha = orm_node.outputs["Alpha"]

    aux_out_color = None
    if aux_img:
            if is_animated and anim_uv_node is not None and ensure_animated_specular_blend is not None:
                aux_node = nodes.new("ShaderNodeTexImage")
                aux_node.name = "Atlas Aux Texture (Current)"
                aux_node.image = aux_img
                aux_node.interpolation = "Closest"
                aux_node.extension = "CLIP"
                aux_node.location = (-1150, -1040)
                aux_node.parent = frame_tex
                links.new(anim_curr_uv, aux_node.inputs["Vector"])

                aux_next_node = nodes.new("ShaderNodeTexImage")
                aux_next_node.name = "Atlas Aux Texture (Next)"
                aux_next_node.image = aux_img
                aux_next_node.interpolation = "Closest"
                aux_next_node.extension = "CLIP"
                aux_next_node.location = (-1150, -1300)
                aux_next_node.parent = frame_tex
                links.new(anim_next_uv, aux_next_node.inputs["Vector"])

                aux_blend_group = ensure_animated_specular_blend()
                if aux_blend_group:
                    anim_aux_blend = nodes.new("ShaderNodeGroup")
                    anim_aux_blend.name = "Animated Aux Blend"
                    anim_aux_blend.node_tree = aux_blend_group
                    anim_aux_blend.location = (-880, -1170)
                    anim_aux_blend.parent = frame_tex
                    links.new(aux_node.outputs["Color"], anim_aux_blend.inputs["Current Specular"])
                    links.new(aux_next_node.outputs["Color"], anim_aux_blend.inputs["Next Specular"])
                    links.new(aux_node.outputs["Alpha"], anim_aux_blend.inputs["Current Emission"])
                    links.new(aux_next_node.outputs["Alpha"], anim_aux_blend.inputs["Next Emission"])
                    if blend_factor_sock:
                        links.new(blend_factor_sock, anim_aux_blend.inputs["Blend Factor"])
                    aux_out_color = anim_aux_blend.outputs["Specular"]
                else:
                    aux_out_color = aux_node.outputs["Color"]
            else:
                aux_node = nodes.new("ShaderNodeTexImage")
                aux_node.name = "Atlas Aux Texture"
                aux_node.image = aux_img
                aux_node.interpolation = "Closest"
                aux_node.extension = "CLIP"
                aux_node.location = (-1150, -1040)
                aux_node.parent = frame_tex
                links.new(active_sample_uv, aux_node.inputs["Vector"])
                aux_out_color = aux_node.outputs["Color"]

    # -------------------------------------------------------------------------
    # 5. Biome tint & colormap decoding
    # -------------------------------------------------------------------------
    tint_node = None
    if enable_biome_tint and albedo_out_color is not None:
        biome_tint_group = ensure_biome_tint()
        if biome_tint_group:
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

            # Direct pure-data link: resolved Linear RGBA calculated by Rust is piped straight into Tint Color.
            links.new(attr_tint_col.outputs["Color"], tint_node.inputs["Tint Color"])

    # -------------------------------------------------------------------------
    # 6. Standard Principled PBR shading
    # -------------------------------------------------------------------------
    cfg = resolve_material_shading_config(
        render_engine=render_engine,
        disable_subsurface=disable_subsurface,
        enable_vertex_ao=enable_vertex_ao,
    )

    base_color = tint_node.outputs["Color"] if tint_node else albedo_out_color
    alpha = tint_node.outputs["Alpha"] if tint_node else albedo_out_alpha
    if base_color is None or alpha is None:
        return mat

    final_enable_vertex_ao = (
        bool(enable_vertex_ao)
        if enable_vertex_ao is not None
        else (category == "blocks" and cfg.get("enable_vertex_ao", True))
    )

    build_pbr_shading(
        nodes,
        links,
        output_node,
        frame_shading,
        base_color=base_color,
        alpha=alpha,
        normal_color=normal_out_color,
        orm_color=orm_out_color,
        orm_alpha=orm_out_alpha,
        aux_color=aux_out_color,
        disable_subsurface=cfg["disable_subsurface"],
        emission_strength=cfg["emission_strength"],
        subsurface_method=cfg.get("subsurface_method", "BURLEY"),
        enable_vertex_ao=final_enable_vertex_ao,
    )

    # Automatically format and space nodes based on active channels
    auto_layout_material(
        mat,
        is_animated=is_animated,
        has_overlay=has_overlay,
        has_normal=has_normal,
        has_orm=has_orm,
        has_aux=has_aux,
        use_attribute_node=use_attribute_node,
        has_biome_tint=enable_biome_tint,
    )

    mat["mtk_enable_vertex_ao"] = final_enable_vertex_ao

    # Keep the albedo node active for Solid viewport display.
    if albedo_node:
        for current in nodes:
            current.select = False
        nodes.active = albedo_node
        albedo_node.select = True

    # Alpha / transparency settings (no transmission in v1).
    if hasattr(mat, "surface_render_method"):
        try:
            mat.surface_render_method = "DITHERED"
        except Exception:
            pass
    elif hasattr(mat, "blend_method"):
        try:
            mat.blend_method = "HASHED"
        except Exception:
            pass

    if hasattr(mat, "use_transparency_overlap"):
        try:
            mat.use_transparency_overlap = True
        except Exception:
            pass
    if hasattr(mat, "use_raytrace_refraction"):
        try:
            mat.use_raytrace_refraction = False
        except Exception:
            pass
    if hasattr(mat, "use_screen_refraction"):
        try:
            mat.use_screen_refraction = False
        except Exception:
            pass

    register_archetype_material(mat, template_key)
    return mat

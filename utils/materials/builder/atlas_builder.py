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

from ...node_groups.animated import (
    ensure_animated_frame_blend,
    ensure_animated_normal_blend,
    ensure_animated_specular_blend,
)
from .stage_builders import (
    build_atlas_uv_pipeline,
    build_biome_tint_pipeline,
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
from .texture_sampler import (
    sample_color_channel,
    sample_normal_channel,
    sample_specular_channel,
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
    # 1. UV & animation pipeline
    # -------------------------------------------------------------------------
    (
        target_uv_output,
        anim_curr_uv,
        anim_next_uv,
        blend_factor_sock,
        active_sample_uv,
    ) = build_atlas_uv_pipeline(
        nodes=nodes,
        links=links,
        frame_uv=frame_uv,
        target_uv_map=target_uv_map,
        use_attribute_node=use_attribute_node,
        atlas_width=atlas_width,
        atlas_height=atlas_height,
        tile_width=tile_width,
        tile_height=tile_height,
        is_animated=is_animated,
    )

    # -------------------------------------------------------------------------
    # 3. Albedo + overlay sampling
    # -------------------------------------------------------------------------
    albedo_out_color, albedo_out_alpha, albedo_node = sample_color_channel(
        nodes,
        links,
        frame_tex,
        albedo_img,
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
        overlay_img,
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

    # -------------------------------------------------------------------------
    # 4. Canonical PBR maps: normal+height, ORM+emission, aux
    # -------------------------------------------------------------------------
    normal_out_color = sample_normal_channel(
        nodes,
        links,
        frame_tex,
        normal_img,
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
        orm_img,
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
        aux_img,
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

    # -------------------------------------------------------------------------
    # 5. Biome tint & colormap decoding
    # -------------------------------------------------------------------------
    tint_node = build_biome_tint_pipeline(
        nodes=nodes,
        links=links,
        frame_biome=frame_biome,
        enable_biome_tint=enable_biome_tint,
        albedo_out_color=albedo_out_color,
        albedo_out_alpha=albedo_out_alpha,
        overlay_out_color=overlay_out_color,
        overlay_out_alpha=overlay_out_alpha,
    )

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

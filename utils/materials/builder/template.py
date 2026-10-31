"""
Template material cloning and reuse engine for Atlas Chunk materials.

Provides ultra-fast C++ native cloning of archetypal materials for multi-chunk
atlas setups, avoiding expensive per-material Python node allocation and wiring.
"""

from __future__ import annotations

import os
from typing import Any, Optional

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from .image_utils import get_or_create_image, set_material_displacement_method

PBR_LAYOUT_VERSION = "mtk_packed_v1"


def get_template_key(
    category: str,
    is_animated: bool,
    use_attribute_node: bool,
    has_overlay: bool,
    has_normal: bool,
    has_orm: bool,
    has_aux: bool,
    render_engine: Optional[str] = None,
    disable_subsurface: Optional[bool] = None,
    target_uv_map: str = "UVMap",
    enable_vertex_ao: Optional[bool] = None,
    enable_biome_tint: bool = True,
) -> str:
    """Compute a deterministic key representing the material's node graph topology."""
    return (
        f"{category}|anim={int(is_animated)}|attr={int(use_attribute_node)}|"
        f"ovr={int(has_overlay)}|n={int(has_normal)}|orm={int(has_orm)}|aux={int(has_aux)}|"
        f"eng={render_engine or 'AUTO'}|nosss={int(bool(disable_subsurface))}|"
        f"vao={int(bool(enable_vertex_ao if enable_vertex_ao is not None else True))}|"
        f"tint={int(bool(enable_biome_tint))}|uv={target_uv_map}"
    )


def preload_atlas_images(
    category: str,
    category_chunk_index: int,
    is_animated: bool,
    albedo_path: Any = None,
    overlay_path: Any = None,
    normal_path: Any = None,
    orm_path: Any = None,
    aux_path: Any = None,
    image_reload_needed: bool = False,
    chunk_stem: Optional[str] = None,
    texture_sources: Optional[Dict[str, Dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Retrieve or load all atlas texture image datablocks for a chunk."""
    c_stem = chunk_stem or (
        f"{category}_anim_chunk_{category_chunk_index:03}"
        if is_animated
        else f"{category}_chunk_{category_chunk_index:03}"
    )

    if texture_sources is not None:
        albedo_slot = texture_sources.get("albedo")
        overlay_slot = texture_sources.get("overlay")
        normal_slot = texture_sources.get("normal")
        orm_slot = texture_sources.get("orm")
        aux_slot = texture_sources.get("aux")

        albedo_source = albedo_slot["source"] if albedo_slot else albedo_path
        overlay_source = overlay_slot["source"] if overlay_slot else overlay_path
        normal_source = normal_slot["source"] if normal_slot else normal_path
        orm_source = orm_slot["source"] if orm_slot else orm_path
        aux_source = aux_slot["source"] if aux_slot else aux_path

        albedo_cs = albedo_slot.get("colorspace", "sRGB") if albedo_slot else "sRGB"
        overlay_cs = overlay_slot.get("colorspace", "sRGB") if overlay_slot else "sRGB"
        normal_cs = normal_slot.get("colorspace", "Non-Color") if normal_slot else "Non-Color"
        orm_cs = orm_slot.get("colorspace", "Non-Color") if orm_slot else "Non-Color"
        aux_cs = aux_slot.get("colorspace", "Non-Color") if aux_slot else "Non-Color"

        albedo_cid = albedo_slot.get("chunk_id", f"atlas/textures/{c_stem}.png") if albedo_slot else f"atlas/textures/{c_stem}.png"
        overlay_cid = overlay_slot.get("chunk_id", f"atlas/textures/{c_stem}_overlay.png") if overlay_slot else f"atlas/textures/{c_stem}_overlay.png"
        normal_cid = normal_slot.get("chunk_id", f"atlas/textures/{c_stem}_n.png") if normal_slot else f"atlas/textures/{c_stem}_n.png"
        orm_cid = orm_slot.get("chunk_id", f"atlas/textures/{c_stem}_orm.png") if orm_slot else f"atlas/textures/{c_stem}_orm.png"
        aux_cid = aux_slot.get("chunk_id", f"atlas/textures/{c_stem}_aux.png") if aux_slot else f"atlas/textures/{c_stem}_aux.png"
    else:
        albedo_source = albedo_path
        overlay_source = overlay_path
        normal_source = normal_path
        orm_source = orm_path
        aux_source = aux_path

        albedo_cs, overlay_cs = "sRGB", "sRGB"
        normal_cs, orm_cs, aux_cs = "Non-Color", "Non-Color", "Non-Color"

        albedo_cid = f"atlas/textures/{c_stem}.png"
        overlay_cid = f"atlas/textures/{c_stem}_overlay.png"
        normal_cid = f"atlas/textures/{c_stem}_n.png"
        orm_cid = f"atlas/textures/{c_stem}_orm.png"
        aux_cid = f"atlas/textures/{c_stem}_aux.png"

    albedo_img = (
        get_or_create_image(
            albedo_source,
            colorspace=albedo_cs,
            force_reload=image_reload_needed,
            chunk_id=albedo_cid,
        )
        if albedo_source is not None
        else None
    )
    overlay_img = (
        get_or_create_image(
            overlay_source,
            colorspace=overlay_cs,
            force_reload=image_reload_needed,
            chunk_id=overlay_cid,
        )
        if overlay_source is not None
        else None
    )
    normal_img = (
        get_or_create_image(
            normal_source,
            colorspace=normal_cs,
            force_reload=image_reload_needed,
            chunk_id=normal_cid,
        )
        if normal_source is not None
        else None
    )
    orm_img = (
        get_or_create_image(
            orm_source,
            colorspace=orm_cs,
            force_reload=image_reload_needed,
            chunk_id=orm_cid,
        )
        if orm_source is not None
        else None
    )
    aux_img = (
        get_or_create_image(
            aux_source,
            colorspace=aux_cs,
            force_reload=image_reload_needed,
            chunk_id=aux_cid,
        )
        if aux_source is not None
        else None
    )

    has_overlay = (overlay_img is not None) if HAS_BPY else bool(overlay_source)
    has_normal = (normal_img is not None) if HAS_BPY else bool(normal_source)
    has_orm = (orm_img is not None) if HAS_BPY else bool(orm_source)
    has_aux = (aux_img is not None) if HAS_BPY else bool(aux_source)

    return {
        "c_stem": c_stem,
        "has_overlay": has_overlay,
        "has_normal": has_normal,
        "has_orm": has_orm,
        "has_aux": has_aux,
        "albedo_img": albedo_img,
        "overlay_img": overlay_img,
        "normal_img": normal_img,
        "orm_img": orm_img,
        "aux_img": aux_img,
    }


def find_archetype_material(
    template_key: str,
    stack_fingerprint: Optional[str] = None,
    exclude_name: Optional[str] = None,
) -> Optional[Any]:
    """Find an existing material in bpy.data.materials matching the template key."""
    if not HAS_BPY or not hasattr(bpy, "data") or not hasattr(bpy.data, "materials"):
        return None

    for mat in bpy.data.materials:
        if mat is None or (exclude_name and mat.name == exclude_name):
            continue
        if mat.get("mtk_template_key") != template_key:
            continue
        if mat.get("mtk_pbr_layout") != PBR_LAYOUT_VERSION:
            continue
        if stack_fingerprint and mat.get("mtk_stack_fingerprint") != stack_fingerprint:
            continue
        tree = getattr(mat, "node_tree", None)
        if tree is None or not getattr(tree, "nodes", None) or len(tree.nodes) == 0:
            continue
        return mat

    return None


def register_archetype_material(mat: Any, template_key: str) -> None:
    """Stamp the template key on a material so it can serve as an archetype."""
    if mat is not None:
        mat["mtk_template_key"] = template_key


def clone_atlas_chunk_material(
    archetype: Any,
    target_mat_name: str,
    *,
    chunk_id: int,
    category: str,
    category_chunk_index: int,
    is_animated: bool,
    target_uv_map: str,
    stack_fingerprint: Optional[str],
    has_overlay: bool,
    normal_path: Any = None,
    orm_path: Any = None,
    aux_path: Any = None,
    albedo_img: Any = None,
    normal_img: Any = None,
    orm_img: Any = None,
    aux_img: Any = None,
    overlay_img: Any = None,
    atlas_width: float = 4096.0,
    atlas_height: float = 4096.0,
    tile_width: float = 16.0,
    tile_height: float = 16.0,
    template_key: str = "",
    enable_biome_tint: bool = True,
) -> Optional[Any]:
    """
    Instantly clone the archetype material and rebind chunk-specific images and attributes.
    Bypasses RNA node creation for a ~30x-150x speedup.
    """
    if not HAS_BPY or archetype is None or albedo_img is None:
        return None

    try:
        cloned = archetype.copy()
        cloned.use_fake_user = False
        set_material_displacement_method(cloned, "BOTH")

        existing = bpy.data.materials.get(target_mat_name)
        if existing is not None and existing != cloned:
            try:
                existing.user_remap(cloned)
                bpy.data.materials.remove(existing)
            except Exception:
                pass

        cloned.name = target_mat_name

        # Authoritative lightweight custom properties
        cloned["mtk_material_mode"] = "ATLAS"
        cloned["mtk_pbr_layout"] = PBR_LAYOUT_VERSION
        cloned["mtk_has_pbr"] = bool(normal_img is not None or orm_img is not None or aux_img is not None)
        cloned["mtk_atlas_category"] = category
        cloned["mtk_atlas_chunk_id"] = chunk_id
        cloned["mtk_atlas_chunk_index"] = category_chunk_index
        cloned["mtk_is_animated"] = is_animated
        cloned["mtk_uv_map_name"] = target_uv_map
        cloned["mtk_has_overlay"] = has_overlay
        cloned["mtk_has_biome_tint"] = bool(enable_biome_tint)
        if stack_fingerprint:
            cloned["mtk_stack_fingerprint"] = stack_fingerprint
        if template_key:
            cloned["mtk_template_key"] = template_key

        nodes = cloned.node_tree.nodes

        # Rebind texture image pointers
        image_slots = (
            ("Atlas Albedo Texture", albedo_img),
            ("Atlas Overlay Texture", overlay_img),
            ("Atlas Normal Texture", normal_img),
            ("Atlas ORM Texture", orm_img),
            ("Atlas Aux Texture", aux_img),
        )
        for base_name, img in image_slots:
            if img is None:
                continue
            if not is_animated:
                node = nodes.get(base_name)
                if node is not None:
                    node.image = img
            else:
                for suffix in (" (Current)", " (Next)"):
                    node = nodes.get(f"{base_name}{suffix}")
                    if node is not None:
                        node.image = img

        # Rebind UV Map target
        uv_node = nodes.get("UV Map")
        if uv_node is not None and hasattr(uv_node, "uv_map"):
            uv_node.uv_map = target_uv_map

        # Rebind tiling group inputs if dimensions differ
        tiling_node = nodes.get("Atlas UV Tiling")
        if tiling_node is not None:
            try:
                tiling_node.inputs["Atlas Width"].default_value = float(atlas_width)
                tiling_node.inputs["Atlas Height"].default_value = float(atlas_height)
                tiling_node.inputs["Tile Width"].default_value = float(tile_width)
                tiling_node.inputs["Tile Height"].default_value = float(tile_height)
            except Exception:
                pass

        anim_uv_node = nodes.get("Animated UV Mapping")
        if anim_uv_node is not None:
            try:
                anim_uv_node.inputs["Frame Width"].default_value = float(tile_width)
                anim_uv_node.inputs["Frame Height"].default_value = float(tile_height)
                anim_uv_node.inputs["Image Width"].default_value = float(atlas_width)
                anim_uv_node.inputs["Image Height"].default_value = float(atlas_height)
            except Exception:
                pass

        # Set active node for solid viewport preview
        albedo_node = nodes.get("Atlas Albedo Texture") or nodes.get("Atlas Albedo Texture (Current)")
        if albedo_node is not None:
            for current in nodes:
                current.select = False
            nodes.active = albedo_node
            albedo_node.select = True

        # Render method & transparency properties
        if hasattr(cloned, "surface_render_method"):
            try:
                cloned.surface_render_method = "DITHERED"
            except Exception:
                pass
        elif hasattr(cloned, "blend_method"):
            try:
                cloned.blend_method = "HASHED"
            except Exception:
                pass

        if hasattr(cloned, "use_transparency_overlap"):
            try:
                cloned.use_transparency_overlap = True
            except Exception:
                pass
        if hasattr(cloned, "use_raytrace_refraction"):
            try:
                cloned.use_raytrace_refraction = False
            except Exception:
                pass
        if hasattr(cloned, "use_screen_refraction"):
            try:
                cloned.use_screen_refraction = False
            except Exception:
                pass

        return cloned
    except Exception:
        return None


def try_clone_material(
    target_mat_name: str,
    *,
    chunk_id: int,
    category: str,
    category_chunk_index: int,
    is_animated: bool,
    use_attribute_node: bool,
    target_uv_map: str,
    stack_fingerprint: Optional[str],
    has_overlay: bool,
    normal_path: Any = None,
    orm_path: Any = None,
    aux_path: Any = None,
    images: dict[str, Any],
    atlas_width: float = 4096.0,
    atlas_height: float = 4096.0,
    tile_width: float = 16.0,
    tile_height: float = 16.0,
    render_engine: Optional[str] = None,
    disable_subsurface: Optional[bool] = None,
    enable_vertex_ao: Optional[bool] = None,
    enable_biome_tint: bool = True,
) -> tuple[Optional[Any], str]:
    """
    Check if a matching archetype exists, and if so, clone and return it.
    Returns (cloned_mat, template_key).
    """
    has_normal_flag = images.get("has_normal", (images.get("normal_img") is not None) if HAS_BPY else bool(normal_path))
    has_orm_flag = images.get("has_orm", (images.get("orm_img") is not None) if HAS_BPY else bool(orm_path))
    has_aux_flag = images.get("has_aux", (images.get("aux_img") is not None) if HAS_BPY else bool(aux_path))

    template_key = get_template_key(
        category=category,
        is_animated=is_animated,
        use_attribute_node=use_attribute_node,
        has_overlay=has_overlay,
        has_normal=has_normal_flag,
        has_orm=has_orm_flag,
        has_aux=has_aux_flag,
        render_engine=render_engine,
        disable_subsurface=disable_subsurface,
        target_uv_map=target_uv_map,
        enable_vertex_ao=enable_vertex_ao,
        enable_biome_tint=enable_biome_tint,
    )

    archetype = find_archetype_material(
        template_key,
        stack_fingerprint=stack_fingerprint,
        exclude_name=target_mat_name,
    )
    if archetype is not None:
        cloned = clone_atlas_chunk_material(
            archetype,
            target_mat_name,
            chunk_id=chunk_id,
            category=category,
            category_chunk_index=category_chunk_index,
            is_animated=is_animated,
            target_uv_map=target_uv_map,
            stack_fingerprint=stack_fingerprint,
            has_overlay=has_overlay,
            normal_path=normal_path,
            orm_path=orm_path,
            aux_path=aux_path,
            albedo_img=images.get("albedo_img"),
            normal_img=images.get("normal_img"),
            orm_img=images.get("orm_img"),
            aux_img=images.get("aux_img"),
            overlay_img=images.get("overlay_img"),
            atlas_width=atlas_width,
            atlas_height=atlas_height,
            tile_width=tile_width,
            tile_height=tile_height,
            template_key=template_key,
            enable_biome_tint=enable_biome_tint,
        )
        if cloned is not None:
            return cloned, template_key

    return None, template_key

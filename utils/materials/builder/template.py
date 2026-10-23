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
) -> str:
    """Compute a deterministic key representing the material's node graph topology."""
    return (
        f"{category}|anim={int(is_animated)}|attr={int(use_attribute_node)}|"
        f"ovr={int(has_overlay)}|n={int(has_normal)}|orm={int(has_orm)}|aux={int(has_aux)}|"
        f"eng={render_engine or 'AUTO'}|nosss={int(bool(disable_subsurface))}|uv={target_uv_map}"
    )


def preload_atlas_images(
    category: str,
    category_chunk_index: int,
    is_animated: bool,
    albedo_path: Any,
    overlay_path: Any,
    normal_path: Any,
    orm_path: Any,
    aux_path: Any,
    image_reload_needed: bool,
    chunk_stem: Optional[str] = None,
) -> dict[str, Any]:
    """Retrieve or load all atlas texture image datablocks for a chunk."""
    c_stem = chunk_stem or (
        f"{category}_anim_chunk_{category_chunk_index:03}"
        if is_animated
        else f"{category}_chunk_{category_chunk_index:03}"
    )

    albedo_img = get_or_create_image(
        albedo_path,
        colorspace="sRGB",
        force_reload=image_reload_needed,
        chunk_id=f"atlas/textures/{c_stem}.png",
    )
    overlay_img = (
        get_or_create_image(
            overlay_path,
            colorspace="sRGB",
            force_reload=image_reload_needed,
            chunk_id=f"atlas/textures/{c_stem}_overlay.png",
        )
        if overlay_path
        else None
    )
    normal_img = (
        get_or_create_image(
            normal_path,
            colorspace="Non-Color",
            force_reload=image_reload_needed,
            chunk_id=f"atlas/textures/{c_stem}_n.png",
        )
        if normal_path
        else None
    )
    orm_img = (
        get_or_create_image(
            orm_path,
            colorspace="Non-Color",
            force_reload=image_reload_needed,
            chunk_id=f"atlas/textures/{c_stem}_orm.png",
        )
        if orm_path
        else None
    )
    aux_img = (
        get_or_create_image(
            aux_path,
            colorspace="Non-Color",
            force_reload=image_reload_needed,
            chunk_id=f"atlas/textures/{c_stem}_aux.png",
        )
        if aux_path
        else None
    )

    has_overlay = (overlay_img is not None) if HAS_BPY else bool(overlay_path)

    return {
        "c_stem": c_stem,
        "has_overlay": has_overlay,
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
        cloned["mtk_has_pbr"] = bool(normal_path or orm_path or aux_path)
        cloned["mtk_atlas_category"] = category
        cloned["mtk_atlas_chunk_id"] = chunk_id
        cloned["mtk_atlas_chunk_index"] = category_chunk_index
        cloned["mtk_is_animated"] = is_animated
        cloned["mtk_uv_map_name"] = target_uv_map
        cloned["mtk_has_overlay"] = has_overlay
        if stack_fingerprint:
            cloned["mtk_stack_fingerprint"] = stack_fingerprint
        if template_key:
            cloned["mtk_template_key"] = template_key

        nodes = cloned.node_tree.nodes

        # Rebind texture image pointers
        if not is_animated:
            if albedo_img is not None:
                albedo_node = nodes.get("Atlas Albedo Texture")
                if albedo_node is not None:
                    albedo_node.image = albedo_img
            if overlay_img is not None:
                ovr_node = nodes.get("Atlas Overlay Texture")
                if ovr_node is not None:
                    ovr_node.image = overlay_img
            if normal_img is not None:
                norm_node = nodes.get("Atlas Normal Texture")
                if norm_node is not None:
                    norm_node.image = normal_img
            if orm_img is not None:
                orm_node = nodes.get("Atlas ORM Texture")
                if orm_node is not None:
                    orm_node.image = orm_img
            if aux_img is not None:
                aux_node = nodes.get("Atlas Aux Texture")
                if aux_node is not None:
                    aux_node.image = aux_img
        else:
            if albedo_img is not None:
                for suffix in (" (Current)", " (Next)"):
                    n = nodes.get(f"Atlas Albedo Texture{suffix}")
                    if n is not None:
                        n.image = albedo_img
            if overlay_img is not None:
                for suffix in (" (Current)", " (Next)"):
                    n = nodes.get(f"Atlas Overlay Texture{suffix}")
                    if n is not None:
                        n.image = overlay_img
            if normal_img is not None:
                for suffix in (" (Current)", " (Next)"):
                    n = nodes.get(f"Atlas Normal Texture{suffix}")
                    if n is not None:
                        n.image = normal_img
            if orm_img is not None:
                for suffix in (" (Current)", " (Next)"):
                    n = nodes.get(f"Atlas ORM Texture{suffix}")
                    if n is not None:
                        n.image = orm_img
            if aux_img is not None:
                for suffix in (" (Current)", " (Next)"):
                    n = nodes.get(f"Atlas Aux Texture{suffix}")
                    if n is not None:
                        n.image = aux_img

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
) -> tuple[Optional[Any], str]:
    """
    Check if a matching archetype exists, and if so, clone and return it.
    Returns (cloned_mat, template_key).
    """
    template_key = get_template_key(
        category=category,
        is_animated=is_animated,
        use_attribute_node=use_attribute_node,
        has_overlay=has_overlay,
        has_normal=bool(normal_path),
        has_orm=bool(orm_path),
        has_aux=bool(aux_path),
        render_engine=render_engine,
        disable_subsurface=disable_subsurface,
        target_uv_map=target_uv_map,
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
        )
        if cloned is not None:
            return cloned, template_key

    return None, template_key

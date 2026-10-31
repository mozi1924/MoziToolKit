"""
Dynamic Entities Material and Image Builder for player heads, custom skulls, and banners.
Uses a 1024x1024 RGBA dynamic atlas texture (slot capacity: 256 entity designs).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("MoziToolKit.Materials.DynamicEntities")

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from .image_utils import (
    ensure_material_node_tree,
    get_or_create_image_from_rgba,
)

DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID = 0xFFF0  # 65520
DEFAULT_DYNAMIC_SKINS_CHUNK_ID = DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID
DYNAMIC_CHUNK_START = 0xFFF0
DYNAMIC_CHUNK_END = 0xFFFF
DYNAMIC_ENTITIES_IMAGE_NAME = "MTK_Dynamic_Entities_Atlas"
DYNAMIC_ENTITIES_MATERIAL_NAME = "MTK:Atlas:entities:dynamic"

# Backwards compatibility constants
DYNAMIC_SKINS_IMAGE_NAME = DYNAMIC_ENTITIES_IMAGE_NAME
DYNAMIC_SKINS_MATERIAL_NAME = DYNAMIC_ENTITIES_MATERIAL_NAME


def dynamic_entities_image_name(chunk_id: int = DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID) -> str:
    """Returns canonical Blender image name for a dynamic entity atlas chunk."""
    if chunk_id == DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID:
        return DYNAMIC_ENTITIES_IMAGE_NAME
    return f"MTK_Dynamic_Entities_Atlas_{chunk_id:04X}"


def dynamic_entities_material_name(chunk_id: int = DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID) -> str:
    """Returns canonical Blender material name for a dynamic entity atlas chunk."""
    if chunk_id == DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID:
        return DYNAMIC_ENTITIES_MATERIAL_NAME
    return f"MTK:Atlas:entities:dynamic_{chunk_id:04X}"


# Aliases
dynamic_skins_image_name = dynamic_entities_image_name
dynamic_skins_material_name = dynamic_entities_material_name


def update_dynamic_entities_image(
    rgba_bytes_or_memview: Any,
    chunk_id: int = DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID,
    image_name: Optional[str] = None,
    width: int = 1024,
    height: int = 1024,
) -> Optional[Any]:
    """
    Creates or updates the Blender Image datablock with latest dynamic entities RGBA bytes.
    """
    if not HAS_BPY or rgba_bytes_or_memview is None:
        return None

    if image_name is None:
        image_name = dynamic_entities_image_name(chunk_id)

    if len(rgba_bytes_or_memview) < width * height * 4:
        logger.warning(
            "Dynamic entity atlas buffer length (%d) is smaller than expected (%d) for chunk 0x%04X",
            len(rgba_bytes_or_memview),
            width * height * 4,
            chunk_id,
        )
        return None

    return get_or_create_image_from_rgba(
        image_name=image_name,
        width=width,
        height=height,
        rgba_bytes_or_memview=rgba_bytes_or_memview,
        colorspace="sRGB",
        force_reload=True,
        flip_y=True,
        pack=True,
    )


update_dynamic_skins_image = update_dynamic_entities_image


def build_dynamic_entities_material(
    chunk_id: int = DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID,
    dynamic_entity_atlas_bytes: Optional[Any] = None,
    image_name: Optional[str] = None,
    mat_name: Optional[str] = None,
) -> Optional[Any]:
    """
    Builds or retrieves the standard Principled BSDF material for player heads,
    custom skulls, and banners, hooking up the dynamic entities 1024x1024 atlas texture.
    """
    if not HAS_BPY:
        return None

    if mat_name is None:
        mat_name = dynamic_entities_material_name(chunk_id)
    if image_name is None:
        image_name = dynamic_entities_image_name(chunk_id)

    img = None
    if dynamic_entity_atlas_bytes is not None:
        img = update_dynamic_entities_image(
            dynamic_entity_atlas_bytes,
            chunk_id=chunk_id,
            image_name=image_name,
        )
    else:
        img = bpy.data.images.get(image_name)

    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(name=mat_name)

    mat["mtk_atlas_chunk_id"] = chunk_id
    mat["mtk_pbr_layout"] = "mtk_dynamic_entities_v1"

    # Forward-compatible transparency handling (Blender 4.2+ / 5.x)
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

    tree = ensure_material_node_tree(mat)
    if tree is None:
        return mat

    nodes = tree.nodes
    tex_node = nodes.get("DynamicAtlasTex")
    if tex_node is None or len(nodes) < 3:
        nodes.clear()
        output = nodes.new("ShaderNodeOutputMaterial")
        output.name = "Material Output"
        output.location = (400, 0)

        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.name = "Principled BSDF"
        bsdf.location = (100, 0)
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.5
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 0.0

        tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.name = "DynamicAtlasTex"
        tex_node.location = (-200, 0)
        tex_node.interpolation = "Closest"

        tree.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
        if "Alpha" in bsdf.inputs and "Alpha" in tex_node.outputs:
            tree.links.new(tex_node.outputs["Alpha"], bsdf.inputs["Alpha"])

    if img is not None:
        tex_node.image = img

    return mat


build_dynamic_skins_material = build_dynamic_entities_material

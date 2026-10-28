"""
Dynamic Skins Material and Image Builder for player heads and custom skulls.
Uses a 1024x1024 RGBA dynamic atlas texture (slot capacity: 256 skins).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("MoziToolKit.Materials.DynamicSkins")

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

DEFAULT_DYNAMIC_SKINS_CHUNK_ID = 0xFFF0  # 65520
DYNAMIC_SKINS_IMAGE_NAME = "MTK_Dynamic_Skins_Atlas"
DYNAMIC_SKINS_MATERIAL_NAME = "MTK:Atlas:skins:dynamic"


def update_dynamic_skins_image(
    rgba_bytes_or_memview: Any,
    image_name: str = DYNAMIC_SKINS_IMAGE_NAME,
    width: int = 1024,
    height: int = 1024,
) -> Optional[Any]:
    """
    Creates or updates the Blender Image datablock with latest dynamic skins RGBA bytes.
    """
    if not HAS_BPY or rgba_bytes_or_memview is None:
        return None

    if len(rgba_bytes_or_memview) < width * height * 4:
        logger.warning(
            "Dynamic skin atlas buffer length (%d) is smaller than expected (%d)",
            len(rgba_bytes_or_memview),
            width * height * 4,
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


def build_dynamic_skins_material(
    dynamic_skin_atlas_bytes: Optional[Any] = None,
    image_name: str = DYNAMIC_SKINS_IMAGE_NAME,
    mat_name: str = DYNAMIC_SKINS_MATERIAL_NAME,
) -> Optional[Any]:
    """
    Builds or retrieves the standard Principled BSDF material for player heads
    and custom skulls, hooking up the dynamic skins 1024x1024 atlas texture.
    """
    if not HAS_BPY:
        return None

    img = None
    if dynamic_skin_atlas_bytes is not None:
        img = update_dynamic_skins_image(dynamic_skin_atlas_bytes, image_name=image_name)
    else:
        img = bpy.data.images.get(image_name)

    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(name=mat_name)

    mat["mtk_atlas_chunk_id"] = DEFAULT_DYNAMIC_SKINS_CHUNK_ID
    mat["mtk_pbr_layout"] = "mtk_dynamic_skins_v1"

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

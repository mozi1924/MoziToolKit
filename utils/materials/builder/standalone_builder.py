"""
Standalone Material Builder.
Constructs Principled BSDF / LabPBR 1.3 shader node trees for standalone block materials.
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

try:
    from ...node_groups.labpbr import ensure_labpbr_decoder
except (ImportError, ValueError):
    from utils.node_groups.labpbr import ensure_labpbr_decoder




def get_or_create_image(image_path: str | Path, colorspace: str = "sRGB") -> Optional[Any]:
    """Load or retrieve an image datablock from disk with proper colorspace."""
    if not HAS_BPY:
        return None

    path_str = str(Path(image_path).resolve())
    if not os.path.exists(path_str):
        return None

    # Check existing images
    file_name = os.path.basename(path_str)
    for img in bpy.data.images:
        if img.filepath == path_str or img.name == file_name:
            if hasattr(img, "colorspace_settings") and colorspace:
                try:
                    img.colorspace_settings.name = colorspace
                except Exception:
                    pass
            return img

    try:
        img = bpy.data.images.load(path_str, check_existing=True)
        if hasattr(img, "colorspace_settings") and colorspace:
            try:
                img.colorspace_settings.name = colorspace
            except Exception:
                pass
        return img
    except Exception:
        return None


def build_standalone_material(
    texture_key: str,
    albedo_path: str | Path,
    normal_path: Optional[str | Path] = None,
    specular_path: Optional[str | Path] = None,
    material_name: Optional[str] = None,
    is_animated: bool = False,
    stack_fingerprint: Optional[str] = None,
    use_labpbr: bool = True,
) -> Optional[Any]:
    """
    Builds or updates a standalone Minecraft material in Blender.
    
    Node Tree Structure:
        - UV Map (UVMap) -> Image Texture (Albedo) [sRGB] -> LabPBR Decoder (Albedo Color & Alpha)
        - UV Map -> Image Texture (Normal) [Non-Color] (if present) -> LabPBR Decoder (Normal Color & Height)
        - UV Map -> Image Texture (Specular) [Non-Color] (if present) -> LabPBR Decoder (Specular Color & Emission)
        - LabPBR Decoder -> Material Output Surface
    
    Args:
        texture_key: Canonical texture identifier, e.g. "minecraft:block/stone".
        albedo_path: Path to Albedo PNG image.
        normal_path: Optional path to Normal (_n) PNG image.
        specular_path: Optional path to Specular/LabPBR (_s) PNG image.
        material_name: Custom name for the material datablock. Defaults to MTK:<texture_key>.
        is_animated: Whether this texture is animated.
        stack_fingerprint: Optional cache fingerprint for provenance tracking.
        use_labpbr: Whether to insert the LabPBR 1.3 decoder node group.
        
    Returns:
        bpy.types.Material instance.
    """
    if not HAS_BPY:
        return None

    mat_name = material_name or f"MTK:{texture_key}"

    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(name=mat_name)

    # Set authoritative lightweight custom properties
    mat["mtk_material_mode"] = "STANDALONE"
    mat["mtk_source_texture_key"] = texture_key
    mat["mtk_is_animated"] = is_animated
    if stack_fingerprint:
        mat["mtk_stack_fingerprint"] = stack_fingerprint

    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # 1. Output Node
    output_node = nodes.new("ShaderNodeOutputMaterial")
    output_node.name = "Material Output"
    output_node.location = (600, 0)

    # 2. UV Map Node
    uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.name = "UV Map"
    uv_node.location = (-800, 0)
    uv_node.uv_map = "UVMap"


    # 3. LabPBR Decoder Group
    decoder_group = ensure_labpbr_decoder() if use_labpbr else None
    if decoder_group:
        decoder_node = nodes.new("ShaderNodeGroup")
        decoder_node.name = "LabPBR Decoder"
        decoder_node.node_tree = decoder_group
        decoder_node.location = (200, 0)
        # Link Decoder -> Output
        links.new(decoder_node.outputs["BSDF"], output_node.inputs["Surface"])
    else:
        # Fallback standard Principled BSDF
        bsdf_node = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf_node.location = (200, 0)
        links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])
        decoder_node = bsdf_node

    # 4. Albedo Texture Node
    albedo_img = get_or_create_image(albedo_path, colorspace="sRGB")
    if albedo_img:
        albedo_node = nodes.new("ShaderNodeTexImage")
        albedo_node.name = "Albedo Texture"
        albedo_node.image = albedo_img
        albedo_node.interpolation = "Closest"
        albedo_node.location = (-400, 200)
        links.new(uv_node.outputs["UV"], albedo_node.inputs["Vector"])

        if decoder_group:
            links.new(albedo_node.outputs["Color"], decoder_node.inputs["Albedo Color"])
            links.new(albedo_node.outputs["Alpha"], decoder_node.inputs["Albedo Alpha"])
        else:
            links.new(albedo_node.outputs["Color"], decoder_node.inputs["Base Color"])
            links.new(albedo_node.outputs["Alpha"], decoder_node.inputs["Alpha"])

    # 5. Normal Texture Node (Optional)
    if normal_path and os.path.exists(str(normal_path)):
        normal_img = get_or_create_image(normal_path, colorspace="Non-Color")
        if normal_img:
            normal_node = nodes.new("ShaderNodeTexImage")
            normal_node.name = "Normal Texture"
            normal_node.image = normal_img
            normal_node.interpolation = "Closest"
            normal_node.location = (-400, -100)
            links.new(uv_node.outputs["UV"], normal_node.inputs["Vector"])

            if decoder_group:
                links.new(normal_node.outputs["Color"], decoder_node.inputs["Normal (_n) Color"])
                links.new(normal_node.outputs["Alpha"], decoder_node.inputs["Normal (_n) Alpha (Height)"])

    # 6. Specular Texture Node (Optional)
    if specular_path and os.path.exists(str(specular_path)):
        spec_img = get_or_create_image(specular_path, colorspace="Non-Color")
        if spec_img:
            spec_node = nodes.new("ShaderNodeTexImage")
            spec_node.name = "Specular Texture"
            spec_node.image = spec_img
            spec_node.interpolation = "Closest"
            spec_node.location = (-400, -400)
            links.new(uv_node.outputs["UV"], spec_node.inputs["Vector"])

            if decoder_group:
                links.new(spec_node.outputs["Color"], decoder_node.inputs["Specular (_s) Color"])
                links.new(spec_node.outputs["Alpha"], decoder_node.inputs["Specular (_s) Alpha (Emission)"])

    # Material settings for transparency
    if hasattr(mat, "blend_method"):
        try:
            mat.blend_method = "CLIP"
        except Exception:
            pass
    if hasattr(mat, "shadow_method"):
        try:
            mat.shadow_method = "CLIP"
        except Exception:
            pass

    return mat


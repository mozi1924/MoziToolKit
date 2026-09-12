"""
Atlas Chunk Material Builder.
Constructs Principled BSDF / LabPBR 1.3 shader node trees for Atlas Chunk materials,
with Mesh Attribute and UV decoding node integration.
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
    from .standalone_builder import get_or_create_image
except (ImportError, ValueError):
    from utils.node_groups.labpbr import ensure_labpbr_decoder
    from utils.materials.builder.standalone_builder import get_or_create_image



def build_atlas_chunk_material(
    chunk_id: int,
    albedo_path: str | Path,
    normal_path: Optional[str | Path] = None,
    specular_path: Optional[str | Path] = None,
    material_name: Optional[str] = None,
    use_attribute_node: bool = True,
    use_labpbr: bool = True,
) -> Optional[Any]:
    """
    Builds or updates an Atlas Chunk Minecraft material in Blender.
    
    Node Tree Structure:
        - UV Map (UVMap) / Attribute Node -> Image Texture (Chunk Albedo) [sRGB] -> LabPBR Decoder
        - UV Map / Attribute Node -> Image Texture (Chunk Normal) [Non-Color] (if present) -> LabPBR Decoder
        - UV Map / Attribute Node -> Image Texture (Chunk Specular) [Non-Color] (if present) -> LabPBR Decoder
        - LabPBR Decoder -> Material Output Surface
    
    Args:
        chunk_id: Atlas chunk index (e.g. 0, 1, 2).
        albedo_path: Path to Chunk Albedo PNG image.
        normal_path: Optional path to Chunk Normal (_n) PNG image.
        specular_path: Optional path to Chunk Specular (_s) PNG image.
        material_name: Custom name for the material datablock. Defaults to MTK_Atlas_Chunk_<id>.
        use_attribute_node: If True, adds ShaderNodeAttribute for reading mesh attributes.
        use_labpbr: Whether to insert the LabPBR 1.3 decoder node group.
        
    Returns:
        bpy.types.Material instance.
    """
    if not HAS_BPY:
        return None

    mat_name = material_name or f"MTK_Atlas_Chunk_{chunk_id}"

    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(name=mat_name)

    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # 1. Output Node
    output_node = nodes.new("ShaderNodeOutputMaterial")
    output_node.name = "Material Output"
    output_node.location = (700, 0)

    # 2. UV Map Node
    uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.name = "UV Map"
    uv_node.location = (-900, 0)
    uv_node.uv_map = "UVMap"


    # 2b. Attribute Node for reading mesh attributes (e.g. mtk_uv_transform or mtk_atlas_chunk_id)
    if use_attribute_node:
        attr_node = nodes.new("ShaderNodeAttribute")
        attr_node.name = "MTK Mesh Attributes"
        attr_node.location = (-900, -250)
        attr_node.attribute_name = "mtk_atlas_chunk_id"
        attr_node.attribute_type = "GEOMETRY"

    # 3. LabPBR Decoder Group
    decoder_group = ensure_labpbr_decoder() if use_labpbr else None
    if decoder_group:
        decoder_node = nodes.new("ShaderNodeGroup")
        decoder_node.name = "LabPBR Decoder"
        decoder_node.node_tree = decoder_group
        decoder_node.location = (300, 0)
        # Link Decoder -> Output
        links.new(decoder_node.outputs["BSDF"], output_node.inputs["Surface"])
    else:
        # Fallback standard Principled BSDF
        bsdf_node = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf_node.location = (300, 0)
        links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])
        decoder_node = bsdf_node

    # 4. Chunk Albedo Texture Node
    albedo_img = get_or_create_image(albedo_path, colorspace="sRGB")
    if albedo_img:
        albedo_node = nodes.new("ShaderNodeTexImage")
        albedo_node.name = "Atlas Albedo Texture"
        albedo_node.image = albedo_img
        albedo_node.interpolation = "Closest"
        albedo_node.location = (-350, 200)
        links.new(uv_node.outputs["UV"], albedo_node.inputs["Vector"])

        if decoder_group:
            links.new(albedo_node.outputs["Color"], decoder_node.inputs["Albedo Color"])
            links.new(albedo_node.outputs["Alpha"], decoder_node.inputs["Albedo Alpha"])
        else:
            links.new(albedo_node.outputs["Color"], decoder_node.inputs["Base Color"])
            links.new(albedo_node.outputs["Alpha"], decoder_node.inputs["Alpha"])

    # 5. Chunk Normal Texture Node (Optional)
    if normal_path and os.path.exists(str(normal_path)):
        normal_img = get_or_create_image(normal_path, colorspace="Non-Color")
        if normal_img:
            normal_node = nodes.new("ShaderNodeTexImage")
            normal_node.name = "Atlas Normal Texture"
            normal_node.image = normal_img
            normal_node.interpolation = "Closest"
            normal_node.location = (-350, -100)
            links.new(uv_node.outputs["UV"], normal_node.inputs["Vector"])

            if decoder_group:
                links.new(normal_node.outputs["Color"], decoder_node.inputs["Normal (_n) Color"])
                links.new(normal_node.outputs["Alpha"], decoder_node.inputs["Normal (_n) Alpha (Height)"])

    # 6. Chunk Specular Texture Node (Optional)
    if specular_path and os.path.exists(str(specular_path)):
        spec_img = get_or_create_image(specular_path, colorspace="Non-Color")
        if spec_img:
            spec_node = nodes.new("ShaderNodeTexImage")
            spec_node.name = "Atlas Specular Texture"
            spec_node.image = spec_img
            spec_node.interpolation = "Closest"
            spec_node.location = (-350, -400)
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


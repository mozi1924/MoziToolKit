"""
Atlas Chunk Material Builder.
Constructs Principled BSDF / LabPBR 1.3 shader node trees for Atlas Chunk materials,
with Mesh Attribute and UV decoding node integration, overlay blending, and dynamic Biome Tinting.
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
    from ...node_groups.atlas_uv_tiling import ensure_atlas_uv_tiling
    from ...node_groups.biome import ensure_biome_tint, ensure_colormap_decoder
    from ..constants import (
        ATTR_UV_TILING_TRANSFORM,
        ATTR_UV_ROTATION,
        ATTR_BIOME_TINT_DATA,
        ATTR_BIOME_TINT_COLOR,
        ATTR_COLORMAP_UV,
    )
    from .standalone_builder import get_or_create_image
except (ImportError, ValueError):
    from utils.node_groups.labpbr import ensure_labpbr_decoder
    from utils.node_groups.atlas_uv_tiling import ensure_atlas_uv_tiling
    from utils.node_groups.biome import ensure_biome_tint, ensure_colormap_decoder
    try:
        from utils.materials.constants import (
            ATTR_UV_TILING_TRANSFORM,
            ATTR_UV_ROTATION,
            ATTR_BIOME_TINT_DATA,
            ATTR_BIOME_TINT_COLOR,
            ATTR_COLORMAP_UV,
        )
    except (ImportError, ValueError):
        ATTR_UV_TILING_TRANSFORM = "mtk_uv_tiling_transform"
        ATTR_UV_ROTATION = "mtk_uv_rotation"
        ATTR_BIOME_TINT_DATA = "mtk_biome_tint_data"
        ATTR_BIOME_TINT_COLOR = "mtk_biome_tint_color"
        ATTR_COLORMAP_UV = "mtk_colormap_uv"
    from utils.materials.builder.standalone_builder import get_or_create_image


def set_material_displacement_method(mat: Any, method: str = "BOTH") -> None:
    """Configure material displacement method for Cycles and EEVEE across Blender versions."""
    if not mat:
        return
    if hasattr(mat, "displacement_method"):
        try:
            mat.displacement_method = method
        except Exception:
            pass
    elif hasattr(mat, "cycles") and hasattr(mat.cycles, "displacement_method"):
        try:
            mat.cycles.displacement_method = method
        except Exception:
            pass


def build_atlas_chunk_material(
    chunk_id: int,
    albedo_path: str | Path,
    normal_path: Optional[str | Path] = None,
    specular_path: Optional[str | Path] = None,
    overlay_path: Optional[str | Path] = None,
    colormaps: Optional[Dict[str, str | Path]] = None,
    category: str = "blocks",
    category_chunk_index: int = 1,
    is_animated: bool = False,
    stack_fingerprint: Optional[str] = None,
    material_name: Optional[str] = None,
    use_attribute_node: bool = True,
    use_labpbr: bool = True,
    atlas_width: float = 4096.0,
    atlas_height: float = 4096.0,
    tile_width: float = 16.0,
    tile_height: float = 16.0,
) -> Optional[Any]:
    """
    Builds or updates an Atlas Chunk Minecraft material in Blender.

    Node Tree Structure:
        - UV Map (UVMap) + Mesh Attributes -> MC_Atlas_UV_Tiling -> Image Texture (Chunk Albedo) [sRGB]
        - UV Map + Mesh Attributes -> MC_Atlas_UV_Tiling -> Image Texture (Chunk Overlay) [sRGB] (if present)
        - Mesh Attributes (mtk_biome_tint_data, mtk_biome_tint_color, mtk_colormap_uv) + Colormaps -> MC_Biome_Tint
        - MC_Biome_Tint (Color & Alpha) -> LabPBR Decoder (Albedo Color & Alpha)
        - UV Map + Mesh Attributes -> MC_Atlas_UV_Tiling -> Image Texture (Chunk Normal) [Non-Color] (if present) -> LabPBR Decoder
        - UV Map + Mesh Attributes -> MC_Atlas_UV_Tiling -> Image Texture (Chunk Specular) [Non-Color] (if present) -> LabPBR Decoder
        - LabPBR Decoder -> Material Output (Surface & Displacement)

    Args:
        chunk_id: Atlas chunk index (e.g. 0, 1, 2).
        albedo_path: Path to Chunk Albedo PNG image.
        normal_path: Optional path to Chunk Normal (_n) PNG image.
        specular_path: Optional path to Chunk Specular (_s) PNG image.
        overlay_path: Optional path to Chunk Overlay (_overlay) PNG image.
        colormaps: Optional dict mapping 'grass', 'foliage', 'dry_foliage' to colormap image paths.
        category: Atlas category name (e.g. "blocks", "chests", "items").
        category_chunk_index: 1-based index within the category.
        is_animated: Whether this chunk is an animated strip chunk.
        stack_fingerprint: Optional cache fingerprint for provenance tracking.
        material_name: Custom name for the material datablock. Defaults to MTK:Atlas:<cat>:<idx:03>.
        use_attribute_node: If True, adds ShaderNodeAttribute for reading mesh attributes & tiling.
        use_labpbr: Whether to insert the LabPBR 1.3 decoder node group.
        atlas_width: Width of the atlas image in pixels.
        atlas_height: Height of the atlas image in pixels.
        tile_width: Width of a single sprite tile in pixels (typically 16.0).
        tile_height: Height of a single sprite tile in pixels (typically 16.0).

    Returns:
        bpy.types.Material instance.
    """
    if not HAS_BPY:
        return None

    if material_name:
        mat_name = material_name
    elif is_animated:
        mat_name = f"MTK:Atlas:{category}:anim:{category_chunk_index:03}"
    else:
        mat_name = f"MTK:Atlas:{category}:{category_chunk_index:03}"

    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(name=mat_name)

    # Set authoritative lightweight custom properties
    mat["mtk_material_mode"] = "ATLAS"
    mat["mtk_atlas_category"] = category
    mat["mtk_atlas_chunk_id"] = chunk_id
    mat["mtk_atlas_chunk_index"] = category_chunk_index
    mat["mtk_is_animated"] = is_animated
    mat["mtk_has_overlay"] = bool(overlay_path and os.path.exists(str(overlay_path)))
    if stack_fingerprint:
        mat["mtk_stack_fingerprint"] = stack_fingerprint

    mat.use_nodes = True
    mat.use_fake_user = False
    set_material_displacement_method(mat, "BOTH")

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # 1. Output Node
    output_node = nodes.new("ShaderNodeOutputMaterial")
    output_node.name = "Material Output"
    output_node.location = (850, 0)

    # 2. UV Map Node
    uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.name = "UV Map"
    uv_node.location = (-1450, 100)
    uv_node.uv_map = "UVMap"

    target_uv_output = uv_node.outputs["UV"]

    # 2b. Attribute Nodes & UV Tiling Group Integration
    if use_attribute_node:
        tiling_group = ensure_atlas_uv_tiling()
        if tiling_group:
            # Attribute for UV transform: [scale_u, scale_v, loc_u, loc_v]
            attr_transform = nodes.new("ShaderNodeAttribute")
            attr_transform.name = "MTK UV Transform"
            attr_transform.location = (-1450, -100)
            attr_transform.attribute_name = ATTR_UV_TILING_TRANSFORM
            attr_transform.attribute_type = "GEOMETRY"

            # Attribute for UV rotation: float angle in radians
            attr_rotation = nodes.new("ShaderNodeAttribute")
            attr_rotation.name = "MTK UV Rotation"
            attr_rotation.location = (-1450, -350)
            attr_rotation.attribute_name = ATTR_UV_ROTATION
            attr_rotation.attribute_type = "GEOMETRY"

            # Separate Transform Color (R=scale_u, G=scale_v, B=loc_u, A=loc_v)
            sep_tf = nodes.new("ShaderNodeSeparateColor")
            sep_tf.name = "Separate UV Transform"
            sep_tf.location = (-1200, -100)
            links.new(attr_transform.outputs["Color"], sep_tf.inputs["Color"])

            red_sock = sep_tf.outputs.get("Red") or sep_tf.outputs[0]
            green_sock = sep_tf.outputs.get("Green") or sep_tf.outputs[1]
            blue_sock = sep_tf.outputs.get("Blue") or sep_tf.outputs[2]

            # Scale CombineXYZ: (scale_u, scale_v, 1.0)
            scale_comb = nodes.new("ShaderNodeCombineXYZ")
            scale_comb.name = "Combine Scale"
            scale_comb.location = (-980, -50)
            scale_comb.inputs["Z"].default_value = 1.0
            links.new(red_sock, scale_comb.inputs["X"])
            links.new(green_sock, scale_comb.inputs["Y"])

            # Location CombineXYZ: (loc_u, loc_v, 0.0)
            loc_comb = nodes.new("ShaderNodeCombineXYZ")
            loc_comb.name = "Combine Location"
            loc_comb.location = (-980, -220)
            loc_comb.inputs["Z"].default_value = 0.0
            links.new(blue_sock, loc_comb.inputs["X"])
            links.new(attr_transform.outputs["Alpha"], loc_comb.inputs["Y"])

            # Rotation CombineXYZ: (0.0, 0.0, rotation)
            rot_comb = nodes.new("ShaderNodeCombineXYZ")
            rot_comb.name = "Combine Rotation"
            rot_comb.location = (-980, -390)
            rot_comb.inputs["X"].default_value = 0.0
            rot_comb.inputs["Y"].default_value = 0.0
            rot_factor = attr_rotation.outputs.get("Factor") or attr_rotation.outputs.get("Fac") or attr_rotation.outputs[2]
            links.new(rot_factor, rot_comb.inputs["Z"])

            # MC_Atlas_UV_Tiling Group Node
            tiling_node = nodes.new("ShaderNodeGroup")
            tiling_node.name = "Atlas UV Tiling"
            tiling_node.node_tree = tiling_group
            tiling_node.location = (-750, 0)
            tiling_node.inputs["Atlas Width"].default_value = float(atlas_width)
            tiling_node.inputs["Atlas Height"].default_value = float(atlas_height)
            tiling_node.inputs["Tile Width"].default_value = float(tile_width)
            tiling_node.inputs["Tile Height"].default_value = float(tile_height)

            links.new(uv_node.outputs["UV"], tiling_node.inputs["Vector"])
            links.new(scale_comb.outputs["Vector"], tiling_node.inputs["Scale"])
            links.new(loc_comb.outputs["Vector"], tiling_node.inputs["Location"])
            links.new(rot_comb.outputs["Vector"], tiling_node.inputs["Rotation"])

            target_uv_output = tiling_node.outputs["Atlas UV"]

    # 3. LabPBR Decoder Group
    decoder_group = ensure_labpbr_decoder() if use_labpbr else None
    if decoder_group:
        decoder_node = nodes.new("ShaderNodeGroup")
        decoder_node.name = "LabPBR Decoder"
        decoder_node.node_tree = decoder_group
        decoder_node.location = (500, 0)
        # Link Decoder -> Output
        links.new(decoder_node.outputs["BSDF"], output_node.inputs["Surface"])
        if "Displacement" in decoder_node.outputs and "Displacement" in output_node.inputs:
            links.new(decoder_node.outputs["Displacement"], output_node.inputs["Displacement"])
    else:
        # Fallback standard Principled BSDF
        bsdf_node = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf_node.location = (500, 0)
        links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])
        decoder_node = bsdf_node

    # 4. Chunk Albedo Texture Node
    albedo_img = get_or_create_image(albedo_path, colorspace="sRGB")
    albedo_node = None
    if albedo_img:
        albedo_node = nodes.new("ShaderNodeTexImage")
        albedo_node.name = "Atlas Albedo Texture"
        albedo_node.image = albedo_img
        albedo_node.interpolation = "Closest"
        albedo_node.extension = "CLIP"
        albedo_node.location = (-450, 200)
        links.new(target_uv_output, albedo_node.inputs["Vector"])

    # 4b. Chunk Overlay Texture Node (Optional)
    overlay_node = None
    if overlay_path and os.path.exists(str(overlay_path)):
        overlay_img = get_or_create_image(overlay_path, colorspace="sRGB")
        if overlay_img:
            overlay_node = nodes.new("ShaderNodeTexImage")
            overlay_node.name = "Atlas Overlay Texture"
            overlay_node.image = overlay_img
            overlay_node.interpolation = "Closest"
            overlay_node.extension = "CLIP"
            overlay_node.location = (-450, 480)
            links.new(target_uv_output, overlay_node.inputs["Vector"])

    # 4c. Biome Tinting & Colormap Decoding Integration
    biome_tint_group = ensure_biome_tint()
    tint_node = None
    if biome_tint_group and albedo_node:
        tint_node = nodes.new("ShaderNodeGroup")
        tint_node.name = "Biome Tint"
        tint_node.node_tree = biome_tint_group
        tint_node.location = (200, 250)

        # Base Color & Alpha
        links.new(albedo_node.outputs["Color"], tint_node.inputs["Base Color"])
        links.new(albedo_node.outputs["Alpha"], tint_node.inputs["Base Alpha"])

        # Overlay Color & Alpha
        if overlay_node:
            links.new(overlay_node.outputs["Color"], tint_node.inputs["Overlay Color"])
            links.new(overlay_node.outputs["Alpha"], tint_node.inputs["Overlay Alpha"])

        # Mesh Attribute: mtk_biome_tint_data (RGBA: Base Weight, Overlay Weight, Tint Weight, Tint Type)
        attr_tint_data = nodes.new("ShaderNodeAttribute")
        attr_tint_data.name = "Attr Biome Tint Data"
        attr_tint_data.attribute_name = ATTR_BIOME_TINT_DATA
        attr_tint_data.attribute_type = "GEOMETRY"
        attr_tint_data.location = (-450, 750)

        sep_tint_data = nodes.new("ShaderNodeSeparateColor")
        sep_tint_data.name = "Separate Biome Tint Data"
        sep_tint_data.location = (-200, 750)
        links.new(attr_tint_data.outputs["Color"], sep_tint_data.inputs["Color"])

        # Wire Tint Weights
        red_w = sep_tint_data.outputs.get("Red") or sep_tint_data.outputs[0]
        green_w = sep_tint_data.outputs.get("Green") or sep_tint_data.outputs[1]
        blue_w = sep_tint_data.outputs.get("Blue") or sep_tint_data.outputs[2]

        links.new(red_w, tint_node.inputs["Base Tint Weight"])
        links.new(green_w, tint_node.inputs["Overlay Tint Weight"])
        links.new(blue_w, tint_node.inputs["Tint Weight"])

        # Mesh Attribute: mtk_biome_tint_color (Fallback / Static / Hardcoded / Water Color)
        attr_tint_col = nodes.new("ShaderNodeAttribute")
        attr_tint_col.name = "Attr Biome Tint Color"
        attr_tint_col.attribute_name = ATTR_BIOME_TINT_COLOR
        attr_tint_col.attribute_type = "GEOMETRY"
        attr_tint_col.location = (-200, 50)

        # Colormap Dynamic Decoding Pipeline
        decoder_group_tree = ensure_colormap_decoder()
        active_colormaps = {}
        if colormaps and isinstance(colormaps, dict):
            for k in ("grass", "foliage", "dry_foliage"):
                if k in colormaps and os.path.exists(str(colormaps[k])):
                    active_colormaps[k] = colormaps[k]

        if decoder_group_tree and active_colormaps:
            # Mesh Attribute: mtk_colormap_uv
            attr_cm_uv = nodes.new("ShaderNodeAttribute")
            attr_cm_uv.name = "Attr Colormap UV"
            attr_cm_uv.attribute_name = ATTR_COLORMAP_UV
            attr_cm_uv.attribute_type = "GEOMETRY"
            attr_cm_uv.location = (-750, 1100)

            colormap_decoder = nodes.new("ShaderNodeGroup")
            colormap_decoder.name = "MC Biome Colormap Decoder"
            colormap_decoder.node_tree = decoder_group_tree
            colormap_decoder.location = (-100, 1050)

            # Tint Type from Biome Tint Data Alpha
            links.new(attr_tint_data.outputs["Alpha"], colormap_decoder.inputs["Tint Type"])
            links.new(attr_tint_col.outputs["Color"], colormap_decoder.inputs["Hardcoded Color"])
            links.new(attr_tint_col.outputs["Color"], colormap_decoder.inputs["Water Color"])
            links.new(attr_tint_col.outputs["Color"], colormap_decoder.inputs["Fallback Color"])

            cm_configs = [
                ("grass", "Colormap Grass", (-450, 1250), "Grass Color"),
                ("foliage", "Colormap Foliage", (-450, 1050), "Foliage Color"),
                ("dry_foliage", "Colormap Dry Foliage", (-450, 850), "Dry Foliage Color"),
            ]
            for key, node_name, pos, target_sock in cm_configs:
                cm_file = active_colormaps.get(key)
                if cm_file:
                    cm_img = get_or_create_image(cm_file, colorspace="sRGB")
                    if cm_img:
                        tex_cm = nodes.new("ShaderNodeTexImage")
                        tex_cm.name = node_name
                        tex_cm.image = cm_img
                        # Colormaps MUST use Linear interpolation and EXTEND clamping!
                        tex_cm.interpolation = "Linear"
                        tex_cm.extension = "EXTEND"
                        tex_cm.location = pos
                        links.new(attr_cm_uv.outputs["Vector"], tex_cm.inputs["Vector"])
                        links.new(tex_cm.outputs["Color"], colormap_decoder.inputs[target_sock])

            links.new(colormap_decoder.outputs["Color"], tint_node.inputs["Tint Color"])
        else:
            # Direct static color fallback
            links.new(attr_tint_col.outputs["Color"], tint_node.inputs["Tint Color"])

        # Link Biome Tint Output -> Decoder / BSDF
        if decoder_group:
            links.new(tint_node.outputs["Color"], decoder_node.inputs["Albedo Color"])
            links.new(tint_node.outputs["Alpha"], decoder_node.inputs["Albedo Alpha"])
        else:
            links.new(tint_node.outputs["Color"], decoder_node.inputs["Base Color"])
            links.new(tint_node.outputs["Alpha"], decoder_node.inputs["Alpha"])
    elif albedo_node:
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
            normal_node.extension = "CLIP"
            normal_node.location = (-450, -100)
            links.new(target_uv_output, normal_node.inputs["Vector"])

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
            spec_node.extension = "CLIP"
            spec_node.location = (-450, -350)
            links.new(target_uv_output, spec_node.inputs["Vector"])

            if decoder_group:
                links.new(spec_node.outputs["Color"], decoder_node.inputs["Specular (_s) Color"])
                links.new(spec_node.outputs["Alpha"], decoder_node.inputs["Specular (_s) Alpha (Emission)"])

    # Ensure Albedo image texture node is active and selected for Solid Viewport mode
    if albedo_node:
        for n in nodes:
            n.select = False
        nodes.active = albedo_node
        albedo_node.select = True

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


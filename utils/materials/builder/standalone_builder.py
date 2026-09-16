"""
Standalone Material Builder.
Constructs Principled BSDF / LabPBR 1.3 shader node trees for standalone block materials,
with structured Frame organization, neat node layout coordinates, overlay blending,
and dynamic Biome Tinting integration.
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
    from ...node_groups.biome import ensure_biome_tint, ensure_colormap_decoder
    from ..constants import (
        ATTR_BIOME_TINT_DATA,
        ATTR_BIOME_TINT_COLOR,
        ATTR_COLORMAP_UV,
    )
except (ImportError, ValueError):
    from utils.node_groups.labpbr import ensure_labpbr_decoder
    from utils.node_groups.biome import ensure_biome_tint, ensure_colormap_decoder
    try:
        from utils.materials.constants import (
            ATTR_BIOME_TINT_DATA,
            ATTR_BIOME_TINT_COLOR,
            ATTR_COLORMAP_UV,
        )
    except (ImportError, ValueError):
        ATTR_BIOME_TINT_DATA = "mtk_biome_tint_data"
        ATTR_BIOME_TINT_COLOR = "mtk_biome_tint_color"
        ATTR_COLORMAP_UV = "mtk_colormap_uv"


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


def _create_frame(
    nodes: Any,
    name: str,
    label: str,
    color: tuple[float, float, float] | None = None,
) -> Any:
    """Helper to create and style a layout frame node."""
    frame = nodes.new("NodeFrame")
    frame.name = name
    frame.label = label
    if color is not None and hasattr(frame, "use_custom_color"):
        frame.use_custom_color = True
        frame.color = color
    return frame


def build_standalone_material(
    texture_key: str,
    albedo_path: str | Path,
    normal_path: Optional[str | Path] = None,
    specular_path: Optional[str | Path] = None,
    overlay_path: Optional[str | Path] = None,
    colormaps: Optional[Dict[str, str | Path]] = None,
    material_name: Optional[str] = None,
    is_animated: bool = False,
    stack_fingerprint: Optional[str] = None,
    use_attribute_node: bool = True,
    use_labpbr: bool = True,
) -> Optional[Any]:
    """
    Builds or updates a standalone Minecraft material in Blender with structured Frames.
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
    mat["mtk_has_overlay"] = bool(overlay_path and os.path.exists(str(overlay_path)))
    if stack_fingerprint:
        mat["mtk_stack_fingerprint"] = stack_fingerprint

    mat.use_nodes = True
    mat.use_fake_user = False
    set_material_displacement_method(mat, "BOTH")

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # -------------------------------------------------------------------------
    # 0. Layout Frames (Logical Responsibility Subgraphs)
    # -------------------------------------------------------------------------
    frame_uv = _create_frame(nodes, "Frame_UV", "UV Coordinates", (0.15, 0.25, 0.40))
    frame_tex = _create_frame(nodes, "Frame_Textures", "Texture Maps Input", (0.15, 0.35, 0.25))
    frame_biome = _create_frame(nodes, "Frame_Biome", "Biome Tint & Colormap Decoding", (0.35, 0.25, 0.15))
    frame_shading = _create_frame(nodes, "Frame_Shading", "LabPBR 1.3 Material Shading", (0.30, 0.20, 0.35))
    frame_output = _create_frame(nodes, "Frame_Output", "Material Output", (0.20, 0.20, 0.20))

    # -------------------------------------------------------------------------
    # 1. Output Node (X: 1400)
    # -------------------------------------------------------------------------
    output_node = nodes.new("ShaderNodeOutputMaterial")
    output_node.name = "Material Output"
    output_node.location = (1400, 0)
    output_node.parent = frame_output

    # -------------------------------------------------------------------------
    # 2. UV Map Node (X: -1500)
    # -------------------------------------------------------------------------
    uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.name = "UV Map"
    uv_node.location = (-1500, 150)
    uv_node.uv_map = "UVMap"
    uv_node.parent = frame_uv

    # -------------------------------------------------------------------------
    # 3. Texture Maps Input (X: -1150)
    # -------------------------------------------------------------------------
    albedo_img = get_or_create_image(albedo_path, colorspace="sRGB")
    albedo_node = None
    if albedo_img:
        albedo_node = nodes.new("ShaderNodeTexImage")
        albedo_node.name = "Albedo Texture"
        albedo_node.image = albedo_img
        albedo_node.interpolation = "Closest"
        albedo_node.extension = "CLIP"
        albedo_node.location = (-1150, 300)
        albedo_node.parent = frame_tex
        links.new(uv_node.outputs["UV"], albedo_node.inputs["Vector"])

    overlay_node = None
    if overlay_path and os.path.exists(str(overlay_path)):
        overlay_img = get_or_create_image(overlay_path, colorspace="sRGB")
        if overlay_img:
            overlay_node = nodes.new("ShaderNodeTexImage")
            overlay_node.name = "Overlay Texture"
            overlay_node.image = overlay_img
            overlay_node.interpolation = "Closest"
            overlay_node.extension = "CLIP"
            overlay_node.location = (-1150, 580)
            overlay_node.parent = frame_tex
            links.new(uv_node.outputs["UV"], overlay_node.inputs["Vector"])

    normal_node = None
    if normal_path and os.path.exists(str(normal_path)):
        normal_img = get_or_create_image(normal_path, colorspace="Non-Color")
        if normal_img:
            normal_node = nodes.new("ShaderNodeTexImage")
            normal_node.name = "Normal Texture"
            normal_node.image = normal_img
            normal_node.interpolation = "Closest"
            normal_node.extension = "CLIP"
            normal_node.location = (-1150, 20)
            normal_node.parent = frame_tex
            links.new(uv_node.outputs["UV"], normal_node.inputs["Vector"])

    spec_node = None
    if specular_path and os.path.exists(str(specular_path)):
        spec_img = get_or_create_image(specular_path, colorspace="Non-Color")
        if spec_img:
            spec_node = nodes.new("ShaderNodeTexImage")
            spec_node.name = "Specular Texture"
            spec_node.image = spec_img
            spec_node.interpolation = "Closest"
            spec_node.extension = "CLIP"
            spec_node.location = (-1150, -260)
            spec_node.parent = frame_tex
            links.new(uv_node.outputs["UV"], spec_node.inputs["Vector"])

    # -------------------------------------------------------------------------
    # 4. Biome Tint & Colormap Decoding Integration (X: -700 to 200)
    # -------------------------------------------------------------------------
    biome_tint_group = ensure_biome_tint()
    tint_node = None
    if biome_tint_group and albedo_node:
        tint_node = nodes.new("ShaderNodeGroup")
        tint_node.name = "MC Biome Tint"
        tint_node.node_tree = biome_tint_group
        tint_node.location = (200, 350)
        tint_node.parent = frame_biome

        # Base Color & Alpha
        links.new(albedo_node.outputs["Color"], tint_node.inputs["Base Color"])
        links.new(albedo_node.outputs["Alpha"], tint_node.inputs["Base Alpha"])

        # Overlay Color & Alpha
        if overlay_node:
            links.new(overlay_node.outputs["Color"], tint_node.inputs["Overlay Color"])
            links.new(overlay_node.outputs["Alpha"], tint_node.inputs["Overlay Alpha"])

        if use_attribute_node:
            # Mesh Attribute: mtk_biome_tint_data (RGBA: Base Weight, Overlay Weight, Tint Weight, Tint Type)
            attr_tint_data = nodes.new("ShaderNodeAttribute")
            attr_tint_data.name = "Attr Biome Tint Data"
            attr_tint_data.attribute_name = ATTR_BIOME_TINT_DATA
            attr_tint_data.attribute_type = "GEOMETRY"
            attr_tint_data.location = (-700, 350)
            attr_tint_data.parent = frame_biome

            sep_tint_data = nodes.new("ShaderNodeSeparateColor")
            sep_tint_data.name = "Separate Biome Tint Data"
            sep_tint_data.location = (-450, 350)
            sep_tint_data.parent = frame_biome
            links.new(attr_tint_data.outputs["Color"], sep_tint_data.inputs["Color"])

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
            attr_tint_col.location = (-450, 100)
            attr_tint_col.parent = frame_biome

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
                attr_cm_uv.location = (-700, 800)
                attr_cm_uv.parent = frame_biome

                colormap_decoder = nodes.new("ShaderNodeGroup")
                colormap_decoder.name = "MC Biome Colormap Decoder"
                colormap_decoder.node_tree = decoder_group_tree
                colormap_decoder.location = (-100, 750)
                colormap_decoder.parent = frame_biome

                links.new(attr_tint_data.outputs["Alpha"], colormap_decoder.inputs["Tint Type"])
                links.new(attr_tint_col.outputs["Color"], colormap_decoder.inputs["Hardcoded Color"])
                links.new(attr_tint_col.outputs["Color"], colormap_decoder.inputs["Water Color"])
                links.new(attr_tint_col.outputs["Color"], colormap_decoder.inputs["Fallback Color"])

                cm_configs = [
                    ("grass", "Colormap Grass", (-450, 950), "Grass Color"),
                    ("foliage", "Colormap Foliage", (-450, 750), "Foliage Color"),
                    ("dry_foliage", "Colormap Dry Foliage", (-450, 550), "Dry Foliage Color"),
                ]
                for key, node_name, pos, target_sock in cm_configs:
                    cm_file = active_colormaps.get(key)
                    if cm_file:
                        cm_img = get_or_create_image(cm_file, colorspace="sRGB")
                        if cm_img:
                            tex_cm = nodes.new("ShaderNodeTexImage")
                            tex_cm.name = node_name
                            tex_cm.image = cm_img
                            tex_cm.interpolation = "Linear"
                            tex_cm.extension = "EXTEND"
                            tex_cm.location = pos
                            tex_cm.parent = frame_biome
                            links.new(attr_cm_uv.outputs["Vector"], tex_cm.inputs["Vector"])
                            links.new(tex_cm.outputs["Color"], colormap_decoder.inputs[target_sock])

                links.new(colormap_decoder.outputs["Color"], tint_node.inputs["Tint Color"])
            else:
                links.new(attr_tint_col.outputs["Color"], tint_node.inputs["Tint Color"])

    # -------------------------------------------------------------------------
    # 5. LabPBR 1.3 Material Shading (X: 650)
    # -------------------------------------------------------------------------
    decoder_group = ensure_labpbr_decoder() if use_labpbr else None
    if decoder_group:
        decoder_node = nodes.new("ShaderNodeGroup")
        decoder_node.name = "LabPBR Decoder"
        decoder_node.node_tree = decoder_group
        decoder_node.location = (650, 0)
        decoder_node.parent = frame_shading

        # Link Decoder -> Output
        links.new(decoder_node.outputs["BSDF"], output_node.inputs["Surface"])
        if "Displacement" in decoder_node.outputs and "Displacement" in output_node.inputs:
            links.new(decoder_node.outputs["Displacement"], output_node.inputs["Displacement"])
    else:
        bsdf_node = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf_node.location = (650, 0)
        bsdf_node.parent = frame_shading
        links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])
        decoder_node = bsdf_node

    # Link Albedo / Tint -> Decoder / BSDF
    if tint_node:
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

    # Link Normal -> Decoder
    if normal_node and decoder_group:
        links.new(normal_node.outputs["Color"], decoder_node.inputs["Normal (_n) Color"])
        links.new(normal_node.outputs["Alpha"], decoder_node.inputs["Normal (_n) Alpha (Height)"])

    # Link Specular -> Decoder
    if spec_node and decoder_group:
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

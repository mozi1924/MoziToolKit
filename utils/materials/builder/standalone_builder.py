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
    from ....bridge.material import get_material_props
    from .shading_config import resolve_material_shading_config
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
    from bridge.material import get_material_props
    try:
        from .shading_config import resolve_material_shading_config
    except (ImportError, ValueError):
        from utils.materials.builder.shading_config import resolve_material_shading_config


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


def ensure_material_node_tree(mat: Any) -> Any:
    """
    Ensure the material has an active node tree across Blender versions
    without accessing deprecated 'Material.use_nodes' in Blender 5.x/6.0+.
    """
    if mat is None:
        return None
    tree = getattr(mat, "node_tree", None)
    if tree is not None:
        return tree

    # Legacy Blender fallback (< 5.0) where node_tree is not initialized automatically
    try:
        import bpy
        if getattr(bpy.app, "version", (0, 0, 0)) < (5, 0, 0):
            mat.use_nodes = True
    except Exception:
        pass
    return getattr(mat, "node_tree", None)


def get_or_create_image_from_rgba(
    image_name: str,
    width: int,
    height: int,
    rgba_bytes_or_memview: Any,
    colorspace: str = "sRGB",
    force_reload: bool = False,
) -> Optional[Any]:
    """
    Creates or updates an image datablock directly in memory using NumPy.
    Zero disk IO and zero temporary files, tightly packed into Blender.
    """
    if not HAS_BPY:
        return None

    img = bpy.data.images.get(image_name)
    if not force_reload and img is not None and getattr(img, "has_data", False):
        if hasattr(img, "colorspace_settings") and colorspace:
            try:
                img.colorspace_settings.name = colorspace
            except Exception:
                pass
        return img

    try:
        import numpy as np
    except ImportError:
        np = None

    if np is None:
        return None

    try:
        if img is None:
            img = bpy.data.images.new(image_name, width=width, height=height, alpha=True)
        elif img.size[0] != width or img.size[1] != height:
            img.scale(width, height)

        raw_u8 = np.frombuffer(rgba_bytes_or_memview, dtype=np.uint8)
        flat_f32 = (raw_u8.astype(np.float32) * (1.0 / 255.0))
        img.pixels.foreach_set(flat_f32)
        img.update()
        if hasattr(img, "pack"):
            try:
                img.pack()
            except Exception:
                pass
        if hasattr(img, "colorspace_settings") and colorspace:
            try:
                img.colorspace_settings.name = colorspace
            except Exception:
                pass
        return img
    except Exception:
        return None


def get_or_create_image(
    image_path_or_source: Any,
    colorspace: str = "sRGB",
    force_reload: bool = False,
    chunk_id: Optional[str] = None,
) -> Optional[Any]:
    """
    Load or retrieve an image datablock from memory (.mtkcache) or disk.
    Prioritizes fast zero-disk memory streaming before falling back to filesystem.
    """
    if not HAS_BPY or image_path_or_source is None:
        return None

    # 1. Handle in-memory (width, height, buffer) tuple directly
    if isinstance(image_path_or_source, (tuple, list)) and len(image_path_or_source) == 3:
        w, h, buf = image_path_or_source
        img_name = chunk_id or "MTK_Memory_Image"
        return get_or_create_image_from_rgba(img_name, w, h, buf, colorspace=colorspace, force_reload=force_reload)

    # 2. Try resolving chunk_id from package if explicit or identifiable
    resolved_chunk_id = chunk_id
    path_str = str(image_path_or_source)
    if not resolved_chunk_id:
        if path_str.startswith(("atlas/textures/", "standalone/", "biome/colormap/")):
            resolved_chunk_id = path_str
        elif "_chunk_" in path_str and path_str.endswith(".png"):
            resolved_chunk_id = f"atlas/textures/{os.path.basename(path_str)}"
        elif "assets/" in path_str and path_str.endswith(".png"):
            idx = path_str.find("assets/")
            resolved_chunk_id = f"standalone/{path_str[idx:]}"

    if resolved_chunk_id:
        img_name = os.path.basename(resolved_chunk_id)
        existing_img = bpy.data.images.get(img_name)
        if not force_reload and existing_img is not None and getattr(existing_img, "has_data", False):
            if hasattr(existing_img, "colorspace_settings") and colorspace:
                try:
                    existing_img.colorspace_settings.name = colorspace
                except Exception:
                    pass
            return existing_img

        try:
            from ....bridge.assets import get_cached_texture_rgba
        except (ImportError, ValueError):
            try:
                from bridge.assets import get_cached_texture_rgba
            except Exception:
                get_cached_texture_rgba = None

        if get_cached_texture_rgba is not None:
            rgba_tuple = get_cached_texture_rgba(resolved_chunk_id)
            if rgba_tuple is not None:
                w, h, memview = rgba_tuple
                img = get_or_create_image_from_rgba(
                    img_name, w, h, memview, colorspace=colorspace, force_reload=force_reload
                )
                if img is not None:
                    return img

    # 3. Fallback: On-disk filesystem loading
    resolved_path = None
    try:
        p = Path(path_str).resolve()
        if p.exists() and p.is_file():
            resolved_path = str(p)
    except Exception:
        resolved_path = None

    if not resolved_path:
        return None

    file_name = os.path.basename(resolved_path)
    for img in bpy.data.images:
        if img.filepath == resolved_path or img.name == file_name:
            if force_reload and hasattr(img, "reload"):
                try:
                    img.reload()
                except Exception:
                    pass
            if hasattr(img, "colorspace_settings") and colorspace:
                try:
                    img.colorspace_settings.name = colorspace
                except Exception:
                    pass
            return img

    try:
        img = bpy.data.images.load(resolved_path, check_existing=True)
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
    uv_map_name: Optional[str] = None,
    block_name: Optional[str] = None,
    emission_override: Optional[float] = None,
    thin_wall_override: Optional[bool] = None,
    transmission_override: Optional[float] = None,
    sticker_threshold_override: Optional[float] = None,
    disable_subsurface: Optional[bool] = None,
    subsurface_scale: float = 0.1,
    render_engine: Optional[str] = None,
    enable_game_semantics: Optional[bool] = None,
    enable_transmission: Optional[bool] = None,
    enable_thin_wall: Optional[bool] = None,
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

    ensure_material_node_tree(mat)
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
    uv_node.uv_map = uv_map_name or "UVMap"
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
    if overlay_path:
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
    if normal_path:
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
    if specular_path:
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
                    v = colormaps.get(k)
                    if v and (os.path.exists(str(v)) or str(v).startswith("biome/")):
                        active_colormaps[k] = v
            else:
                for k in ("grass", "foliage", "dry_foliage"):
                    active_colormaps[k] = f"biome/colormap/{k}"

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
                        cm_img = get_or_create_image(cm_file, colorspace="sRGB", chunk_id=f"biome/colormap/{key}")
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

    # Configure PBR gating and catalog physical properties (Emission, Thin Wall, Transmission, Sticker Threshold, SSS)
    has_pbr = bool(normal_node or spec_node)
    clean_block = block_name or texture_key or mat_name

    raw_props = get_material_props(clean_block, texture_name=texture_key)
    cfg = resolve_material_shading_config(
        clean_block=clean_block,
        texture_key=texture_key,
        raw_props=raw_props,
        has_pbr=has_pbr,
        render_engine=render_engine,
        enable_game_semantics=enable_game_semantics,
        enable_transmission=enable_transmission,
        enable_thin_wall=enable_thin_wall,
        disable_subsurface=disable_subsurface,
        emission_override=emission_override,
        thin_wall_override=thin_wall_override,
        transmission_override=transmission_override,
        sticker_threshold_override=sticker_threshold_override,
    )

    emission_val = cfg["emission_strength"]
    is_thin = cfg["thin_wall"]
    trans_val = cfg["transmission_weight"]
    sticker_thresh = cfg["sticker_threshold"]
    final_disable_sss = cfg["disable_subsurface"]

    if decoder_group:
        if "Enable PBR (0-1)" in decoder_node.inputs:
            decoder_node.inputs["Enable PBR (0-1)"].default_value = 1.0 if has_pbr else 0.0
        if "Hardcoded Emission" in decoder_node.inputs:
            decoder_node.inputs["Hardcoded Emission"].default_value = float(emission_val)
        if "Thin Wall" in decoder_node.inputs:
            decoder_node.inputs["Thin Wall"].default_value = bool(is_thin)
        if "Transmission Weight" in decoder_node.inputs:
            decoder_node.inputs["Transmission Weight"].default_value = float(trans_val)
        if "Sticker Threshold" in decoder_node.inputs:
            decoder_node.inputs["Sticker Threshold"].default_value = float(sticker_thresh)
        if "Disable Subsurface" in decoder_node.inputs:
            decoder_node.inputs["Disable Subsurface"].default_value = bool(final_disable_sss)
        if "Subsurface Scale" in decoder_node.inputs:
            decoder_node.inputs["Subsurface Scale"].default_value = float(subsurface_scale)
    else:
        if "Transmission Weight" in decoder_node.inputs:
            decoder_node.inputs["Transmission Weight"].default_value = float(trans_val)
            if trans_val > 0.0 and "Roughness" in decoder_node.inputs:
                decoder_node.inputs["Roughness"].default_value = 0.0
        if "Emission Strength" in decoder_node.inputs and emission_val > 0.0:
            decoder_node.inputs["Emission Strength"].default_value = float(emission_val)
        if "Thin Wall" in decoder_node.inputs and is_thin:
            decoder_node.inputs["Thin Wall"].default_value = True
        if not final_disable_sss:
            if "Subsurface Weight" in decoder_node.inputs:
                decoder_node.inputs["Subsurface Weight"].default_value = 1.0
            if "Subsurface Scale" in decoder_node.inputs:
                decoder_node.inputs["Subsurface Scale"].default_value = float(subsurface_scale)

    # Ensure Albedo image texture node is active and selected for Solid Viewport mode
    if albedo_node:
        for n in nodes:
            n.select = False
        nodes.active = albedo_node
        albedo_node.select = True

    # Material settings for transparency and refraction (Blender 4.2+ EEVEE Next & legacy)
    is_transmissive = bool(trans_val > 0.0)
    if is_transmissive:
        if hasattr(mat, "surface_render_method"):
            try:
                mat.surface_render_method = "BLENDED"
            except Exception:
                pass
        elif hasattr(mat, "blend_method"):
            try:
                mat.blend_method = "HASHED"
            except Exception:
                pass
    else:
        if hasattr(mat, "surface_render_method"):
            try:
                mat.surface_render_method = "DITHERED"
            except Exception:
                pass
        elif hasattr(mat, "blend_method"):
            try:
                mat.blend_method = "CLIP"
            except Exception:
                pass

    if hasattr(mat, "use_transparency_overlap"):
        try:
            mat.use_transparency_overlap = True
        except Exception:
            pass
    if hasattr(mat, "use_raytrace_refraction"):
        try:
            mat.use_raytrace_refraction = cfg["use_raytrace_refraction"]
        except Exception:
            pass
    if hasattr(mat, "use_screen_refraction"):
        try:
            mat.use_screen_refraction = cfg["use_raytrace_refraction"]
        except Exception:
            pass

    return mat

"""
MoziToolKit Scene Interchange Material Builder.

Constructs canonical Principled BSDF materials using the compact Scene Mini-Atlas
embedded in .mtkscene packages. Adheres strictly to the Canonical PBR Pipeline
(Rule 5) and Blender 4.2+ / 5.x / 6.0 standards (Rule 6).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from ..materials.builder.image_utils import (
    ensure_material_node_tree,
    get_or_create_image_from_rgba,
)

logger = logging.getLogger("MoziToolKit.Scene.Materials")


def build_scene_chunk_material(
    scene_name: str,
    chunk_stem: str,
    albedo_img: Optional[Any] = None,
    normal_img: Optional[Any] = None,
    orm_img: Optional[Any] = None,
) -> Optional[Any]:
    """
    Builds a canonical Principled BSDF material referencing the Scene Mini-Atlas.
    Zero runtime LabPBR decoding trees; strictly standard BSDF with Closest interpolation.
    """
    if not HAS_BPY:
        return None

    mat_name = f"MTK_Scene_{scene_name}_{chunk_stem}"
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(mat_name)

    tree = ensure_material_node_tree(mat)
    if tree is None:
        return mat

    nodes = tree.nodes
    output = nodes.get("Material Output")
    bsdf = nodes.get("Principled BSDF")
    tex_node = nodes.get("MiniAtlasAlbedo")

    if output is None or bsdf is None or tex_node is None:
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
        tex_node.name = "MiniAtlasAlbedo"
        tex_node.location = (-250, 0)
        tex_node.interpolation = "Closest"

        tree.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
        if "Alpha" in bsdf.inputs and "Alpha" in tex_node.outputs:
            tree.links.new(tex_node.outputs["Alpha"], bsdf.inputs["Alpha"])

    if albedo_img is not None:
        tex_node.image = albedo_img

    # Hook Normal map if present
    if normal_img is not None:
        norm_node = nodes.get("MiniAtlasNormal")
        norm_map = nodes.get("Normal Map")
        if norm_node is None:
            norm_node = nodes.new("ShaderNodeTexImage")
            norm_node.name = "MiniAtlasNormal"
            norm_node.location = (-250, -250)
            norm_node.interpolation = "Closest"
        norm_node.image = normal_img

        if norm_map is None:
            norm_map = nodes.new("ShaderNodeNormalMap")
            norm_map.name = "Normal Map"
            norm_map.location = (-50, -250)
            tree.links.new(norm_node.outputs["Color"], norm_map.inputs["Color"])
            if "Normal" in bsdf.inputs:
                tree.links.new(norm_map.outputs["Normal"], bsdf.inputs["Normal"])

    return mat


def bind_scene_materials(
    mesh_obj: Any,
    reader: Any,
    scene_name: str = "Scene",
) -> List[Any]:
    """
    Reads mini-atlas texture chunks from the ScenePackageReader, creates in-memory
    Blender images, builds canonical PBR materials, and binds them to the mesh slots.
    """
    if not HAS_BPY or mesh_obj is None or reader is None:
        return []

    mesh = getattr(mesh_obj, "data", None)
    if mesh is None:
        return []

    texture_names = reader.get_atlas_texture_names()
    # Find unique base chunk stems (e.g. 'scene_chunk_001' from 'atlas/textures/scene_chunk_001.png')
    stems = set()
    for name in texture_names:
        clean = name.replace("atlas/textures/", "")
        if clean.endswith(".png"):
            clean = clean[:-4]
        # Strip suffixes like _n, _orm, _aux
        for suffix in ("_n", "_orm", "_aux"):
            if clean.endswith(suffix):
                clean = clean[: -len(suffix)]
                break
        stems.add(clean)

    sorted_stems = sorted(stems)
    materials = []

    for stem in sorted_stems:
        albedo_name = f"atlas/textures/{stem}.png"
        albedo_img = None
        try:
            w, h, pixels = reader.read_texture_rgba(albedo_name, flip_v=False)
            albedo_img = get_or_create_image_from_rgba(
                f"MTK_Scene_{scene_name}_{stem}",
                w,
                h,
                pixels,
                colorspace="sRGB",
                flip_y=True,
            )
        except Exception as e:
            logger.debug("Failed reading albedo texture %s: %s", albedo_name, e)

        normal_name = f"atlas/textures/{stem}_n.png"
        normal_img = None
        if normal_name in texture_names:
            try:
                w, h, pixels = reader.read_texture_rgba(normal_name, flip_v=False)
                normal_img = get_or_create_image_from_rgba(
                    f"MTK_Scene_{scene_name}_{stem}_Normal",
                    w,
                    h,
                    pixels,
                    colorspace="Non-Color",
                    flip_y=True,
                )
            except Exception as e:
                logger.debug("Failed reading normal texture %s: %s", normal_name, e)

        mat = build_scene_chunk_material(
            scene_name=scene_name,
            chunk_stem=stem,
            albedo_img=albedo_img,
            normal_img=normal_img,
        )
        if mat is not None:
            materials.append(mat)

    # Bind to mesh material slots
    if hasattr(mesh, "materials"):
        mesh.materials.clear()
        for mat in materials:
            mesh.materials.append(mat)

    return materials

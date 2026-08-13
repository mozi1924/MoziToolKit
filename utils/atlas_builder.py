"""
Atlas Material Builder for Blender.
Constructs a unified Atlas Shader Material using MC_Atlas_UV_Decoder and generated atlas textures.
"""

import json
from pathlib import Path
import bpy
from .node_groups.atlas_uv_decoder import build_atlas_uv_decoder_node_group
from .material_builder import load_image_texture


def build_atlas_material(
    atlas_dir: str | Path,
    mat_name: str = "MC_Atlas_Material",
    pack_textures: bool = True
) -> bpy.types.Material:
    """
    Construct or update a Blender Material that uses the generated Atlas textures and mapping.
    """
    atlas_path = Path(atlas_dir)
    mapping_file = atlas_path / "atlas_mapping.json"
    albedo_file = atlas_path / "atlas_albedo.png"
    normal_file = atlas_path / "atlas_normal.png"
    specular_file = atlas_path / "atlas_specular.png"

    if not mapping_file.exists() or not albedo_file.exists():
        raise FileNotFoundError(f"Atlas files missing in directory: {atlas_path}")

    with open(mapping_file, "r", encoding="utf-8") as fp:
        mapping_data = json.load(fp)

    atlas_w = float(mapping_data.get("atlas_width", 1728))
    atlas_h = float(mapping_data.get("atlas_height", 52352))
    tile_size = float(mapping_data.get("tile_size", 16))

    # Create or fetch material
    if mat_name in bpy.data.materials:
        mat = bpy.data.materials[mat_name]
    else:
        mat = bpy.data.materials.new(name=mat_name)

    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # 1. Output & Principled BSDF
    output_node = nodes.new("ShaderNodeOutputMaterial")
    output_node.location = (800, 0)

    bsdf_node = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf_node.location = (400, 0)
    links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])

    # 2. Texture Coordinate
    tex_coord = nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-800, 0)

    # 3. Atlas UV Decoder Node Group
    decoder_tree = build_atlas_uv_decoder_node_group()
    decoder_node = nodes.new("ShaderNodeGroup")
    decoder_node.node_tree = decoder_tree
    decoder_node.name = "MC Atlas UV Decoder"
    decoder_node.location = (-500, 0)

    # Set atlas dimensions
    decoder_node.inputs["Atlas Width"].default_value = atlas_w
    decoder_node.inputs["Atlas Height"].default_value = atlas_h
    decoder_node.inputs["Tile Size"].default_value = tile_size

    # Connect UV Vector
    links.new(tex_coord.outputs["UV"], decoder_node.inputs["Vector"])

    # 4. Albedo Image Texture Node
    alb_img = load_image_texture(albedo_file, colorspace="sRGB", pack_textures=pack_textures)
    tex_albedo = nodes.new("ShaderNodeTexImage")
    tex_albedo.name = "Atlas Albedo"
    tex_albedo.image = alb_img
    tex_albedo.interpolation = "Closest"
    tex_albedo.location = (-100, 200)

    links.new(decoder_node.outputs["Atlas UV"], tex_albedo.inputs["Vector"])
    links.new(tex_albedo.outputs["Color"], bsdf_node.inputs["Base Color"])
    links.new(tex_albedo.outputs["Alpha"], bsdf_node.inputs["Alpha"])

    # 5. Normal Map (if exists)
    if normal_file.exists():
        norm_img = load_image_texture(normal_file, colorspace="Non-Color", pack_textures=pack_textures)
        tex_normal = nodes.new("ShaderNodeTexImage")
        tex_normal.name = "Atlas Normal"
        tex_normal.image = norm_img
        tex_normal.interpolation = "Closest"
        tex_normal.location = (-100, -100)

        norm_map = nodes.new("ShaderNodeNormalMap")
        norm_map.location = (150, -100)

        links.new(decoder_node.outputs["Atlas UV"], tex_normal.inputs["Vector"])
        links.new(tex_normal.outputs["Color"], norm_map.inputs["Color"])
        links.new(norm_map.outputs["Normal"], bsdf_node.inputs["Normal"])

    # 6. Specular Map (if exists)
    if specular_file.exists():
        spec_img = load_image_texture(specular_file, colorspace="Non-Color", pack_textures=pack_textures)
        tex_specular = nodes.new("ShaderNodeTexImage")
        tex_specular.name = "Atlas Specular"
        tex_specular.image = spec_img
        tex_specular.interpolation = "Closest"
        tex_specular.location = (-100, -400)

        links.new(decoder_node.outputs["Atlas UV"], tex_specular.inputs["Vector"])
        if "Specular IOR Level" in bsdf_node.inputs:
            links.new(tex_specular.outputs["Color"], bsdf_node.inputs["Specular IOR Level"])

    return mat

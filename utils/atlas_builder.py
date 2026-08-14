"""
Atlas Material Builder for Blender.
Constructs a unified Atlas Shader Material using MC_Atlas_UV_Decoder and generated atlas textures.
Stores mapping JSON dictionary as a custom property on mat.node_tree["mtk:atlas_mapping"].
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
        raw_json_str = fp.read()
        mapping_data = json.loads(raw_json_str)

    atlas_w = float(mapping_data.get("atlas_width", 1728))
    atlas_h = float(mapping_data.get("atlas_height", 52352))
    tile_size = float(mapping_data.get("tile_size", 16))
    static_material_columns = float(mapping_data.get("static_material_columns", 1))

    # Create or fetch material
    if mat_name in bpy.data.materials:
        mat = bpy.data.materials[mat_name]
    else:
        mat = bpy.data.materials.new(name=mat_name)

    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Store mapping JSON as custom property on node tree
    mat.node_tree["mtk:atlas_mapping"] = raw_json_str

    # 1. Output & Principled BSDF
    output_node = nodes.new("ShaderNodeOutputMaterial")
    output_node.location = (800, 0)

    bsdf_node = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf_node.location = (400, 0)
    links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])

    # 2. Texture Coordinate & Attribute Node
    tex_coord = nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-900, 200)

    attr_node = nodes.new("ShaderNodeAttribute")
    attr_node.name = "Face Material ID Attribute"
    attr_node.attribute_name = "material_id"
    attr_node.location = (-900, -100)

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
    decoder_node.inputs["Static Material Columns"].default_value = static_material_columns

    # Connect UV Vector & Material ID Attribute
    links.new(tex_coord.outputs["UV"], decoder_node.inputs["Vector"])
    links.new(attr_node.outputs["Fac"], decoder_node.inputs["Material ID"])

    # 4. Albedo Image Texture Node
    alb_img = load_image_texture(albedo_file, colorspace="sRGB", pack_textures=pack_textures)
    tex_albedo = nodes.new("ShaderNodeTexImage")
    tex_albedo.name = "Atlas Albedo"
    tex_albedo.image = alb_img
    tex_albedo.interpolation = "Closest"
    tex_albedo.extension = "CLIP"
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
        tex_normal.extension = "CLIP"
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
        tex_specular.extension = "CLIP"
        tex_specular.location = (-100, -400)

        links.new(decoder_node.outputs["Atlas UV"], tex_specular.inputs["Vector"])
        if "Specular IOR Level" in bsdf_node.inputs:
            links.new(tex_specular.outputs["Color"], bsdf_node.inputs["Specular IOR Level"])

    return mat


def build_atlas_chunk_materials(
    atlas_dir: str | Path,
    material_prefix: str,
    pack_textures: bool = True,
    chunk_ids: set[int] | None = None,
) -> dict[int, bpy.types.Material]:
    """Build one UV-driven Blender material per atlas chunk.

    This is intentionally node-decoder-free: Material Preview and the solid
    texture display path sample the mesh UVs directly.  The decoder remains a
    separate future-facing path for procedural geometry.
    """
    atlas_path = Path(atlas_dir)
    with open(atlas_path / "atlas_mapping.json", "r", encoding="utf-8") as fp:
        raw_mapping = fp.read()
        mapping = json.loads(raw_mapping)

    materials = {}
    for chunk in mapping.get("chunks", []):
        chunk_id = int(chunk["chunk_id"])
        if chunk_ids is not None and chunk_id not in chunk_ids:
            continue
        albedo_name = chunk.get("files", {}).get("albedo")
        if not albedo_name:
            continue
        albedo_path = atlas_path / albedo_name
        if not albedo_path.exists():
            raise FileNotFoundError(f"Missing atlas chunk image: {albedo_path}")
        material_name = f"{material_prefix}:chunk:{chunk_id:03d}"
        mat = bpy.data.materials.get(material_name) or bpy.data.materials.new(material_name)
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()
        mat.node_tree["mtk:atlas_mapping"] = raw_mapping
        mat["mtk:atlas_chunk_id"] = chunk_id
        mat["mtk:atlas_chunk_kind"] = chunk["kind"]

        output = nodes.new("ShaderNodeOutputMaterial")
        output.location = (360, 0)
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (120, 0)
        coords = nodes.new("ShaderNodeTexCoord")
        coords.location = (-520, 0)
        texture = nodes.new("ShaderNodeTexImage")
        texture.name = f"Atlas Chunk {chunk_id:03d} Albedo"
        texture.image = load_image_texture(albedo_path, colorspace="sRGB", pack_textures=pack_textures)
        texture.interpolation = "Closest"
        texture.extension = "CLIP"
        texture.location = (-220, 0)
        links.new(coords.outputs["UV"], texture.inputs["Vector"])
        links.new(texture.outputs["Color"], bsdf.inputs["Base Color"])
        links.new(texture.outputs["Alpha"], bsdf.inputs["Alpha"])
        links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
        materials[chunk_id] = mat
    return materials

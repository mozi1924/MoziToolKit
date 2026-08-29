"""
Atlas Material Builder for Blender.
Constructs unified and chunk-based Atlas Shader Materials using LabPBR 1.3 and UV decoders.
"""

import json
from pathlib import Path
import bpy

from ...node_groups import ensure_all_templates
from ...node_groups.atlas_uv_decoder import build_atlas_uv_decoder_node_group
from ..nodes.builder import load_image_texture, set_material_displacement_method
from ..constants import (
    DEFAULT_NAMESPACE,
    PROP_PACK_HASH,
    PROP_PACK_HASH_SHORT,
    PROP_SOURCE_NAMESPACE,
    PROP_SOURCE_TEXTURE,
    PROP_MATERIAL_ID,
    PROP_ATLAS_CHUNK_ID,
    PROP_ATLAS_CHUNK_KIND,
    PROP_ATLAS_CHUNK_CATEGORY,
    PROP_ATLAS_MAPPING,
    PROP_ATLAS_WIDTH,
    PROP_ATLAS_HEIGHT,
    PROP_TILE_SIZE,
    PROP_TILES_PER_ROW,
    PROP_CREATED_BY,
    PROP_PROVENANCE_SCHEMA_VERSION,
    PROP_ENABLE_UV_TILING,
    PROVENANCE_SCHEMA_VERSION,
    ATTR_FACE_MATERIAL_ID,
    ATTR_ANIM_TIMING,
    ATTR_ANIM_FRAME_SIZE,
    ATTR_UV_TILING_TRANSFORM,
    ATTR_BIOME_TINT_DATA,
    ATTR_BIOME_TINT_COLOR,
)




def _new_atlas_uv_source(nodes, *, attribute_name: str | None, location: tuple[float, float]):
    """Create the UV source for one Atlas material variant.

    Normal meshes use Blender's active UV map.  Yefira is the exceptional
    procedural variant: its Geometry Nodes graph supplies an evaluated
    ``UVMap`` attribute instead.  Keeping that choice here prevents a Yefira
    fix from silently changing every normal Mozi atlas material.
    """
    if attribute_name:
        node = nodes.new("ShaderNodeAttribute")
        node.name = f"Atlas UV Attribute ({attribute_name})"
        node.attribute_type = "GEOMETRY"
        node.attribute_name = attribute_name
        node.location = location
        return node.outputs["Vector"]

    node = nodes.new("ShaderNodeTexCoord")
    node.name = "Atlas Texture Coordinate"
    node.location = location
    return node.outputs["UV"]


def build_atlas_material(
    atlas_dir: str | Path,
    mat_name: str = "MC_Atlas_Material",
    pack_textures: bool = True,
    uv_attribute: str | None = None,
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
    mat.use_fake_user = False
    set_material_displacement_method(mat, "BOTH")
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Store mapping JSON and dimensions as custom property on node tree and material
    mat.node_tree[PROP_ATLAS_MAPPING] = raw_json_str
    mat[PROP_ATLAS_MAPPING] = raw_json_str
    mat[PROP_ATLAS_WIDTH] = atlas_w
    mat[PROP_ATLAS_HEIGHT] = atlas_h
    mat[PROP_TILE_SIZE] = tile_size
    mat[PROP_TILES_PER_ROW] = max(1, int(atlas_w // tile_size))
    mat[PROP_CREATED_BY] = "MoziToolKit"
    mat[PROP_PROVENANCE_SCHEMA_VERSION] = PROVENANCE_SCHEMA_VERSION

    # 1. Output & Principled BSDF
    output_node = nodes.new("ShaderNodeOutputMaterial")
    output_node.location = (800, 0)

    bsdf_node = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf_node.location = (400, 0)
    links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])

    # 2. Default to the ordinary mesh UV layer.  An explicit caller opts a
    # procedural variant into a named geometry attribute.
    uv_socket = _new_atlas_uv_source(nodes, attribute_name=uv_attribute, location=(-900, 200))

    attr_node = nodes.new("ShaderNodeAttribute")
    attr_node.name = "Face Material ID Attribute"
    attr_node.attribute_name = ATTR_FACE_MATERIAL_ID
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
    links.new(uv_socket, decoder_node.inputs["Vector"])
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

    # 4b. Biome Tint & Overlay Integration
    overlay_file = atlas_path / "atlas_overlay.png"
    templates = ensure_all_templates()
    biome_tint_group = templates.get("MC_Biome_Tint")
    if biome_tint_group:
        biome_tint_node = nodes.new("ShaderNodeGroup")
        biome_tint_node.node_tree = biome_tint_group
        biome_tint_node.name = "MC Biome Tint"
        biome_tint_node.location = (150, 200)

        add_packed_biome_attribute_nodes(nodes, links, biome_tint_node)

        links.new(tex_albedo.outputs["Color"], biome_tint_node.inputs["Base Color"])
        links.new(tex_albedo.outputs["Alpha"], biome_tint_node.inputs["Base Alpha"])
        links.new(biome_tint_node.outputs["Color"], bsdf_node.inputs["Base Color"])
        links.new(biome_tint_node.outputs["Alpha"], bsdf_node.inputs["Alpha"])

        if overlay_file.exists():
            overlay_img = load_image_texture(overlay_file, colorspace="sRGB", pack_textures=pack_textures)
            if overlay_img:
                tex_overlay = nodes.new("ShaderNodeTexImage")
                tex_overlay.name = "Atlas Overlay"
                tex_overlay.image = overlay_img
                tex_overlay.interpolation = "Closest"
                tex_overlay.extension = "CLIP"
                tex_overlay.location = (-100, 450)
                links.new(decoder_node.outputs["Atlas UV"], tex_overlay.inputs["Vector"])
                links.new(tex_overlay.outputs["Color"], biome_tint_node.inputs["Overlay Color"])
                links.new(tex_overlay.outputs["Alpha"], biome_tint_node.inputs["Overlay Alpha"])
    else:
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

    # 7. Ensure Albedo texture node is active and selected for Solid Viewport mode
    for n in nodes:
        n.select = False
    nodes.active = tex_albedo
    tex_albedo.select = True

    return mat


def add_packed_biome_attribute_nodes(nodes, links, biome_tint_node, location=(-300, 200)):
    """Connect two RGBA face attributes to the biome group (six legacy streams)."""
    data = nodes.new("ShaderNodeAttribute")
    data.name = "Attr Biome Tint Data"
    data.attribute_type = "GEOMETRY"
    data.attribute_name = ATTR_BIOME_TINT_DATA
    data.location = (location[0], location[1] + 160)
    split = nodes.new("ShaderNodeSeparateColor")
    split.name = "Split Biome Tint Data"
    split.location = (location[0] + 180, location[1] + 160)
    links.new(data.outputs["Color"], split.inputs["Color"])
    links.new(split.outputs["Red"], biome_tint_node.inputs["Base Tint Weight"])
    links.new(split.outputs["Green"], biome_tint_node.inputs["Overlay Tint Weight"])
    links.new(split.outputs["Blue"], biome_tint_node.inputs["Tint Weight"])
    links.new(data.outputs["Alpha"], biome_tint_node.inputs["Use Hardcoded"])

    color = nodes.new("ShaderNodeAttribute")
    color.name = "Attr Biome Tint Color"
    color.attribute_type = "GEOMETRY"
    color.attribute_name = ATTR_BIOME_TINT_COLOR
    color.location = (location[0], location[1])
    # The writer resolves the active colour up front, therefore feeding it to
    # both sockets preserves the node group's legacy interface without a
    # second colour attribute.
    links.new(color.outputs["Color"], biome_tint_node.inputs["Tint Color"])
    links.new(color.outputs["Color"], biome_tint_node.inputs["Hardcoded Color"])


def build_atlas_chunk_materials(
    atlas_dir: str | Path,
    pack_hash: str | None = None,
    material_prefix: str | None = None,
    namespace: str = DEFAULT_NAMESPACE,
    pack_textures: bool = True,
    chunk_ids: set[int] | None = None,
    uv_attribute: str | None = None,
    enable_uv_tiling: bool = False,
) -> dict[int, bpy.types.Material]:
    """Build Atlas chunk materials for the normal or an explicit DCC variant.

    ``uv_attribute=None`` is the normal mesh contract.  ``"UVMap"`` is used
    only by Yefira's evaluated Geometry Nodes output.
    ``enable_uv_tiling=True`` is only used for static mesh material replacement
    from merged quad exporters (JMC2OBJ and Mineways). Yefira and Ice Cube
    do not require UV tiling nodes or attributes.
    """
    atlas_path = Path(atlas_dir)
    with open(atlas_path / "atlas_mapping.json", "r", encoding="utf-8") as fp:
        raw_mapping = fp.read()
        mapping = json.loads(raw_mapping)

    # Prepare compact mapping string
    compact_mapping = {
        "format_version": mapping.get("format_version", 10),
        "provenance_schema_version": mapping.get("provenance_schema_version", 1),
        "max_chunk_size": mapping.get("max_chunk_size"),
        "tile_size": mapping.get("tile_size"),
        "face_order": mapping.get("face_order", []),
        "chunks": mapping.get("chunks", []),
        "textures": mapping.get("textures", {}),
        "materials": mapping.get("materials", []),
        "animations": mapping.get("animations", []),
    }
    compact_mapping_str = json.dumps(compact_mapping, separators=(",", ":"))

    templates = ensure_all_templates()
    short_hash = pack_hash[:12] if pack_hash else ""

    materials = {}
    for chunk in mapping.get("chunks", []):
        chunk_id = int(chunk["chunk_id"])
        if chunk_ids is not None and chunk_id not in chunk_ids:
            continue

        chunk_files = chunk.get("files", {})
        albedo_name = chunk_files.get("albedo")
        if not albedo_name:
            continue

        albedo_path = atlas_path / albedo_name
        if not albedo_path.exists():
            raise FileNotFoundError(f"Missing atlas chunk image: {albedo_path}")
        chunk_cat = chunk.get("category", "blocks")
        if "category_chunk_index" in chunk:
            cat_chunk_idx = int(chunk["category_chunk_index"])
            chunk_texture_name = f"{chunk_cat}_chunk_{cat_chunk_idx:03d}"
        elif albedo_name.endswith("_albedo.png"):
            chunk_texture_name = albedo_name[:-11]
        else:
            chunk_texture_name = f"{chunk_cat}_chunk_{chunk_id:03d}"
        chunk_namespace = chunk.get("namespace", namespace or DEFAULT_NAMESPACE)

        # Determine material name & lookup existing material by durable metadata contract
        variant_suffix = ""
        if uv_attribute:
            variant_suffix += f":attr:{uv_attribute}"
        if enable_uv_tiling:
            variant_suffix += ":tiled"

        if material_prefix:
            material_name = f"{material_prefix}:{chunk_texture_name}{variant_suffix}"
        elif short_hash:
            material_name = f"mtk:{chunk_namespace}:{chunk_texture_name}:{short_hash}{variant_suffix}"
        else:
            material_name = f"mtk:{chunk_namespace}:{chunk_texture_name}{variant_suffix}"

        mat = None
        for existing in bpy.data.materials:
            if (
                existing.get(PROP_SOURCE_NAMESPACE) == chunk_namespace
                and existing.get(PROP_SOURCE_TEXTURE) == chunk_texture_name
                and existing.get("mtk:atlas_uv_source", "") == (uv_attribute or "")
                and bool(existing.get(PROP_ENABLE_UV_TILING, False)) == bool(enable_uv_tiling)
            ):
                if pack_hash and existing.get(PROP_PACK_HASH) == pack_hash:
                    mat = existing
                    break
                elif not pack_hash and existing.name == material_name:
                    mat = existing
                    break
            elif existing.name == material_name:
                mat = existing
                break

        if not mat:
            mat = bpy.data.materials.new(name=material_name)

        mat.use_nodes = True
        mat.use_fake_user = False
        set_material_displacement_method(mat, "BOTH")
        mat.node_tree[PROP_ATLAS_MAPPING] = compact_mapping_str
        mat[PROP_ATLAS_MAPPING] = compact_mapping_str
        mat[PROP_ATLAS_WIDTH] = float(chunk.get("width", 16))
        mat[PROP_ATLAS_HEIGHT] = float(chunk.get("height", 16))
        mat[PROP_TILE_SIZE] = float(chunk.get("tile_size", 16))
        mat[PROP_TILES_PER_ROW] = int(chunk.get("tiles_per_row", 1))

        mat[PROP_CREATED_BY] = "MoziToolKit"
        mat[PROP_PROVENANCE_SCHEMA_VERSION] = PROVENANCE_SCHEMA_VERSION
        mat[PROP_ENABLE_UV_TILING] = enable_uv_tiling
        mat[PROP_SOURCE_NAMESPACE] = chunk_namespace
        mat[PROP_SOURCE_TEXTURE] = chunk_texture_name
        mat[PROP_MATERIAL_ID] = f"{chunk_namespace}:{chunk_texture_name}"
        if pack_hash:
            mat[PROP_PACK_HASH] = pack_hash
            mat[PROP_PACK_HASH_SHORT] = short_hash
        mat[PROP_ATLAS_CHUNK_ID] = chunk_id
        mat[PROP_ATLAS_CHUNK_KIND] = chunk["kind"]
        mat[PROP_ATLAS_CHUNK_CATEGORY] = chunk.get("category", "blocks")
        if "category_chunk_index" in chunk:
            mat["mtk:atlas_category_chunk_index"] = int(chunk["category_chunk_index"])
        mat["mtk:atlas_uv_source"] = uv_attribute or ""

        albedo_tex_node = None
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()

        # 1. Output & LabPBR 1.3 Decoder
        output_node = nodes.new("ShaderNodeOutputMaterial")
        output_node.location = (600, 0)

        decoder_group = templates["LabPBR 1.3 Decoder"]
        decoder_node = nodes.new("ShaderNodeGroup")
        decoder_node.node_tree = decoder_group
        decoder_node.name = "LabPBR 1.3 Decoder"
        decoder_node.location = (300, 0)

        links.new(decoder_node.outputs["BSDF"], output_node.inputs["Surface"])
        if "Displacement" in decoder_node.outputs and "Displacement" in output_node.inputs:
            links.new(decoder_node.outputs["Displacement"], output_node.inputs["Displacement"])

        # Setup Biome Tint Node Group (only if chunk contains tinted/overlay textures)
        needs_biome_tint = chunk.get("has_tint", False) or chunk.get("has_overlay", False) or bool(chunk_files.get("overlay"))
        biome_tint_group = templates.get("MC_Biome_Tint") if needs_biome_tint else None
        biome_tint_node = None
        if biome_tint_group:
            biome_tint_node = nodes.new("ShaderNodeGroup")
            biome_tint_node.node_tree = biome_tint_group
            biome_tint_node.name = "MC Biome Tint"
            biome_tint_node.location = (50, 200)

            add_packed_biome_attribute_nodes(nodes, links, biome_tint_node)

            links.new(biome_tint_node.outputs["Color"], decoder_node.inputs["Albedo Color"])
            links.new(biome_tint_node.outputs["Alpha"], decoder_node.inputs["Albedo Alpha"])

        # 2. Ordinary meshes read their UV layer.  The Yefira call site opts
        # into its generated UVMap attribute explicitly.
        uv_socket = _new_atlas_uv_source(nodes, attribute_name=uv_attribute, location=(-1200, 0))

        # Build channels: Albedo, Normal, Specular
        channels_info = [
            ("albedo", "Albedo", "sRGB", "Albedo Color", "Albedo Alpha", 300),
            ("normal", "Normal", "Non-Color", "Normal (_n) Color", "Normal (_n) Alpha (Height)", 0),
            ("specular", "Specular", "Non-Color", "Specular (_s) Color", "Specular (_s) Alpha (Emission)", -300),
        ]

        is_animated = (chunk.get("kind") == "animation")

        if enable_uv_tiling:
            # Tiling attribute node (RGBA: scale XY, location XY)
            attr_tiling = nodes.new("ShaderNodeAttribute")
            attr_tiling.name = "Attr UV Tiling Transform"
            attr_tiling.attribute_type = "GEOMETRY"
            attr_tiling.attribute_name = ATTR_UV_TILING_TRANSFORM
            attr_tiling.location = (-1500, -600)

            split_tiling = nodes.new("ShaderNodeSeparateColor")
            split_tiling.name = "Split UV Tiling Transform"
            split_tiling.location = (-1330, -600)
            links.new(attr_tiling.outputs["Color"], split_tiling.inputs["Color"])

            # Safe Scale fallback: if Red / Green == 0 (e.g. default / missing attribute), default Scale to 1.0
            cmp_scale_x = nodes.new("ShaderNodeMath")
            cmp_scale_x.name = "Is Scale X Non-Zero"
            cmp_scale_x.operation = 'GREATER_THAN'
            cmp_scale_x.inputs[1].default_value = 0.0001
            cmp_scale_x.location = (-1160, -500)
            links.new(split_tiling.outputs["Red"], cmp_scale_x.inputs[0])

            mix_scale_x = nodes.new("ShaderNodeMix")
            mix_scale_x.name = "Safe Scale X"
            mix_scale_x.data_type = 'FLOAT'
            mix_scale_x.inputs[2].default_value = 1.0
            mix_scale_x.location = (-1000, -500)
            links.new(cmp_scale_x.outputs["Value"], mix_scale_x.inputs[0])
            links.new(split_tiling.outputs["Red"], mix_scale_x.inputs[3])

            cmp_scale_y = nodes.new("ShaderNodeMath")
            cmp_scale_y.name = "Is Scale Y Non-Zero"
            cmp_scale_y.operation = 'GREATER_THAN'
            cmp_scale_y.inputs[1].default_value = 0.0001
            cmp_scale_y.location = (-1160, -620)
            links.new(split_tiling.outputs["Green"], cmp_scale_y.inputs[0])

            mix_scale_y = nodes.new("ShaderNodeMix")
            mix_scale_y.name = "Safe Scale Y"
            mix_scale_y.data_type = 'FLOAT'
            mix_scale_y.inputs[2].default_value = 1.0
            mix_scale_y.location = (-1000, -620)
            links.new(cmp_scale_y.outputs["Value"], mix_scale_y.inputs[0])
            links.new(split_tiling.outputs["Green"], mix_scale_y.inputs[3])

            comb_scale = nodes.new("ShaderNodeCombineXYZ")
            comb_scale.name = "Combine UV Tiling Scale"
            comb_scale.inputs[2].default_value = 1.0
            comb_scale.location = (-840, -550)
            links.new(mix_scale_x.outputs[0], comb_scale.inputs[0])
            links.new(mix_scale_y.outputs[0], comb_scale.inputs[1])

            comb_loc = nodes.new("ShaderNodeCombineXYZ")
            comb_loc.name = "Combine UV Tiling Location"
            comb_loc.inputs[2].default_value = 0.0
            comb_loc.location = (-840, -700)
            links.new(split_tiling.outputs["Blue"], comb_loc.inputs[0])
            links.new(attr_tiling.outputs["Alpha"], comb_loc.inputs[1])

        if is_animated:
            # Two RGBA streams replace five scalar attributes.  This is
            # essential for EEVEE's per-material attribute budget.
            attr_timing = nodes.new("ShaderNodeAttribute")
            attr_timing.name = "Attr Animation Timing"
            attr_timing.attribute_type = "GEOMETRY"
            attr_timing.attribute_name = ATTR_ANIM_TIMING
            attr_timing.location = (-1500, 300)
            split_timing = nodes.new("ShaderNodeSeparateColor")
            split_timing.name = "Split Animation Timing"
            split_timing.location = (-1330, 300)
            links.new(attr_timing.outputs["Color"], split_timing.inputs["Color"])

            max_frames = nodes.new("ShaderNodeMath")
            max_frames.name = "Max Total Frames"
            max_frames.operation = "MAXIMUM"
            max_frames.inputs[1].default_value = 1.0
            max_frames.location = (-1300, 300)
            links.new(split_timing.outputs["Red"], max_frames.inputs[0])

            max_time = nodes.new("ShaderNodeMath")
            max_time.name = "Max Frametime"
            max_time.operation = "MAXIMUM"
            max_time.inputs[1].default_value = 1.0
            max_time.location = (-1300, 100)
            links.new(split_timing.outputs["Green"], max_time.inputs[0])

            attr_size = nodes.new("ShaderNodeAttribute")
            attr_size.name = "Attr Animation Frame Size"
            attr_size.attribute_type = "GEOMETRY"
            attr_size.attribute_name = ATTR_ANIM_FRAME_SIZE
            attr_size.location = (-1500, -300)
            split_size = nodes.new("ShaderNodeSeparateColor")
            split_size.name = "Split Animation Frame Size"
            split_size.location = (-1330, -300)
            links.new(attr_size.outputs["Color"], split_size.inputs["Color"])

            max_width = nodes.new("ShaderNodeMath")
            max_width.name = "Max Frame Width"
            max_width.operation = "MAXIMUM"
            max_width.inputs[1].default_value = float(chunk.get("tile_size", 16))
            max_width.location = (-1300, -300)
            links.new(split_size.outputs["Red"], max_width.inputs[0])

            max_height = nodes.new("ShaderNodeMath")
            max_height.name = "Max Frame Height"
            max_height.operation = "MAXIMUM"
            max_height.inputs[1].default_value = float(chunk.get("tile_size", 16))
            max_height.location = (-1300, -500)
            links.new(split_size.outputs["Green"], max_height.inputs[0])

            for channel_key, channel_name, colorspace, col_socket, alpha_socket, base_y in channels_info:
                fname = chunk_files.get(channel_key)
                if not fname:
                    continue
                fpath = atlas_path / fname
                if not fpath.exists():
                    continue

                img = load_image_texture(fpath, colorspace=colorspace, pack_textures=pack_textures, pack_hash=pack_hash)
                if not img:
                    continue

                # Scheduler
                scheduler = nodes.new("ShaderNodeGroup")
                scheduler.node_tree = templates["MC_Animation_Scheduler_Default"]
                scheduler.name = f"MC .mcmeta Scheduler ({channel_name})"
                scheduler.location = (-1050, base_y - 250)
                links.new(max_frames.outputs["Value"], scheduler.inputs["Total Frames"])
                links.new(max_time.outputs["Value"], scheduler.inputs["Frametime"])
                links.new(split_timing.outputs["Blue"], scheduler.inputs["Interpolate"])

                if enable_uv_tiling:
                    # Tiling on Frame 0 before animation stepping
                    tiling_frame0 = nodes.new("ShaderNodeGroup")
                    tiling_frame0.node_tree = templates["MC_Atlas_UV_Tiling"]
                    tiling_frame0.name = f"MC Atlas UV Tiling ({channel_name})"
                    tiling_frame0.location = (-1050, base_y)
                    tiling_frame0.inputs["Atlas Width"].default_value = float(chunk.get("width", 16))
                    tiling_frame0.inputs["Atlas Height"].default_value = float(chunk.get("height", 16))
                    links.new(max_width.outputs["Value"], tiling_frame0.inputs["Tile Width"])
                    links.new(max_height.outputs["Value"], tiling_frame0.inputs["Tile Height"])
                    links.new(uv_socket, tiling_frame0.inputs["Vector"])
                    links.new(comb_scale.outputs["Vector"], tiling_frame0.inputs["Scale"])
                    links.new(comb_loc.outputs["Vector"], tiling_frame0.inputs["Location"])
                    anim_uv_in_socket = tiling_frame0.outputs["Atlas UV"]
                else:
                    anim_uv_in_socket = uv_socket

                # UV Mapper
                uv_node = nodes.new("ShaderNodeGroup")
                uv_node.node_tree = templates["MC_Animated_UV_Mapping"]
                uv_node.name = f"MC UV Mapping ({channel_name})"
                uv_node.location = (-800, base_y)
                links.new(max_width.outputs["Value"], uv_node.inputs["Frame Width"])
                links.new(max_height.outputs["Value"], uv_node.inputs["Frame Height"])
                uv_node.inputs["Image Width"].default_value = float(chunk["width"])
                uv_node.inputs["Image Height"].default_value = float(chunk["height"])
                if "Atlas Mode" in uv_node.inputs:
                    uv_node.inputs["Atlas Mode"].default_value = 1.0

                links.new(anim_uv_in_socket, uv_node.inputs["Vector"])
                links.new(scheduler.outputs["Current Frame"], uv_node.inputs["Current Frame"])
                links.new(scheduler.outputs["Next Frame"], uv_node.inputs["Next Frame"])
                links.new(scheduler.outputs["Blend Factor"], uv_node.inputs["Blend Factor"])

                curr_uv_socket = uv_node.outputs["Current UV"]
                next_uv_socket = uv_node.outputs["Next UV"]


                # Tex Current & Next
                tex_curr = nodes.new("ShaderNodeTexImage")
                tex_curr.name = f"Tex Current ({channel_name})"
                tex_curr.image = img
                tex_curr.interpolation = "Closest"
                tex_curr.extension = "CLIP"
                tex_curr.location = (-320, base_y + 120)
                links.new(curr_uv_socket, tex_curr.inputs["Vector"])

                if channel_key == "albedo":
                    albedo_tex_node = tex_curr

                tex_next = nodes.new("ShaderNodeTexImage")
                tex_next.name = f"Tex Next ({channel_name})"
                tex_next.image = img
                tex_next.interpolation = "Closest"
                tex_next.extension = "CLIP"
                tex_next.location = (-320, base_y - 120)
                links.new(next_uv_socket, tex_next.inputs["Vector"])

                # Frame Blend
                blend_node = nodes.new("ShaderNodeGroup")
                blend_node.node_tree = templates["MC_Animated_Frame_Blend"]
                blend_node.name = f"Frame Blend ({channel_name})"
                blend_node.location = (-60, base_y)

                links.new(tex_curr.outputs["Color"], blend_node.inputs["Current Color"])
                links.new(tex_next.outputs["Color"], blend_node.inputs["Next Color"])
                links.new(tex_curr.outputs["Alpha"], blend_node.inputs["Current Alpha"])
                links.new(tex_next.outputs["Alpha"], blend_node.inputs["Next Alpha"])
                links.new(uv_node.outputs["Blend Factor"], blend_node.inputs["Blend Factor"])

                if channel_key == "albedo" and biome_tint_node:
                    links.new(blend_node.outputs["Color"], biome_tint_node.inputs["Base Color"])
                    links.new(blend_node.outputs["Alpha"], biome_tint_node.inputs["Base Alpha"])
                else:
                    links.new(blend_node.outputs["Color"], decoder_node.inputs[col_socket])
                    links.new(blend_node.outputs["Alpha"], decoder_node.inputs[alpha_socket])

        else:
            if enable_uv_tiling:
                # Static Branch (tiled UV mapping for merged quads)
                tiling_node = nodes.new("ShaderNodeGroup")
                tiling_node.node_tree = templates["MC_Atlas_UV_Tiling"]
                tiling_node.name = "MC Atlas UV Tiling"
                tiling_node.location = (-800, 0)
                tiling_node.inputs["Atlas Width"].default_value = float(chunk.get("width", 16))
                tiling_node.inputs["Atlas Height"].default_value = float(chunk.get("height", 16))
                tiling_node.inputs["Tile Width"].default_value = float(chunk.get("tile_size", 16))
                tiling_node.inputs["Tile Height"].default_value = float(chunk.get("tile_size", 16))
                links.new(uv_socket, tiling_node.inputs["Vector"])
                links.new(comb_scale.outputs["Vector"], tiling_node.inputs["Scale"])
                links.new(comb_loc.outputs["Vector"], tiling_node.inputs["Location"])
                uv_source_socket = tiling_node.outputs["Atlas UV"]
            else:
                uv_source_socket = uv_socket




            # Check if overlay texture exists for static chunk
            overlay_fname = chunk_files.get("overlay")
            if overlay_fname and biome_tint_node:
                overlay_fpath = atlas_path / overlay_fname
                if overlay_fpath.exists():
                    overlay_img = load_image_texture(overlay_fpath, colorspace="sRGB", pack_textures=pack_textures, pack_hash=pack_hash)
                    if overlay_img:
                        tex_overlay = nodes.new("ShaderNodeTexImage")
                        tex_overlay.name = f"Atlas Chunk {chunk_id:03d} Static (Overlay)"
                        tex_overlay.image = overlay_img
                        tex_overlay.interpolation = "Closest"
                        tex_overlay.extension = "CLIP"
                        tex_overlay.location = (-500, 500)
                        links.new(uv_source_socket, tex_overlay.inputs["Vector"])
                        links.new(tex_overlay.outputs["Color"], biome_tint_node.inputs["Overlay Color"])
                        links.new(tex_overlay.outputs["Alpha"], biome_tint_node.inputs["Overlay Alpha"])

            for channel_key, channel_name, colorspace, col_socket, alpha_socket, base_y in channels_info:
                fname = chunk_files.get(channel_key)
                if not fname:
                    continue
                fpath = atlas_path / fname
                if not fpath.exists():
                    continue

                img = load_image_texture(fpath, colorspace=colorspace, pack_textures=pack_textures, pack_hash=pack_hash)
                if not img:
                    continue

                tex_node = nodes.new("ShaderNodeTexImage")
                tex_node.name = f"Atlas Chunk {chunk_id:03d} Static ({channel_name})"
                tex_node.image = img
                tex_node.interpolation = "Closest"
                tex_node.extension = "CLIP"
                tex_node.location = (-500, base_y)

                if channel_key == "albedo":
                    albedo_tex_node = tex_node

                links.new(uv_source_socket, tex_node.inputs["Vector"])
                if channel_key == "albedo" and biome_tint_node:
                    links.new(tex_node.outputs["Color"], biome_tint_node.inputs["Base Color"])
                    links.new(tex_node.outputs["Alpha"], biome_tint_node.inputs["Base Alpha"])
                else:
                    links.new(tex_node.outputs["Color"], decoder_node.inputs[col_socket])
                    links.new(tex_node.outputs["Alpha"], decoder_node.inputs[alpha_socket])

        # Ensure Albedo image texture node is active and selected for Solid Viewport mode
        if albedo_tex_node:
            for n in nodes:
                n.select = False
            nodes.active = albedo_tex_node
            albedo_tex_node.select = True

        materials[chunk_id] = mat

    return materials

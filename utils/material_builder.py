import os
import shutil
from pathlib import Path
import bpy
from .node_groups import ensure_all_templates


def load_image_texture(
    filepath: Path,
    colorspace: str = 'sRGB',
    pack_textures: bool = True,
    pack_hash: str = None
) -> bpy.types.Image:
    """
    Load or reuse an image into Blender with Closest interpolation (pixel art).
    Names the image datablock as 'filename:pack_hash_short' to prevent collision
    (e.g., stone.png:dcddb12ac1c4) and reuses existing image datablocks when available.
    """
    if not filepath or not filepath.exists():
        return None

    str_path = str(filepath.resolve())
    short_hash = pack_hash[:12] if pack_hash else None
    expected_name = f"{filepath.name}:{short_hash}" if short_hash else filepath.name

    # 1. Check for existing matching image datablock in Blender
    img = None
    for existing in bpy.data.images:
        if expected_name and existing.name == expected_name:
            img = existing
            break
        if pack_hash and existing.get("mtk:pack_hash") == pack_hash and existing.get("mtk:source_file") == filepath.name:
            img = existing
            break
        if existing.filepath and str(Path(bpy.path.abspath(existing.filepath)).resolve()) == str_path:
            img = existing
            break

    # 2. Load from disk if not already present in bpy.data.images
    if not img:
        img = bpy.data.images.load(str_path, check_existing=False)
        if expected_name:
            img.name = expected_name
        if pack_hash:
            img["mtk:pack_hash"] = pack_hash
            img["mtk:pack_hash_short"] = short_hash
            img["mtk:source_file"] = filepath.name
    elif expected_name and img.name != expected_name:
        img.name = expected_name

    # Configure image properties for pixel art & color space
    if hasattr(img, "colorspace_settings"):
        try:
            img.colorspace_settings.name = colorspace
        except Exception:
            pass

    # Handle packing vs external storage
    if pack_textures:
        if not img.packed_file:
            try:
                img.pack()
            except Exception as e:
                print(f"[MoziToolKit] Failed to pack image {img.name}: {e}")
    else:
        # Save relative to blend file if blend file is saved
        if bpy.data.is_saved:
            blend_dir = Path(bpy.data.filepath).parent
            tex_target_dir = blend_dir / "textures" / "block"
            tex_target_dir.mkdir(parents=True, exist_ok=True)
            target_path = tex_target_dir / filepath.name
            if not target_path.exists():
                try:
                    shutil.copy2(filepath, target_path)
                except Exception as e:
                    print(f"[MoziToolKit] Error copying texture to relative directory: {e}")
            try:
                rel_path = "//" + os.path.relpath(target_path, blend_dir)
                img.filepath = rel_path
            except Exception:
                pass

    return img


def build_channel_nodes(
    mat: bpy.types.Material,
    channel_name: str,
    img_path: Path,
    mcmeta_data: dict,
    colorspace: str,
    pack_textures: bool,
    scheduler_node: bpy.types.Node,
    decoder_node: bpy.types.Node,
    tex_coord_node: bpy.types.Node,
    decoder_col_socket: str,
    decoder_alpha_socket: str,
    pack_hash: str = None,
    base_x: int = -800,
    base_y: int = 0
):
    """
    Dynamically build nodes for a single texture channel (Albedo, Normal, or Specular).
    Handles both animated (with .mcmeta) and static branches.
    """
    if not img_path or not img_path.exists():
        return

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    templates = ensure_all_templates()

    img = load_image_texture(img_path, colorspace=colorspace, pack_textures=pack_textures, pack_hash=pack_hash)
    if not img:
        return

    img_width = img.size[0] if img.size[0] > 0 else 16
    img_height = img.size[1] if img.size[1] > 0 else 16

    is_animated = False
    if mcmeta_data and isinstance(mcmeta_data, dict):
        frame_width = mcmeta_data.get("width") or img_width
        frame_height = mcmeta_data.get("height") or frame_width
        frametime = mcmeta_data.get("frametime", 1)
        interpolate = mcmeta_data.get("interpolate", False)
        frames = mcmeta_data.get("frames", [])
        total_frames = img_height // frame_height if frame_height > 0 else 1
        if total_frames > 1 or (isinstance(frames, list) and len(frames) > 1):
            is_animated = True

    if is_animated:
        # --- ANIMATED BRANCH ---

        # Each channel needs its own scheduler.  A single shared scheduler
        # caused the last processed .mcmeta to overwrite every channel's
        # frame count, timing and interpolation setting.
        scheduler_node = nodes.new("ShaderNodeGroup")
        scheduler_node.node_tree = templates["MC_Animation_Scheduler_Default"]
        scheduler_node.name = f"MC .mcmeta Scheduler ({channel_name})"
        scheduler_node.label = f"{channel_name}: {total_frames} frames, {frametime} ticks"
        scheduler_node.location = (base_x - 250, base_y - 250)
        scheduler_node.inputs["Total Frames"].default_value = max(1, total_frames)
        scheduler_node.inputs["Frametime"].default_value = max(1, frametime)
        scheduler_node.inputs["Interpolate"].default_value = bool(interpolate)


        # UV Mapping Node Group
        uv_map_group = templates["MC_Animated_UV_Mapping"]
        uv_node = nodes.new("ShaderNodeGroup")
        uv_node.node_tree = uv_map_group
        uv_node.name = f"MC UV Mapping ({channel_name})"
        uv_node.location = (base_x, base_y)

        uv_node.inputs["Frame Width"].default_value = float(frame_width)
        uv_node.inputs["Frame Height"].default_value = float(frame_height)
        uv_node.inputs["Image Width"].default_value = float(img_width)
        uv_node.inputs["Image Height"].default_value = float(img_height)
        if "Atlas Mode" in uv_node.inputs:
            uv_node.inputs["Atlas Mode"].default_value = 0.0

        if tex_coord_node and "UV" in tex_coord_node.outputs:
            links.new(tex_coord_node.outputs["UV"], uv_node.inputs["Vector"])

        if scheduler_node:
            if "Current Frame" in scheduler_node.outputs and "Current Frame" in uv_node.inputs:
                links.new(scheduler_node.outputs["Current Frame"], uv_node.inputs["Current Frame"])
            if "Next Frame" in scheduler_node.outputs and "Next Frame" in uv_node.inputs:
                links.new(scheduler_node.outputs["Next Frame"], uv_node.inputs["Next Frame"])
            # Keep the animation signal on the same path as the reference
            # material: scheduler -> UV mapper -> frame compositor.  The UV
            # group deliberately forwards Blend Factor unchanged, so every
            # animated channel has one coherent current/next-frame contract.
            if "Blend Factor" in scheduler_node.outputs and "Blend Factor" in uv_node.inputs:
                links.new(scheduler_node.outputs["Blend Factor"], uv_node.inputs["Blend Factor"])

        # Current Frame Image Node
        tex_curr = nodes.new("ShaderNodeTexImage")
        tex_curr.name = f"Tex Current ({channel_name})"
        tex_curr.image = img
        tex_curr.interpolation = 'Closest'
        tex_curr.location = (base_x + 250, base_y + 100)
        links.new(uv_node.outputs["Current UV"], tex_curr.inputs["Vector"])

        # Next Frame Image Node
        tex_next = nodes.new("ShaderNodeTexImage")
        tex_next.name = f"Tex Next ({channel_name})"
        tex_next.image = img
        tex_next.interpolation = 'Closest'
        tex_next.location = (base_x + 250, base_y - 150)
        links.new(uv_node.outputs["Next UV"], tex_next.inputs["Vector"])

        # Frame Blend Node Group
        blend_group = templates["MC_Animated_Frame_Blend"]
        blend_node = nodes.new("ShaderNodeGroup")
        blend_node.node_tree = blend_group
        blend_node.name = f"Frame Blend ({channel_name})"
        blend_node.location = (base_x + 500, base_y)

        links.new(tex_curr.outputs["Color"], blend_node.inputs["Current Color"])
        links.new(tex_next.outputs["Color"], blend_node.inputs["Next Color"])
        links.new(tex_curr.outputs["Alpha"], blend_node.inputs["Current Alpha"])
        links.new(tex_next.outputs["Alpha"], blend_node.inputs["Next Alpha"])

        if "Blend Factor" in uv_node.outputs:
            links.new(uv_node.outputs["Blend Factor"], blend_node.inputs["Blend Factor"])

        # Connect output to LabPBR Decoder
        if decoder_node:
            links.new(blend_node.outputs["Color"], decoder_node.inputs[decoder_col_socket])
            links.new(blend_node.outputs["Alpha"], decoder_node.inputs[decoder_alpha_socket])

    else:
        # --- STATIC BRANCH ---
        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.name = f"Tex Static ({channel_name})"
        tex_node.image = img
        tex_node.interpolation = 'Closest'
        tex_node.location = (base_x + 250, base_y)

        if tex_coord_node and "UV" in tex_coord_node.outputs:
            links.new(tex_coord_node.outputs["UV"], tex_node.inputs["Vector"])

        if decoder_node:
            links.new(tex_node.outputs["Color"], decoder_node.inputs[decoder_col_socket])
            links.new(tex_node.outputs["Alpha"], decoder_node.inputs[decoder_alpha_socket])


def rebuild_material(
    mat: bpy.types.Material,
    texture_info: dict,
    pack_textures: bool = True,
    pack_hash: str = None
) -> bool:
    """
    Completely clear an existing material's node tree and reconstruct a LabPBR 1.3 PBR material
    supporting mixed static/animated texture channels.
    """
    if not mat:
        return False

    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    if not pack_hash:
        pack_hash = mat.get("mtk:pack_hash") or texture_info.get("pack_hash")

    templates = ensure_all_templates()

    # Material Output Node
    output_node = nt.nodes.new("ShaderNodeOutputMaterial")
    output_node.location = (600, 0)

    # LabPBR 1.3 Decoder Node Group Instance
    decoder_group = templates["LabPBR 1.3 Decoder"]
    decoder_node = nt.nodes.new("ShaderNodeGroup")
    decoder_node.node_tree = decoder_group
    decoder_node.name = "LabPBR 1.3 Decoder"
    decoder_node.location = (300, 0)

    # Link Decoder to Output
    nt.links.new(decoder_node.outputs["BSDF"], output_node.inputs["Surface"])
    if "Displacement" in decoder_node.outputs and "Displacement" in output_node.inputs:
        nt.links.new(decoder_node.outputs["Displacement"], output_node.inputs["Displacement"])

    # Shared TexCoord Node
    tex_coord = nt.nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-1200, 0)

    # Schedulers are created per animated channel in build_channel_nodes.
    scheduler_node = None

    # Build Albedo Channel
    if texture_info.get("albedo"):
        build_channel_nodes(
            mat=mat,
            channel_name="Albedo",
            img_path=texture_info["albedo"],
            mcmeta_data=texture_info.get("albedo_mcmeta"),
            colorspace='sRGB',
            pack_textures=pack_textures,
            scheduler_node=scheduler_node,
            decoder_node=decoder_node,
            tex_coord_node=tex_coord,
            decoder_col_socket="Albedo Color",
            decoder_alpha_socket="Albedo Alpha",
            pack_hash=pack_hash,
            base_x=-800,
            base_y=300
        )

    # Build Normal Channel (_n)
    if texture_info.get("normal"):
        build_channel_nodes(
            mat=mat,
            channel_name="Normal",
            img_path=texture_info["normal"],
            mcmeta_data=texture_info.get("normal_mcmeta"),
            colorspace='Non-Color',
            pack_textures=pack_textures,
            scheduler_node=scheduler_node,
            decoder_node=decoder_node,
            tex_coord_node=tex_coord,
            decoder_col_socket="Normal (_n) Color",
            decoder_alpha_socket="Normal (_n) Alpha (Height)",
            pack_hash=pack_hash,
            base_x=-800,
            base_y=0
        )

    # Build Specular Channel (_s)
    if texture_info.get("specular"):
        build_channel_nodes(
            mat=mat,
            channel_name="Specular",
            img_path=texture_info["specular"],
            mcmeta_data=texture_info.get("specular_mcmeta"),
            colorspace='Non-Color',
            pack_textures=pack_textures,
            scheduler_node=scheduler_node,
            decoder_node=decoder_node,
            tex_coord_node=tex_coord,
            decoder_col_socket="Specular (_s) Color",
            decoder_alpha_socket="Specular (_s) Alpha (Emission)",
            pack_hash=pack_hash,
            base_x=-800,
            base_y=-300
        )

    return True


def inspect_material_nodes(mat: bpy.types.Material) -> dict:
    """
    Inspect the shader node tree of a material and report health status
    for LabPBR Decoder, animation subgraphs, drivers, and channel links.
    """
    if not mat or not mat.use_nodes or not mat.node_tree:
        return {"has_node_tree": False, "is_healthy": False, "issues": ["No node tree found"]}

    nt = mat.node_tree
    nodes = nt.nodes
    issues = []

    # 1. Output Node Check
    output_nodes = [n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial"]
    has_output = len(output_nodes) > 0
    if not has_output:
        issues.append("Missing Material Output node")

    # 2. LabPBR Decoder Check
    decoder_nodes = [
        n for n in nodes
        if n.bl_idname == "ShaderNodeGroup" and n.node_tree and "LabPBR" in n.node_tree.name
    ]
    has_decoder = len(decoder_nodes) > 0
    bsdf_linked = False
    displacement_linked = False

    if not has_decoder:
        issues.append("Missing LabPBR 1.3 Decoder node")
    else:
        decoder = decoder_nodes[0]
        if output_nodes:
            output = output_nodes[0]
            # Check BSDF link
            if "BSDF" in decoder.outputs and "Surface" in output.inputs:
                for link in nt.links:
                    if link.from_socket == decoder.outputs["BSDF"] and link.to_socket == output.inputs["Surface"]:
                        bsdf_linked = True
                        break
            if not bsdf_linked:
                issues.append("LabPBR BSDF output is not connected to Material Output Surface")

            # Check Displacement link
            if "Displacement" in decoder.outputs and "Displacement" in output.inputs:
                for link in nt.links:
                    if link.from_socket == decoder.outputs["Displacement"] and link.to_socket == output.inputs["Displacement"]:
                        displacement_linked = True
                        break

    # 3. Channels and Animation inspection
    schedulers = [n for n in nodes if n.bl_idname == "ShaderNodeGroup" and n.node_tree and "Scheduler" in n.node_tree.name]
    uv_mappers = [n for n in nodes if n.bl_idname == "ShaderNodeGroup" and n.node_tree and "UV_Mapping" in n.node_tree.name]
    frame_blends = [n for n in nodes if n.bl_idname == "ShaderNodeGroup" and n.node_tree and "Frame_Blend" in n.node_tree.name]
    image_nodes = [n for n in nodes if n.bl_idname == "ShaderNodeTexImage" and n.image]

    # Check animation chain linkage
    for uv_node in uv_mappers:
        has_vector_in = any(link.to_node == uv_node and link.to_socket.name == "Vector" for link in nt.links)
        if not has_vector_in:
            issues.append(f"Animation UV Mapping node '{uv_node.name}' has no incoming Vector connection")

    is_healthy = (len(issues) == 0) and has_output and has_decoder and bsdf_linked

    return {
        "has_node_tree": True,
        "has_output_node": has_output,
        "has_decoder_node": has_decoder,
        "bsdf_linked": bsdf_linked,
        "displacement_linked": displacement_linked,
        "image_count": len(image_nodes),
        "scheduler_count": len(schedulers),
        "uv_mapper_count": len(uv_mappers),
        "frame_blend_count": len(frame_blends),
        "is_healthy": is_healthy,
        "issues": issues,
    }


def repair_material_nodes(
    mat: bpy.types.Material,
    resource_pack=None,
    force_rebuild: bool = False
) -> bool:
    """
    Repair or reconstruct a material's shader node tree.
    - Updates template node groups (LabPBR 1.3 Decoder, Animation groups) in place to latest version.
    - Reconnects broken LabPBR decoder links to Material Output.
    - Reconnects broken animation chains and fixes timeline drivers.
    - Rebuilds completely from resource pack if force_rebuild=True.
    """
    if not mat:
        return False

    templates = ensure_all_templates()

    # If force_rebuild is requested and pack is provided
    if force_rebuild and resource_pack:
        from .material_matching import extract_material_texture_keys
        namespace, candidates = extract_material_texture_keys(mat)
        tex_info = None
        for cand in candidates:
            info = resource_pack.get_texture_info(cand, namespace)
            if info and info.get("albedo"):
                tex_info = info
                break
        if tex_info:
            return rebuild_material(mat, tex_info, pack_textures=True, pack_hash=resource_pack.pack_hash)

    # In-place repair
    mat.use_nodes = True
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links

    # 1. Ensure Output Node
    output_node = next((n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial"), None)
    if not output_node:
        output_node = nodes.new("ShaderNodeOutputMaterial")
        output_node.location = (600, 0)

    # 2. Ensure LabPBR 1.3 Decoder Node
    decoder_node = next(
        (n for n in nodes if n.bl_idname == "ShaderNodeGroup" and n.node_tree and "LabPBR" in n.node_tree.name),
        None
    )
    if not decoder_node:
        decoder_node = next((n for n in nodes if n.name == "LabPBR 1.3 Decoder"), None)

    if not decoder_node:
        decoder_node = nodes.new("ShaderNodeGroup")
        decoder_node.name = "LabPBR 1.3 Decoder"
        decoder_node.location = (300, 0)

    decoder_node.node_tree = templates["LabPBR 1.3 Decoder"]

    # Reconnect Decoder -> Output
    if "BSDF" in decoder_node.outputs and "Surface" in output_node.inputs:
        bsdf_linked = any(
            l.from_socket == decoder_node.outputs["BSDF"] and l.to_socket == output_node.inputs["Surface"]
            for l in links
        )
        if not bsdf_linked:
            links.new(decoder_node.outputs["BSDF"], output_node.inputs["Surface"])

    if "Displacement" in decoder_node.outputs and "Displacement" in output_node.inputs:
        disp_linked = any(
            l.from_socket == decoder_node.outputs["Displacement"] and l.to_socket == output_node.inputs["Displacement"]
            for l in links
        )
        if not disp_linked:
            links.new(decoder_node.outputs["Displacement"], output_node.inputs["Displacement"])

    # 3. Ensure Shared TexCoord Node
    tex_coord = next((n for n in nodes if n.bl_idname == "ShaderNodeTexCoord"), None)
    if not tex_coord:
        tex_coord = nodes.new("ShaderNodeTexCoord")
        tex_coord.location = (-1200, 0)

    # 4. Repair and Update Template Node Groups across all node group instances
    for n in nodes:
        if n.bl_idname != "ShaderNodeGroup" or not n.node_tree:
            continue
        tree_name = n.node_tree.name
        if "Scheduler" in tree_name:
            n.node_tree = templates["MC_Animation_Scheduler_Default"]
        elif "UV_Mapping" in tree_name:
            n.node_tree = templates["MC_Animated_UV_Mapping"]
        elif "Frame_Blend" in tree_name:
            n.node_tree = templates["MC_Animated_Frame_Blend"]
        elif "Atlas_UV_Decoder" in tree_name:
            n.node_tree = templates["MC_Atlas_UV_Decoder"]

    # 5. Reconnect TexCoord to UV Mapping & Static nodes if missing, and ensure Atlas Mode
    from .material_matching import detect_material_mode
    mat_mode = detect_material_mode(mat)
    is_atlas_mat = mat_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED")

    for n in nodes:
        if n.bl_idname == "ShaderNodeGroup" and n.node_tree == templates["MC_Animated_UV_Mapping"]:
            if "Atlas Mode" in n.inputs:
                n.inputs["Atlas Mode"].default_value = 1.0 if is_atlas_mat else 0.0
            if "Vector" in n.inputs and not n.inputs["Vector"].is_linked:
                links.new(tex_coord.outputs["UV"], n.inputs["Vector"])
        elif n.bl_idname == "ShaderNodeTexImage" and n.name.startswith("Tex Static"):
            if "Vector" in n.inputs and not n.inputs["Vector"].is_linked:
                links.new(tex_coord.outputs["UV"], n.inputs["Vector"])

    # 6. Reconnect Tex Current / Tex Next to Frame Blend if unlinked
    for blend_node in [n for n in nodes if n.bl_idname == "ShaderNodeGroup" and n.node_tree == templates["MC_Animated_Frame_Blend"]]:
        channel = ""
        if "(" in blend_node.name and ")" in blend_node.name:
            channel = blend_node.name.split("(", 1)[1].split(")", 1)[0]
        if channel:
            tex_curr = next((n for n in nodes if n.name == f"Tex Current ({channel})"), None)
            tex_next = next((n for n in nodes if n.name == f"Tex Next ({channel})"), None)
            uv_node = next((n for n in nodes if n.name == f"MC UV Mapping ({channel})"), None)

            if tex_curr and "Color" in tex_curr.outputs and "Current Color" in blend_node.inputs:
                if not blend_node.inputs["Current Color"].is_linked:
                    links.new(tex_curr.outputs["Color"], blend_node.inputs["Current Color"])
                if not blend_node.inputs["Current Alpha"].is_linked and "Alpha" in tex_curr.outputs:
                    links.new(tex_curr.outputs["Alpha"], blend_node.inputs["Current Alpha"])

            if tex_next and "Color" in tex_next.outputs and "Next Color" in blend_node.inputs:
                if not blend_node.inputs["Next Color"].is_linked:
                    links.new(tex_next.outputs["Color"], blend_node.inputs["Next Color"])
                if not blend_node.inputs["Next Alpha"].is_linked and "Alpha" in tex_next.outputs:
                    links.new(tex_next.outputs["Alpha"], blend_node.inputs["Next Alpha"])

            if uv_node and "Blend Factor" in uv_node.outputs and "Blend Factor" in blend_node.inputs:
                if not blend_node.inputs["Blend Factor"].is_linked:
                    links.new(uv_node.outputs["Blend Factor"], blend_node.inputs["Blend Factor"])

            # Connect Frame Blend to Decoder sockets
            col_socket = "Albedo Color" if channel == "Albedo" else f"{channel} (_n) Color" if channel == "Normal" else f"{channel} (_s) Color"
            alpha_socket = "Albedo Alpha" if channel == "Albedo" else "Normal (_n) Alpha (Height)" if channel == "Normal" else "Specular (_s) Alpha (Emission)"
            if col_socket in decoder_node.inputs and not decoder_node.inputs[col_socket].is_linked:
                links.new(blend_node.outputs["Color"], decoder_node.inputs[col_socket])
            if alpha_socket in decoder_node.inputs and not decoder_node.inputs[alpha_socket].is_linked:
                links.new(blend_node.outputs["Alpha"], decoder_node.inputs[alpha_socket])

    return True


import os
import shutil
from pathlib import Path
import bpy
from .node_group_templates import ensure_all_templates


def load_image_texture(filepath: Path, colorspace: str = 'sRGB', pack_textures: bool = True) -> bpy.types.Image:
    """
    Load an image into Blender with Closest interpolation (pixel art).
    Optionally pack it into the blend file or save it to relative textures/ directory.
    """
    if not filepath or not filepath.exists():
        return None

    str_path = str(filepath.resolve())
    img = bpy.data.images.load(str_path, check_existing=True)
    
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

    img = load_image_texture(img_path, colorspace=colorspace, pack_textures=pack_textures)
    if not img:
        return

    is_animated = bool(mcmeta_data)

    if is_animated:
        # --- ANIMATED BRANCH ---
        img_width = img.size[0] if img.size[0] > 0 else 16
        img_height = img.size[1] if img.size[1] > 0 else 16
        
        frame_width = mcmeta_data.get("width") or img_width
        frame_height = mcmeta_data.get("height") or frame_width
        frametime = mcmeta_data.get("frametime", 2)
        interpolate = mcmeta_data.get("interpolate", False)
        total_frames = img_height // frame_height if frame_height > 0 else 1

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

        if tex_coord_node and "UV" in tex_coord_node.outputs:
            links.new(tex_coord_node.outputs["UV"], uv_node.inputs["Vector"])

        if scheduler_node:
            if "Current Frame" in scheduler_node.outputs and "Current Frame" in uv_node.inputs:
                links.new(scheduler_node.outputs["Current Frame"], uv_node.inputs["Current Frame"])
            if "Next Frame" in scheduler_node.outputs and "Next Frame" in uv_node.inputs:
                links.new(scheduler_node.outputs["Next Frame"], uv_node.inputs["Next Frame"])

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

        if scheduler_node and "Blend Factor" in scheduler_node.outputs:
            links.new(scheduler_node.outputs["Blend Factor"], blend_node.inputs["Blend Factor"])

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
    pack_textures: bool = True
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
            base_x=-800,
            base_y=-300
        )

    return True

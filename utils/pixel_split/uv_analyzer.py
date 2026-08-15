from typing import Tuple, Optional
import bpy
from .types import TargetGrid, FacePixelInfo
from ..mesh.uv import get_face_uv_bounds, get_image_from_face
from ..materials.matching import detect_material_mode


def _find_albedo_image(mat: bpy.types.Material) -> Optional[bpy.types.Image]:
    """Search for the primary Albedo / Base Color Image datablock in a material node tree."""
    if not mat or not mat.use_nodes or not mat.node_tree:
        return None

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # 1. Prioritize nodes explicitly named Albedo
    for node in nodes:
        if node.type == "TEX_IMAGE" and node.image and "albedo" in node.name.lower():
            return node.image

    # 2. Check nodes linked into LabPBR Decoder "Albedo Color" or Principled BSDF "Base Color"
    for link in links:
        if link.to_socket and link.to_socket.name in ("Albedo Color", "Base Color", "Color"):
            if link.from_node and link.from_node.type == "TEX_IMAGE" and link.from_node.image:
                return link.from_node.image
            # If coming from Frame Blend group
            if link.from_node and link.from_node.type == "GROUP" and link.from_node.node_tree and "Blend" in link.from_node.node_tree.name:
                for b_link in links:
                    if b_link.to_node == link.from_node and b_link.from_node and b_link.from_node.type == "TEX_IMAGE" and b_link.from_node.image:
                        return b_link.from_node.image

    # 3. Check active TEX_IMAGE node
    if nodes.active and nodes.active.type == "TEX_IMAGE" and nodes.active.image:
        return nodes.active.image

    # 4. Fallback to any TEX_IMAGE node with an image
    for node in nodes:
        if node.type == "TEX_IMAGE" and node.image:
            return node.image

    return None


def get_face_effective_texture_info(
    face,
    obj,
    context,
    default_res: Tuple[int, int] = (64, 64),
    uv_layer=None
) -> FacePixelInfo:
    """Intelligently determine effective single-frame / tile texture resolution for a face.

    Handles:
    - Standalone animated materials (MC_Animated_UV_Mapping, Scheduler, vertical strip aspect ratio)
    - Unified Atlas materials (MC_Atlas_UV_Decoder, tile_size)
    - Atlas Chunk materials (baked atlas coordinates vs local UVs)
    - Standalone static and generic materials
    """
    mat = None
    if face.material_index < len(obj.material_slots):
        slot = obj.material_slots[face.material_index]
        mat = slot.material

    if not mat or not mat.use_nodes or not mat.node_tree:
        img = get_image_from_face(face, obj, context)
        if img and img.size[0] > 0 and img.size[1] > 0:
            raw_w, raw_h = int(img.size[0]), int(img.size[1])
            # Check for vertical strip ratio heuristic even on plain image materials
            if raw_h > raw_w and raw_h % raw_w == 0:
                tf = raw_h // raw_w
                return FacePixelInfo(
                    effective_resolution=(raw_w, raw_w),
                    raw_image_resolution=(raw_w, raw_h),
                    material_mode="GENERIC",
                    is_animated=True,
                    total_frames=tf,
                    frame_width=raw_w,
                    frame_height=raw_w,
                    uv_mode="LOCAL",
                )
            return FacePixelInfo(
                effective_resolution=(raw_w, raw_h),
                raw_image_resolution=(raw_w, raw_h),
                material_mode="GENERIC",
            )
        return FacePixelInfo(
            effective_resolution=default_res,
            raw_image_resolution=default_res,
            material_mode="GENERIC",
        )

    mode = detect_material_mode(mat)

    # --- 1. UNIFIED ATLAS MODE ---
    if mode == "ATLAS_UNIFIED":
        decoder_node = next(
            (n for n in mat.node_tree.nodes if n.type == "GROUP" and n.node_tree and "Atlas_UV_Decoder" in n.node_tree.name or n.name == "MC Atlas UV Decoder"),
            None
        )
        tile_size = 16
        atlas_w = 1728
        atlas_h = 52352
        if decoder_node:
            if "Tile Size" in decoder_node.inputs:
                tile_size = int(round(decoder_node.inputs["Tile Size"].default_value))
            if "Atlas Width" in decoder_node.inputs:
                atlas_w = int(round(decoder_node.inputs["Atlas Width"].default_value))
            if "Atlas Height" in decoder_node.inputs:
                atlas_h = int(round(decoder_node.inputs["Atlas Height"].default_value))

        tile_size = max(1, tile_size)
        return FacePixelInfo(
            effective_resolution=(tile_size, tile_size),
            raw_image_resolution=(atlas_w, atlas_h),
            material_mode="ATLAS_UNIFIED",
            frame_width=tile_size,
            frame_height=tile_size,
            uv_mode="LOCAL",
        )

    # --- 2. ATLAS CHUNK MODE ---
    if mode == "ATLAS_CHUNK":
        img = _find_albedo_image(mat)
        raw_w = int(img.size[0]) if img and img.size[0] > 0 else 1024
        raw_h = int(img.size[1]) if img and img.size[1] > 0 else 1024

        # Check if UVs are baked into atlas coordinates
        is_baked_uv = True
        if uv_layer and face.loops:
            bounds = get_face_uv_bounds(face, uv_layer)
            # A face with UV width and height >= 0.8 is likely local [0, 1] UVs
            if bounds.width >= 0.8 and bounds.height >= 0.8:
                is_baked_uv = False

        # Also check MC_Animated_UV_Mapping node if present
        uv_node = next(
            (n for n in mat.node_tree.nodes if n.type == "GROUP" and n.node_tree and "UV_Mapping" in n.node_tree.name),
            None
        )
        if uv_node and "Atlas Mode" in uv_node.inputs:
            if float(uv_node.inputs["Atlas Mode"].default_value) == 0.0:
                is_baked_uv = False

        if is_baked_uv:
            return FacePixelInfo(
                effective_resolution=(raw_w, raw_h),
                raw_image_resolution=(raw_w, raw_h),
                material_mode="ATLAS_CHUNK",
                uv_mode="ATLAS_BAKED",
            )
        else:
            tile_size = 16
            if uv_node and "Frame Width" in uv_node.inputs:
                tile_size = int(round(uv_node.inputs["Frame Width"].default_value))
            return FacePixelInfo(
                effective_resolution=(tile_size, tile_size),
                raw_image_resolution=(raw_w, raw_h),
                material_mode="ATLAS_CHUNK",
                frame_width=tile_size,
                frame_height=tile_size,
                uv_mode="LOCAL",
            )

    # --- 3. STANDALONE & GENERIC MODES ---
    img = _find_albedo_image(mat) or get_image_from_face(face, obj, context)
    if not img or img.size[0] <= 0 or img.size[1] <= 0:
        return FacePixelInfo(
            effective_resolution=default_res,
            raw_image_resolution=default_res,
            material_mode=mode,
        )

    raw_w, raw_h = int(img.size[0]), int(img.size[1])

    # Check for MC_Animated_UV_Mapping node group
    uv_node = next(
        (n for n in mat.node_tree.nodes if n.type == "GROUP" and n.node_tree and "UV_Mapping" in n.node_tree.name),
        None
    )
    if uv_node:
        fw = int(round(uv_node.inputs["Frame Width"].default_value)) if "Frame Width" in uv_node.inputs else raw_w
        fh = int(round(uv_node.inputs["Frame Height"].default_value)) if "Frame Height" in uv_node.inputs else fw
        fw = max(1, fw)
        fh = max(1, fh)
        tf = raw_h // fh if fh > 0 else 1
        return FacePixelInfo(
            effective_resolution=(fw, fh),
            raw_image_resolution=(raw_w, raw_h),
            material_mode=mode,
            is_animated=True,
            total_frames=max(1, tf),
            frame_width=fw,
            frame_height=fh,
            uv_mode="LOCAL",
        )

    # Check for MC .mcmeta Scheduler node group
    sched_node = next(
        (n for n in mat.node_tree.nodes if n.type == "GROUP" and n.node_tree and "Scheduler" in n.node_tree.name),
        None
    )
    if sched_node and "Total Frames" in sched_node.inputs:
        tf = int(round(sched_node.inputs["Total Frames"].default_value))
        if tf > 1:
            fh = max(1, raw_h // tf)
            fw = raw_w
            return FacePixelInfo(
                effective_resolution=(fw, fh),
                raw_image_resolution=(raw_w, raw_h),
                material_mode=mode,
                is_animated=True,
                total_frames=tf,
                frame_width=fw,
                frame_height=fh,
                uv_mode="LOCAL",
            )

    # Check vertical animation strip ratio heuristic (e.g. 16x512 -> 32 frames of 16x16)
    if raw_h > raw_w and raw_h % raw_w == 0:
        tf = raw_h // raw_w
        return FacePixelInfo(
            effective_resolution=(raw_w, raw_w),
            raw_image_resolution=(raw_w, raw_h),
            material_mode=mode,
            is_animated=True,
            total_frames=tf,
            frame_width=raw_w,
            frame_height=raw_w,
            uv_mode="LOCAL",
        )

    # Static texture
    return FacePixelInfo(
        effective_resolution=(raw_w, raw_h),
        raw_image_resolution=(raw_w, raw_h),
        material_mode=mode,
        is_animated=False,
        total_frames=1,
        frame_width=raw_w,
        frame_height=raw_h,
        uv_mode="LOCAL",
    )


def get_texture_resolution_for_face(
    face, obj, context, default_res: Tuple[int, int] = (64, 64), uv_layer=None
) -> Tuple[int, int]:
    """Retrieve effective texture width and height associated with a face's material."""
    info = get_face_effective_texture_info(face, obj, context, default_res=default_res, uv_layer=uv_layer)
    return info.effective_resolution


def calculate_face_target_grid(
    face,
    uv_layer,
    tex_w: int,
    tex_h: int,
    pixels_per_face: int = 1,
    max_subdivisions: int = 1024,
) -> TargetGrid:
    """Determine horizontal and vertical subdivision counts to match texture pixel resolution.

    Accurately accounts for:
    - UV rotation (90°, 180°, 270°)
    - Non-uniform quad shapes / trapezoids (evaluating opposing edge pairs)
    - Non-quad faces (bounding box UV span)
    - Safety clamping up to max_subdivisions
    """
    ppf = max(1, int(pixels_per_face))
    max_sub = max(1, int(max_subdivisions))

    if len(face.loops) == 4:
        uv0 = face.loops[0][uv_layer].uv
        uv1 = face.loops[1][uv_layer].uv
        uv2 = face.loops[2][uv_layer].uv
        uv3 = face.loops[3][uv_layer].uv

        # Calculate lengths of edge 0-1 and opposing edge 3-2 in texture pixel space
        len_01 = (((uv1.x - uv0.x) * tex_w) ** 2 + ((uv1.y - uv0.y) * tex_h) ** 2) ** 0.5
        len_32 = (((uv2.x - uv3.x) * tex_w) ** 2 + ((uv2.y - uv3.y) * tex_h) ** 2) ** 0.5

        # Calculate lengths of edge 0-3 and opposing edge 1-2 in texture pixel space
        len_03 = (((uv3.x - uv0.x) * tex_w) ** 2 + ((uv3.y - uv0.y) * tex_h) ** 2) ** 0.5
        len_12 = (((uv2.x - uv1.x) * tex_w) ** 2 + ((uv2.y - uv1.y) * tex_h) ** 2) ** 0.5

        span_u = max(len_01, len_32)
        span_v = max(len_03, len_12)

        cols = max(1, min(max_sub, int(round(span_u / ppf))))
        rows = max(1, min(max_sub, int(round(span_v / ppf))))
    else:
        bounds = get_face_uv_bounds(face, uv_layer)
        span_u = bounds.width * tex_w
        span_v = bounds.height * tex_h
        cols = max(1, min(max_sub, int(round(span_u / ppf))))
        rows = max(1, min(max_sub, int(round(span_v / ppf))))

    return TargetGrid(cols=cols, rows=rows, tex_w=tex_w, tex_h=tex_h)

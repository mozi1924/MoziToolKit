"""
Unified animation frame dimension and timing analyzer for materials and texture dictionaries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False


def get_material_animation_info(mat: Any | None) -> dict | None:
    """Return animation frame dimensions if mat is an animated material, else None.

    Returns a dictionary with keys:
    - 'frame_width': float
    - 'frame_height': float
    - 'img_width': float
    - 'img_height': float
    - 'total_frames': int
    """
    if not mat or not mat.use_nodes or not mat.node_tree:
        return None

    # 1. Check for MC_Animated_UV_Mapping node group
    for n in mat.node_tree.nodes:
        if n.type == "GROUP" and n.node_tree and all(
            socket in n.inputs for socket in ("Frame Width", "Frame Height", "Image Width", "Image Height")
        ):
            fw = float(n.inputs["Frame Width"].default_value) if "Frame Width" in n.inputs else 16.0
            fh = float(n.inputs["Frame Height"].default_value) if "Frame Height" in n.inputs else 16.0
            iw = float(n.inputs["Image Width"].default_value) if "Image Width" in n.inputs else 16.0
            ih = float(n.inputs["Image Height"].default_value) if "Image Height" in n.inputs else 16.0
            if ih > fh and fh > 0:
                return {
                    "frame_width": fw,
                    "frame_height": fh,
                    "img_width": iw,
                    "img_height": ih,
                    "total_frames": max(1, int(round(ih / fh))),
                }

    # 2. Check for MC .mcmeta Scheduler node group with images
    sched_node = next(
        (n for n in mat.node_tree.nodes if n.type == "GROUP" and "Total Frames" in n.inputs),
        None,
    )
    if sched_node and "Total Frames" in sched_node.inputs:
        tf = int(round(sched_node.inputs["Total Frames"].default_value))
        if tf > 1:
            for n in mat.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image and n.image.size[0] > 0 and n.image.size[1] > 0:
                    iw = float(n.image.size[0])
                    ih = float(n.image.size[1])
                    fh = max(1.0, ih / tf)
                    fw = iw
                    return {
                        "frame_width": fw,
                        "frame_height": fh,
                        "img_width": iw,
                        "img_height": ih,
                        "total_frames": tf,
                    }

    # 3. Check for vertical animation strip ratio heuristic on image nodes
    for n in mat.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image and n.image.size[0] > 0 and n.image.size[1] > 0:
            iw, ih = int(n.image.size[0]), int(n.image.size[1])
            if ih > iw and ih % iw == 0:
                tf = ih // iw
                return {
                    "frame_width": float(iw),
                    "frame_height": float(iw),
                    "img_width": float(iw),
                    "img_height": float(ih),
                    "total_frames": tf,
                }

    return None


def get_texture_info_animation_info(tex_info: dict | None, img: bpy.types.Image | None = None) -> dict | None:
    """Return animation frame dimensions for a texture_info dict if animated, else None.

    Returns a dictionary with keys:
    - 'frame_width': float
    - 'frame_height': float
    - 'img_width': float
    - 'img_height': float
    - 'total_frames': int
    """
    if not tex_info or not isinstance(tex_info, dict):
        return None

    anim_meta = tex_info.get("animation_metadata")
    if anim_meta and isinstance(anim_meta, dict):
        return {
            "frame_width": float(anim_meta.get("frame_width", 16)),
            "frame_height": float(anim_meta.get("frame_height", 16)),
            "img_width": float(anim_meta.get("image_width", 16)),
            "img_height": float(anim_meta.get("image_height", 16)),
            "total_frames": int(anim_meta.get("total_frames", 1)),
        }

    mcmeta = tex_info.get("albedo_mcmeta")
    albedo_path = tex_info.get("albedo")

    iw, ih = 0, 0
    if img and img.size[0] > 0 and img.size[1] > 0:
        iw, ih = int(img.size[0]), int(img.size[1])
    elif albedo_path and Path(albedo_path).exists():
        if bpy and hasattr(bpy, "data"):
            resolved_albedo = str(Path(albedo_path).resolve())
            for existing in bpy.data.images:
                if existing.filepath and str(Path(bpy.path.abspath(existing.filepath)).resolve()) == resolved_albedo:
                    if existing.size[0] > 0 and existing.size[1] > 0:
                        iw, ih = int(existing.size[0]), int(existing.size[1])
                        break
        if iw <= 0 or ih <= 0:
            try:
                from PIL import Image
                Image.MAX_IMAGE_PIXELS = 128 * 1024 * 1024
                with Image.open(albedo_path) as pil_img:
                    iw, ih = pil_img.size
            except Exception:
                pass

    if iw <= 0 or ih <= 0:
        return None

    fw = iw
    fh = iw
    is_anim = False
    if mcmeta and isinstance(mcmeta, dict):
        fw = int(mcmeta.get("width") or iw)
        fh = int(mcmeta.get("height") or fw)
        frames = mcmeta.get("frames", [])
        total_frames = ih // fh if fh > 0 else 1
        if total_frames > 1 or (isinstance(frames, list) and len(frames) > 1):
            is_anim = True
    elif ih > iw and ih % iw == 0:
        is_anim = True
        fw = iw
        fh = iw

    if is_anim and ih > fh and fh > 0:
        return {
            "frame_width": float(fw),
            "frame_height": float(fh),
            "img_width": float(iw),
            "img_height": float(ih),
            "total_frames": max(1, ih // fh),
        }
    return None

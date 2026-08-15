"""
UV area, pixel resolution, and collapse detection utilities for extrusion repair.
"""

from __future__ import annotations

from typing import Tuple, Optional
import bpy

from ..pixel_split.uv_analyzer import get_face_effective_texture_info
from ..materials.texture_finder import get_material_pixel_step


def calculate_face_uv_area(face, uv_layer) -> float:
    """Calculate 2D signed area of a face in UV space using Shoelace formula."""
    loops = face.loops
    if len(loops) < 3:
        return 0.0
    area = 0.0
    n = len(loops)
    for i in range(n):
        uv1 = loops[i][uv_layer].uv
        uv2 = loops[(i + 1) % n][uv_layer].uv
        area += (uv1.x * uv2.y - uv2.x * uv1.y)
    return 0.5 * abs(area)


def is_face_uv_collapsed(
    face,
    uv_layer,
    area_threshold: Optional[float] = None,
    dist_threshold: Optional[float] = None,
    pixel_step: Optional[Tuple[float, float]] = None,
) -> bool:
    """Check if face UVs are collapsed to a point, line segment, or near zero 2D area.

    Adapts dynamically to the face's UV pixel resolution if pixel_step is provided.
    """
    if len(face.loops) < 3:
        return True

    if pixel_step is not None:
        step_u, step_v = pixel_step
        calc_area_threshold = area_threshold if area_threshold is not None else (step_u * step_v * 0.05)
        calc_dist_threshold = dist_threshold if dist_threshold is not None else (min(step_u, step_v) * 0.1)
    else:
        calc_area_threshold = area_threshold if area_threshold is not None else 1e-6
        calc_dist_threshold = dist_threshold if dist_threshold is not None else 1e-4

    if calculate_face_uv_area(face, uv_layer) < calc_area_threshold:
        return True

    uvs = [l[uv_layer].uv for l in face.loops]
    max_dist_sq = 0.0
    for i in range(len(uvs)):
        for j in range(i + 1, len(uvs)):
            dist_sq = (uvs[i] - uvs[j]).length_squared
            if dist_sq > max_dist_sq:
                max_dist_sq = dist_sq
    return max_dist_sq < (calc_dist_threshold * calc_dist_threshold)


def get_face_pixel_step(
    face,
    obj=None,
    context=None,
    uv_layer=None,
    default_res: Tuple[int, int] = (64, 64),
) -> Tuple[float, float]:
    """Retrieve anisotropic 2D UV step (step_u, step_v) for 1 pixel on a face's texture.

    Supports:
    - ATLAS_UNIFIED (Local UVs corresponding to tile_size)
    - ATLAS_CHUNK (Baked Atlas UVs or Local UVs)
    - STANDALONE_BAKED (Animated strips with baked UVs)
    - STANDALONE / GENERIC (Non-square or square single textures)
    """
    active_obj = obj or (bpy.context.active_object if bpy and hasattr(bpy, "context") else None)
    active_ctx = context or (bpy.context if bpy and hasattr(bpy, "context") else None)

    if active_obj is not None:
        try:
            info = get_face_effective_texture_info(
                face,
                active_obj,
                active_ctx,
                default_res=default_res,
                uv_layer=uv_layer,
            )
            if info.uv_mode in ("ATLAS_BAKED", "STANDALONE_BAKED"):
                raw_w, raw_h = info.raw_image_resolution
                return (1.0 / max(1, raw_w), 1.0 / max(1, raw_h))
            else:
                eff_w, eff_h = info.effective_resolution
                return (1.0 / max(1, eff_w), 1.0 / max(1, eff_h))
        except Exception:
            pass

    # Fallback to active material or default
    if active_obj and active_obj.active_material:
        step = get_material_pixel_step(active_obj.active_material, default_size=default_res[0])
        return (step, step)
    return (1.0 / float(default_res[0]), 1.0 / float(default_res[1]))


def get_active_texture_pixel_step(obj=None) -> float:
    """Legacy helper: Retrieve scalar UV step for active object's material."""
    active_obj = obj or (bpy.context.active_object if bpy and hasattr(bpy, "context") else None)
    if active_obj and active_obj.active_material:
        return get_material_pixel_step(active_obj.active_material, default_size=64)
    return 1.0 / 64.0

"""
UV area, pixel resolution, and collapse detection utilities for extrusion repair.
"""

from __future__ import annotations

from typing import Tuple, Optional
import bpy

from ..pixel_split.uv_analyzer import get_face_effective_texture_info
from ..materials.matching import get_material_pixel_step


from ..mesh.uv_math import (
    calculate_face_uv_area,
    is_face_uv_collapsed,
)



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

"""
UV Pipeline and Space Remapping Utilities.
Handles loop UV coordinate remapping between Atlas, Standalone, and Local UV spaces,
as well as face-level UV rotation straightening and shader tiling normalization.
"""

from __future__ import annotations

from typing import Optional
import bpy

from ..atlas.layout import (
    remap_uv_coordinate,
    remap_uv_to_local,
    remap_local_to_target_uv,
)
from ...mesh.uv_rotation import (
    straighten_face_uv,
    normalize_face_uv_for_atlas_tiling,
    face_uv_requires_atlas_tiling,
    restore_atlas_tiling_uv,
)
from ...mesh.fluid_uv import (
    is_fluid_texture_name,
    is_flowing_fluid_texture,
    normalize_static_fluid_face_uv,
    repair_polygon_fluid_uv,
)



def remap_polygon_loop_uvs(
    polygon: bpy.types.MeshPolygon,
    uv_layer: bpy.types.MeshUVLoopLayer,
    orig_mode: str,
    old_loc: Optional[dict] = None,
    old_chunk: Optional[dict] = None,
    old_anim_info: Optional[dict] = None,
    target_location: Optional[dict] = None,
    target_chunk: Optional[dict] = None,
    target_anim_info: Optional[dict] = None,
) -> None:
    """Transform all loop UVs for a single polygon from source space to target space."""
    for loop_index in polygon.loop_indices:
        uv = uv_layer.data[loop_index].uv
        uv.x, uv.y = remap_uv_coordinate(
            uv.x, uv.y,
            orig_mode=orig_mode,
            old_loc=old_loc,
            old_chunk=old_chunk,
            old_anim_info=old_anim_info,
            target_location=target_location,
            target_chunk=target_chunk,
            target_anim_info=target_anim_info,
        )


def remap_face_uv_to_local(
    polygon: bpy.types.MeshPolygon,
    uv_layer: bpy.types.MeshUVLoopLayer,
    orig_mode: str,
    old_loc: Optional[dict] = None,
    old_chunk: Optional[dict] = None,
    old_anim_info: Optional[dict] = None,
) -> None:
    """Map loop UV coordinates of a polygon back to source-local [0, 1] normalized space."""
    for loop_index in polygon.loop_indices:
        uv = uv_layer.data[loop_index].uv
        uv.x, uv.y = remap_uv_to_local(
            uv.x, uv.y, orig_mode, old_loc, old_chunk, old_anim_info
        )


def restore_face_atlas_tiling(
    polygon: bpy.types.MeshPolygon,
    uv_layer: bpy.types.MeshUVLoopLayer,
    tiling_scale: tuple[float, float, float],
    tiling_location: tuple[float, float, float],
    tiling_rotation: float,
) -> None:
    """Bake stored UV tiling transformation (scale, offset, rotation) back into loop UV coordinates."""
    for loop_index in polygon.loop_indices:
        uv = uv_layer.data[loop_index].uv
        uv.x, uv.y = restore_atlas_tiling_uv(
            uv.x, uv.y, tiling_scale, tiling_location, tiling_rotation
        )


def straighten_and_normalize_face_uv(
    polygon: bpy.types.MeshPolygon,
    uv_layer: bpy.types.MeshUVLoopLayer,
) -> tuple[float, tuple[float, float, float], tuple[float, float, float]]:
    """Straighten non-orthogonal UVs (e.g. liquid) and compute atlas tiling transform if required.

    Returns:
        (uv_rotation, uv_tiling_scale, uv_tiling_location)
    """
    rot_angle, was_straightened = straighten_face_uv(polygon, uv_layer)
    uv_rotation = float(rot_angle) if was_straightened else 0.0
    uv_tiling_scale = (1.0, 1.0, 1.0)
    uv_tiling_location = (0.0, 0.0, 0.0)

    if was_straightened or face_uv_requires_atlas_tiling(polygon, uv_layer):
        scale, location = normalize_face_uv_for_atlas_tiling(polygon, uv_layer)
        uv_tiling_scale = scale
        uv_tiling_location = location

    return uv_rotation, uv_tiling_scale, uv_tiling_location

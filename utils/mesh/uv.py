"""
UV bounds, center calculations, and face image resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
import sys
try:
    import bpy
    from mathutils import Vector
except ImportError:
    bpy = None
    Vector = None

from ..materials.texture_finder import find_face_image
from .uv_rotation import (
    is_orthogonal_angle,
    detect_face_uv_rotation,
    straighten_face_uv,
    process_mesh_uv_rotations,
    normalize_face_uv_for_atlas_tiling,
    face_uv_requires_atlas_tiling,
    restore_atlas_tiling_uv,
)
from .fluid_uv import (
    repair_face_fluid_uv,
    process_mesh_fluid_uv_repairs,
)


@dataclass
class UVBounds:
    """Bounding box of UV coordinates for a face or group of faces."""
    min_u: float
    max_u: float
    min_v: float
    max_v: float

    @property
    def width(self) -> float:
        return self.max_u - self.min_u

    @property
    def height(self) -> float:
        return self.max_v - self.min_v


def get_face_uv_bounds(face, uv_layer) -> UVBounds:
    """Calculate min/max UV coordinates for a face."""
    if not face.loops:
        return UVBounds(0.0, 0.0, 0.0, 0.0)

    u_coords = [loop[uv_layer].uv.x for loop in face.loops]
    v_coords = [loop[uv_layer].uv.y for loop in face.loops]

    return UVBounds(
        min_u=min(u_coords),
        max_u=max(u_coords),
        min_v=min(v_coords),
        max_v=max(v_coords),
    )


def get_face_uv_center(face, uv_layer) -> Vector:
    """Calculate geometric center vector of a face's UV loop coordinates."""
    if not face.loops:
        return Vector((0.0, 0.0))

    uv_center = Vector((0.0, 0.0))
    for loop in face.loops:
        uv_center += loop[uv_layer].uv
    uv_center /= len(face.loops)
    return uv_center


def get_image_from_face(face, obj, context=None) -> bpy.types.Image | None:
    """Find the Image object associated with a bmesh face."""
    return find_face_image(face, obj, context)

"""
UV geometric calculations, center, bounds, and face scaling helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

try:
    import bpy
    from mathutils import Vector
except ImportError:
    bpy = None
    Vector = None


@dataclass
class UVBounds:
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


def get_face_uv_center(face, uv_layer):
    """Calculate geometric center vector of a face's UV loop coordinates."""
    if not face.loops:
        return Vector((0.0, 0.0)) if Vector else (0.0, 0.0)

    if Vector:
        uv_center = Vector((0.0, 0.0))
        for loop in face.loops:
            uv_center += loop[uv_layer].uv
        uv_center /= len(face.loops)
        return uv_center
    else:
        tot_u = sum(loop[uv_layer].uv.x for loop in face.loops)
        tot_v = sum(loop[uv_layer].uv.y for loop in face.loops)
        n = float(len(face.loops))
        return (tot_u / n, tot_v / n)


def calculate_face_uv_area(face, uv_layer) -> float:
    """Calculate 2D signed area of a face in UV space using the Shoelace formula."""
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

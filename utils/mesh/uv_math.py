"""
Common UV geometric algorithms, Shoelace area calculation, collapse detection, and bounds.
Provides unified, high-performance mathematical primitives for UV manipulation across MoziToolKit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

try:
    import bpy
    from mathutils import Vector
except ImportError:
    bpy = None
    Vector = None


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


def is_orthogonal_angle(angle: float, tolerance: float = 1e-3) -> bool:
    """Check if an angle in radians is close to a multiple of 90 degrees (pi/2)."""
    half_pi = math.pi / 2.0
    rem = abs(angle) % half_pi
    return rem < tolerance or abs(rem - half_pi) < tolerance

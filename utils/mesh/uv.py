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


try:
    from ...bridge.uv import (
        calculate_uv_area as _rust_calculate_uv_area,
        get_uv_bounds as _rust_get_uv_bounds,
        get_uv_center as _rust_get_uv_center,
    )
except (ImportError, ValueError):
    from bridge.uv import (
        calculate_uv_area as _rust_calculate_uv_area,
        get_uv_bounds as _rust_get_uv_bounds,
        get_uv_center as _rust_get_uv_center,
    )


def get_face_uv_bounds(face, uv_layer) -> UVBounds:
    """Calculate min/max UV coordinates for a face using Rust accelerated bounds."""
    if not face.loops:
        return UVBounds(0.0, 0.0, 0.0, 0.0)

    uvs = [(loop[uv_layer].uv.x, loop[uv_layer].uv.y) for loop in face.loops]
    min_u, min_v, max_u, max_v, _span_u, _span_v = _rust_get_uv_bounds(uvs)
    return UVBounds(
        min_u=min_u,
        max_u=max_u,
        min_v=min_v,
        max_v=max_v,
    )


def get_face_uv_center(face, uv_layer):
    """Calculate geometric center vector of a face's UV loop coordinates using Rust."""
    if not face.loops:
        return Vector((0.0, 0.0)) if Vector else (0.0, 0.0)

    uvs = [(loop[uv_layer].uv.x, loop[uv_layer].uv.y) for loop in face.loops]
    cu, cv = _rust_get_uv_center(uvs)
    return Vector((cu, cv)) if Vector else (cu, cv)


def calculate_face_uv_area(face, uv_layer) -> float:
    """Calculate 2D signed area of a face in UV space using Rust accelerated Shoelace formula."""
    if not face.loops or len(face.loops) < 3:
        return 0.0
    uvs = [(loop[uv_layer].uv.x, loop[uv_layer].uv.y) for loop in face.loops]
    return _rust_calculate_uv_area(uvs)


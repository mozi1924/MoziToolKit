"""
UV rotation detection, straightening, and mesh attribute management.

Identifies faces with rotated UV coordinates (such as jmc2obj flowing liquid UVs
rotated by non-orthogonal angles like 45°, 135°), straightens them into canonical
[0, 1] coordinates, and extracts the Euler Z rotation angle for the MC_Atlas_UV_Tiling
shader node group.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple, List

try:
    import bpy
    from mathutils import Vector
except ImportError:
    bpy = None
    Vector = None


def is_orthogonal_angle(angle: float, tolerance: float = 1e-3) -> bool:
    """Check if an angle (in radians) is a multiple of 90 degrees (pi / 2)."""
    half_pi = math.pi / 2.0
    rem = angle % half_pi
    return abs(rem) < tolerance or abs(rem - half_pi) < tolerance


def detect_face_uv_rotation(polygon, uv_layer, tolerance: float = 1e-3) -> float:
    """Calculate the Euler Z rotation angle (in radians) of a face's loop UVs.

    Returns 0.0 for unrotated or standard axis-aligned faces.
    Returns non-zero angle theta in radians for non-orthogonal rotated faces
    (e.g., jmc2obj flowing water UVs rotated at 45°, 135°, -45°, -135°).
    """
    if polygon is None or uv_layer is None or len(polygon.loop_indices) < 3:
        return 0.0

    loop_indices = polygon.loop_indices
    uvs = [uv_layer.data[li].uv for li in loop_indices]

    # Find the primary direction edge e01
    p0 = uvs[0]
    p1 = uvs[1]
    edge = Vector((p1.x - p0.x, p1.y - p0.y))

    if edge.length < 1e-6:
        # Fallback if first edge is degenerate
        for i in range(1, len(uvs)):
            p_curr = uvs[i]
            p_next = uvs[(i + 1) % len(uvs)]
            edge = Vector((p_next.x - p_curr.x, p_next.y - p_curr.y))
            if edge.length >= 1e-6:
                break
        else:
            return 0.0

    theta = math.atan2(edge.y, edge.x)

    # Normalize theta to (-pi, pi]
    while theta <= -math.pi:
        theta += 2.0 * math.pi
    while theta > math.pi:
        theta -= 2.0 * math.pi

    if is_orthogonal_angle(theta, tolerance):
        # Standard axis-aligned face (multiples of 90 degrees)
        return 0.0

    return theta


def straighten_face_uv(polygon, uv_layer, angle: Optional[float] = None) -> Tuple[float, bool]:
    """Straighten a rotated polygon's loop UVs back to standard axis-aligned coordinates.

    Rotates loop UVs by -angle around the UV geometric center.
    Returns (angle, was_straightened).
    """
    if polygon is None or uv_layer is None or len(polygon.loop_indices) < 3:
        return 0.0, False

    if angle is None:
        angle = detect_face_uv_rotation(polygon, uv_layer)

    if abs(angle) < 1e-4:
        return 0.0, False

    loop_indices = polygon.loop_indices
    uv_objs = [uv_layer.data[li].uv for li in loop_indices]
    num_loops = len(uv_objs)

    # Calculate UV center
    center_u = sum(uv.x for uv in uv_objs) / num_loops
    center_v = sum(uv.y for uv in uv_objs) / num_loops

    # Rotate by -angle around center
    cos_t = math.cos(-angle)
    sin_t = math.sin(-angle)

    for uv in uv_objs:
        dx = uv.x - center_u
        dy = uv.y - center_v
        new_x = center_u + (dx * cos_t - dy * sin_t)
        new_y = center_v + (dx * sin_t + dy * cos_t)
        uv.x = new_x
        uv.y = new_y

    return angle, True


def process_mesh_uv_rotations(mesh, uv_layer=None) -> List[float]:
    """Detect and straighten rotated UVs across all faces in a mesh.

    Returns a list of rotation angles (in radians) matching mesh.polygons order.
    """
    if mesh is None or not mesh.polygons:
        return []

    if uv_layer is None:
        uv_layer = mesh.uv_layers.active

    if uv_layer is None:
        return [0.0] * len(mesh.polygons)

    rotations: List[float] = []
    for poly in mesh.polygons:
        rot, _straightened = straighten_face_uv(poly, uv_layer)
        rotations.append(rot)

    return rotations


def normalize_face_uv_for_atlas_tiling(polygon, uv_layer, epsilon: float = 1e-6) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """Normalize one face's local UV rectangle and return its Mapping inputs.

    Atlas UVs must stay in one cell.  Optimised jmc2obj quads can span many
    local texture repeats, so their original affine coordinate is retained as
    per-face Mapping scale/location data for ``MC_Atlas_UV_Tiling``.
    """
    if polygon is None or uv_layer is None or not polygon.loop_indices:
        return (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)

    uvs = [uv_layer.data[index].uv for index in polygon.loop_indices]
    min_u, max_u = min(uv.x for uv in uvs), max(uv.x for uv in uvs)
    min_v, max_v = min(uv.y for uv in uvs), max(uv.y for uv in uvs)
    span_u, span_v = max_u - min_u, max_v - min_v

    # A collapsed UV axis cannot be normalized. Keep it stable rather than
    # creating infinities; the texture lookup remains constant on that axis.
    safe_span_u = span_u if span_u > epsilon else 1.0
    safe_span_v = span_v if span_v > epsilon else 1.0
    for uv in uvs:
        uv.x = (uv.x - min_u) / safe_span_u if span_u > epsilon else 0.0
        uv.y = (uv.y - min_v) / safe_span_v if span_v > epsilon else 0.0

    # MC_Atlas_UV_Tiling subtracts/adds 0.5 around the Mapping node, hence
    # this location produces ``min + span * normalized_uv`` exactly.
    return (
        (safe_span_u, safe_span_v, 1.0),
        (min_u + (safe_span_u - 1.0) * 0.5, min_v + (safe_span_v - 1.0) * 0.5, 0.0),
    )

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
    from mathutils import Vector
except ImportError:
    Vector = None


from .uv_math import is_orthogonal_angle


def detect_face_uv_rotation(polygon, uv_layer, tolerance: float = 1e-3) -> float:
    """Calculate the Euler Z rotation angle (in radians) of a face's loop UVs.

    Returns 0.0 for unrotated or standard axis-aligned faces (including right
    triangles and trapezoids where at least one edge aligns orthogonally).
    Returns non-zero angle theta in radians only when ALL valid edges of the face
    are non-orthogonal (e.g., jmc2obj flowing water UVs rotated at 45°, 135°).
    """
    if polygon is None or uv_layer is None or len(polygon.loop_indices) < 3:
        return 0.0

    loop_indices = polygon.loop_indices
    uvs = [uv_layer.data[li].uv for li in loop_indices]
    num_uvs = len(uvs)

    valid_edges = []
    for i in range(num_uvs):
        p_curr = uvs[i]
        p_next = uvs[(i + 1) % num_uvs]
        edge = Vector((p_next.x - p_curr.x, p_next.y - p_curr.y))
        if edge.length >= 1e-6:
            theta = math.atan2(edge.y, edge.x)
            while theta <= -math.pi:
                theta += 2.0 * math.pi
            while theta > math.pi:
                theta -= 2.0 * math.pi
            valid_edges.append((edge, theta))

    if not valid_edges:
        return 0.0

    # If ANY edge is orthogonal, the face is built in an axis-aligned grid
    # (e.g. right triangles with a diagonal hypotenuse, axis-aligned stairs)
    for _edge, theta in valid_edges:
        if is_orthogonal_angle(theta, tolerance):
            return 0.0

    # If ALL valid edges are non-orthogonal, the entire face is tilted
    # (e.g. jmc2obj 45-degree flowing liquid diamonds)
    primary_theta = valid_edges[0][1]
    if is_orthogonal_angle(primary_theta, tolerance):
        return 0.0

    return primary_theta


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


def face_uv_requires_atlas_tiling(polygon, uv_layer, epsilon: float = 1e-4) -> bool:
    """Return whether local UVs need shader-side wrapping to fit an Atlas cell.

    A UV region smaller than one tile is common for pixel-split block faces
    and partial models such as campfires.  It must remain directly baked into
    the Atlas cell.  Only coordinates that escape the canonical 0..1 tile
    need the scale/location attributes and the tiling node's ``FRACT`` step.
    """
    if polygon is None or uv_layer is None or not polygon.loop_indices:
        return False
    uvs = [uv_layer.data[index].uv for index in polygon.loop_indices]
    return (
        min(uv.x for uv in uvs) < -epsilon
        or max(uv.x for uv in uvs) > 1.0 + epsilon
        or min(uv.y for uv in uvs) < -epsilon
        or max(uv.y for uv in uvs) > 1.0 + epsilon
    )


def restore_atlas_tiling_uv(
    u: float,
    v: float,
    scale: Tuple[float, float, float] = (1.0, 1.0, 1.0),
    location: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: float = 0.0,
) -> Tuple[float, float]:
    """Apply the Atlas tiling node's affine mapping to normalized local UV.

    Atlas meshes store UVs normalized to one atlas cell.  The shader restores
    the original jmc2obj tiled/rotated coordinate before wrapping it.  When
    converting back to Standalone, the same transform must be baked into the
    mesh UVs because Standalone materials do not include the atlas tiling node.
    """
    sx, sy = float(scale[0]), float(scale[1])
    lx, ly = float(location[0]), float(location[1])
    x = sx * (float(u) - 0.5)
    y = sy * (float(v) - 0.5)
    if abs(rotation) > 1e-8:
        cos_t = math.cos(rotation)
        sin_t = math.sin(rotation)
        x, y = x * cos_t - y * sin_t, x * sin_t + y * cos_t
    return x + lx + 0.5, y + ly + 0.5

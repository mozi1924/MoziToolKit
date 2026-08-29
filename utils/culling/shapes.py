"""
2D Face Occlusion Shape calculation and geometric Boolean occlusion tests.
Equivalent to Minecraft's VoxelShape.getFaceOcclusionShape and Shapes.joinIsNotEmpty(BooleanOp.ONLY_FIRST).
"""

from __future__ import annotations
from typing import Sequence, Optional, List, Tuple
from .types import FaceOcclusionRect, FULL_FACE_RECT, EMPTY_FACE_RECT

_EPSILON = 1e-4


def subtract_rect(
    rect: FaceOcclusionRect,
    cutter: FaceOcclusionRect
) -> list[FaceOcclusionRect]:
    """
    Subtract a 2D axis-aligned cutter rectangle from a target rectangle.
    Returns a list of 0 to 4 remaining non-overlapping rectangular fragments.
    """
    a0, b0, a1, b1 = rect.min_u, rect.min_v, rect.max_u, rect.max_v
    ca0, cb0, ca1, cb1 = cutter.min_u, cutter.min_v, cutter.max_u, cutter.max_v

    ia0, ia1 = max(a0, ca0), min(a1, ca1)
    ib0, ib1 = max(b0, cb0), min(b1, cb1)

    # No intersection
    if (ia1 - ia0) <= _EPSILON or (ib1 - ib0) <= _EPSILON:
        return [rect]

    candidates = [
        FaceOcclusionRect(a0, b0, ia0, b1),  # Left remainder
        FaceOcclusionRect(ia1, b0, a1, b1),  # Right remainder
        FaceOcclusionRect(ia0, b0, ia1, ib0), # Bottom remainder
        FaceOcclusionRect(ia0, ib1, ia1, b1), # Top remainder
    ]

    return [
        r for r in candidates
        if (r.max_u - r.min_u) > _EPSILON and (r.max_v - r.min_v) > _EPSILON
    ]


def is_face_completely_occluded(
    target_rects: Sequence[FaceOcclusionRect],
    neighbor_occluder_rects: Sequence[FaceOcclusionRect]
) -> bool:
    """
    Check if all rectangles in target_rects are completely covered by neighbor_occluder_rects.
    Returns True if target is 100% occluded (should be culled), False if any part remains visible.
    
    Equivalent to Minecraft Shapes.joinIsNotEmpty(targetShape, occluderShape, BooleanOp.ONLY_FIRST) == False.
    """
    if not target_rects:
        return True
    if not neighbor_occluder_rects:
        return False

    # Fast path: check if neighbor has a full face
    for occ in neighbor_occluder_rects:
        if occ.is_full:
            return True

    # Detailed 2D polygon subtraction
    for target in target_rects:
        if target.is_empty:
            continue
        pieces = [target]
        for occ in neighbor_occluder_rects:
            if occ.is_empty:
                continue
            next_pieces: list[FaceOcclusionRect] = []
            for p in pieces:
                next_pieces.extend(subtract_rect(p, occ))
            pieces = next_pieces
            if not pieces:
                break
        # If any fragment of this target rect remains unoccluded, the face is visible!
        if pieces:
            return False

    return True


def extract_face_occlusion_from_elements(
    elements_boxes: Sequence[Tuple[Tuple[float, float, float], Tuple[float, float, float]]],
    direction: str,
) -> tuple[FaceOcclusionRect, ...]:
    """
    Derive 2D face occlusion rectangles on an outer boundary plane from 3D axis-aligned cuboids.
    
    direction: 'east' (+X=1), 'west' (-X=0), 'up' (+Y=1), 'down' (-Y=0), 'south' (+Z=1), 'north' (-Z=0)
    """
    rects: list[FaceOcclusionRect] = []
    dir_low = direction.lower()

    for (x0, y0, z0), (x1, y1, z1) in elements_boxes:
        if dir_low == "east":
            # Outer plane at X=1
            if abs(x1 - 1.0) <= _EPSILON:
                rects.append(FaceOcclusionRect(z0, y0, z1, y1))
        elif dir_low == "west":
            # Outer plane at X=0
            if abs(x0 - 0.0) <= _EPSILON:
                rects.append(FaceOcclusionRect(z0, y0, z1, y1))
        elif dir_low in ("up", "top"):
            # Outer plane at Y=1
            if abs(y1 - 1.0) <= _EPSILON:
                rects.append(FaceOcclusionRect(x0, z0, x1, z1))
        elif dir_low in ("down", "bottom"):
            # Outer plane at Y=0
            if abs(y0 - 0.0) <= _EPSILON:
                rects.append(FaceOcclusionRect(x0, z0, x1, z1))
        elif dir_low == "south":
            # Outer plane at Z=1
            if abs(z1 - 1.0) <= _EPSILON:
                rects.append(FaceOcclusionRect(x0, y0, x1, y1))
        elif dir_low == "north":
            # Outer plane at Z=0
            if abs(z0 - 0.0) <= _EPSILON:
                rects.append(FaceOcclusionRect(x0, y0, x1, y1))

    # Filter out empty rectangles
    valid_rects = tuple(r for r in rects if not r.is_empty)
    return valid_rects


def extract_quad_face_occlusion_rect(
    vertices: Sequence[Tuple[float, float, float]],
    direction: str,
) -> Optional[FaceOcclusionRect]:
    """
    Extract 2D FaceOcclusionRect on the outer plane for a single quad face's vertices in [0..1] space.
    If the quad lies on the boundary plane corresponding to direction, returns the 2D rect;
    otherwise returns None.
    """
    if not vertices or len(vertices) < 3:
        return None
    dir_low = direction.lower()
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    min_z, max_z = min(zs), max(zs)

    if dir_low == "east":
        if abs(max_x - 1.0) <= _EPSILON and abs(min_x - 1.0) <= _EPSILON:
            r = FaceOcclusionRect(min_z, min_y, max_z, max_y)
            return r if not r.is_empty else None
    elif dir_low == "west":
        if abs(min_x - 0.0) <= _EPSILON and abs(max_x - 0.0) <= _EPSILON:
            r = FaceOcclusionRect(min_z, min_y, max_z, max_y)
            return r if not r.is_empty else None
    elif dir_low in ("up", "top"):
        if abs(max_y - 1.0) <= _EPSILON and abs(min_y - 1.0) <= _EPSILON:
            r = FaceOcclusionRect(min_x, min_z, max_x, max_z)
            return r if not r.is_empty else None
    elif dir_low in ("down", "bottom"):
        if abs(min_y - 0.0) <= _EPSILON and abs(max_y - 0.0) <= _EPSILON:
            r = FaceOcclusionRect(min_x, min_z, max_x, max_z)
            return r if not r.is_empty else None
    elif dir_low == "south":
        if abs(max_z - 1.0) <= _EPSILON and abs(min_z - 1.0) <= _EPSILON:
            r = FaceOcclusionRect(min_x, min_y, max_x, max_y)
            return r if not r.is_empty else None
    elif dir_low == "north":
        if abs(min_z - 0.0) <= _EPSILON and abs(max_z - 0.0) <= _EPSILON:
            r = FaceOcclusionRect(min_x, min_y, max_x, max_y)
            return r if not r.is_empty else None
    return None


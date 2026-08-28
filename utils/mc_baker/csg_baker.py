"""
3D AABB CSG (Constructive Solid Geometry) Boolean Baking for Minecraft Models.
Performs exact orthogonal box decomposition to clip fluid geometry for waterlogged blocks,
eliminating internal water faces and co-planar Z-fighting with zero runtime overhead.
"""

from __future__ import annotations
from typing import Sequence, Optional, List, Tuple
from .types import BakedModel, BakedElement, BakedFace, MC_DIRECTIONS
from .math_utils import default_face_uv, bake_face_exact

AABB = Tuple[float, float, float, float, float, float]  # (min_x, min_y, min_z, max_x, max_y, max_z) in [0..16]

_EPS: float = 1e-5


def subtract_aabb(box: AABB, cut: AABB, eps: float = _EPS) -> List[AABB]:
    """
    Subtract an axis-aligned 3D bounding box `cut` from `box`.
    Returns a list of 0 to 6 disjoint sub-AABBs covering (box \\ cut).
    All coordinates in [0..16] space.
    """
    x0, y0, z0, x1, y1, z1 = box
    cx0, cy0, cz0, cx1, cy1, cz1 = cut

    # Compute overlap intersection
    ix0, ix1 = max(x0, cx0), min(x1, cx1)
    iy0, iy1 = max(y0, cy0), min(y1, cy1)
    iz0, iz1 = max(z0, cz0), min(z1, cz1)

    # If no intersection / invalid volume, the original box remains untouched
    if ix1 - ix0 <= eps or iy1 - iy0 <= eps or iz1 - iz0 <= eps:
        return [box]

    result: List[AABB] = []

    # 1. Bottom sub-box (-Y)
    if iy0 - y0 > eps:
        result.append((x0, y0, z0, x1, iy0, z1))

    # 2. Top sub-box (+Y)
    if y1 - iy1 > eps:
        result.append((x0, iy1, z0, x1, y1, z1))

    # 3. Left sub-box (-X, clamped to Y intersection)
    if ix0 - x0 > eps:
        result.append((x0, iy0, z0, ix0, iy1, z1))

    # 4. Right sub-box (+X, clamped to Y intersection)
    if x1 - ix1 > eps:
        result.append((ix1, iy0, z0, x1, iy1, z1))

    # 5. North/Back sub-box (-Z, clamped to X & Y intersection)
    if iz0 - z0 > eps:
        result.append((ix0, iy0, z0, ix1, iy1, iz0))

    # 6. South/Front sub-box (+Z, clamped to X & Y intersection)
    if z1 - iz1 > eps:
        result.append((ix0, iy0, iz1, ix1, iy1, z1))

    return [b for b in result if (b[3] - b[0] > eps and b[4] - b[1] > eps and b[5] - b[2] > eps)]


def difference_aabbs(subjects: Sequence[AABB], cuts: Sequence[AABB], eps: float = _EPS) -> List[AABB]:
    """
    Perform iterative difference: (subjects \\ cuts).
    Subtracts each cut AABB from all active subject pieces.
    """
    current_boxes = list(subjects)
    for cut in cuts:
        next_boxes: List[AABB] = []
        for box in current_boxes:
            pieces = subtract_aabb(box, cut, eps=eps)
            next_boxes.extend(pieces)
        current_boxes = next_boxes
        if not current_boxes:
            break
    return current_boxes


def extract_solid_aabbs(elements: Sequence[BakedElement], eps: float = _EPS) -> List[AABB]:
    """
    Extract axis-aligned bounding boxes (AABBs) in [0..16] space from BakedElement instances.
    """
    solid_boxes: List[AABB] = []
    for elem in elements:
        fx, fy, fz = elem.from_pos
        tx, ty, tz = elem.to_pos
        min_x, max_x = min(fx, tx), max(fx, tx)
        min_y, max_y = min(fy, ty), max(fy, ty)
        min_z, max_z = min(fz, tz), max(fz, tz)
        if max_x - min_x > eps and max_y - min_y > eps and max_z - min_z > eps:
            solid_boxes.append((min_x, min_y, min_z, max_x, max_y, max_z))
    return solid_boxes


def create_water_element_from_aabb(
    box: AABB,
    water_texture: str = "minecraft:block/water_still",
    tint_index: int = 0,
) -> BakedElement:
    """
    Construct a BakedElement for a water AABB sub-box.
    Generates exact 6-face vertices and standard UVs.
    """
    min_x, min_y, min_z, max_x, max_y, max_z = box
    from_pos = (min_x, min_y, min_z)
    to_pos = (max_x, max_y, max_z)

    faces: dict[str, BakedFace] = {}
    for d in MC_DIRECTIONS:
        final_dir, uv_rot, verts, uvs, uv_bounds = bake_face_exact(
            orig_dir=d,
            from_pos=from_pos,
            to_pos=to_pos,
            face_rotation_deg=0.0,
            uv_bounds=None,
            rot_x=0.0,
            rot_y=0.0,
            elem_rotation=None,
            uvlock=False,
            uv_base=16.0,
        )
        faces[d] = BakedFace(
            direction=final_dir,
            texture=water_texture,
            uv_rot=uv_rot,
            uv_bounds=uv_bounds,
            tint_index=tint_index,
            cullface=d if (
                (d == "down" and min_y <= _EPS) or
                (d == "up" and max_y >= 16.0 - _EPS) or
                (d == "north" and min_z <= _EPS) or
                (d == "south" and max_z >= 16.0 - _EPS) or
                (d == "west" and min_x <= _EPS) or
                (d == "east" and max_x >= 16.0 - _EPS)
            ) else None,
            vertices=tuple(verts),
            uvs=tuple(uvs),
        )

    return BakedElement(
        from_pos=from_pos,
        to_pos=to_pos,
        faces=faces,
        rotation=None,
    )


def bake_waterlogged_elements(
    solid_elements: Sequence[BakedElement],
    fluid_height: float = 16.0,
    water_texture: str = "minecraft:block/water_still",
    tint_index: int = 0,
    eps: float = _EPS,
) -> List[BakedElement]:
    """
    Bake fluid geometry for a waterlogged block using exact AABB CSG subtraction.
    (Water Box [0..16, 0..fluid_height, 0..16]) \\ (Solid Elements)
    """
    initial_water_box: AABB = (0.0, 0.0, 0.0, 16.0, fluid_height, 16.0)
    solid_boxes = extract_solid_aabbs(solid_elements, eps=eps)
    water_boxes = difference_aabbs([initial_water_box], solid_boxes, eps=eps)

    elements: List[BakedElement] = []
    for wb in water_boxes:
        elem = create_water_element_from_aabb(
            box=wb,
            water_texture=water_texture,
            tint_index=tint_index,
        )
        elements.append(elem)
    return elements

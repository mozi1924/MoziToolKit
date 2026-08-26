"""
Mathematical utilities for 3D transformation, Quad baking, and UV calculations
based directly on Minecraft 26.2 official FaceBakery, FaceInfo, and BlockMath.
"""

from __future__ import annotations
import math
from typing import Tuple, List, Optional, Dict

Vec3 = Tuple[float, float, float]
Vec2 = Tuple[float, float]
Mat3 = Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]

MC_DIRECTIONS: list[str] = ["east", "west", "up", "down", "south", "north"]

DIR_TO_INDEX: dict[str, int] = {
    "east": 0,
    "west": 1,
    "up": 2,
    "down": 3,
    "south": 4,
    "north": 5,
}

DIR_VECTORS: dict[str, Vec3] = {
    "east": (1.0, 0.0, 0.0),    # +X
    "west": (-1.0, 0.0, 0.0),   # -X
    "up": (0.0, 1.0, 0.0),      # +Y
    "down": (0.0, -1.0, 0.0),   # -Y
    "south": (0.0, 0.0, 1.0),   # +Z
    "north": (0.0, 0.0, -1.0),  # -Z
}

VECTOR_TO_DIR: dict[tuple[int, int, int], str] = {
    (1, 0, 0): "east",
    (-1, 0, 0): "west",
    (0, 1, 0): "up",
    (0, -1, 0): "down",
    (0, 0, 1): "south",
    (0, 0, -1): "north",
}

# FaceInfo Extent vertex definitions (exact from FaceInfo.java in Minecraft 26.2)
FACE_INFO_CANONICAL: dict[str, list[Vec3]] = {
    "down": [
        (0.0, 0.0, 1.0),  # 0: MIN_X, MIN_Y, MAX_Z
        (0.0, 0.0, 0.0),  # 1: MIN_X, MIN_Y, MIN_Z
        (1.0, 0.0, 0.0),  # 2: MAX_X, MIN_Y, MIN_Z
        (1.0, 0.0, 1.0),  # 3: MAX_X, MIN_Y, MAX_Z
    ],
    "up": [
        (0.0, 1.0, 0.0),  # 0: MIN_X, MAX_Y, MIN_Z
        (0.0, 1.0, 1.0),  # 1: MIN_X, MAX_Y, MAX_Z
        (1.0, 1.0, 1.0),  # 2: MAX_X, MAX_Y, MAX_Z
        (1.0, 1.0, 0.0),  # 3: MAX_X, MAX_Y, MIN_Z
    ],
    "north": [
        (1.0, 1.0, 0.0),  # 0: MAX_X, MAX_Y, MIN_Z
        (1.0, 0.0, 0.0),  # 1: MAX_X, MIN_Y, MIN_Z
        (0.0, 0.0, 0.0),  # 2: MIN_X, MIN_Y, MIN_Z
        (0.0, 1.0, 0.0),  # 3: MIN_X, MAX_Y, MIN_Z
    ],
    "south": [
        (0.0, 1.0, 1.0),  # 0: MIN_X, MAX_Y, MAX_Z
        (0.0, 0.0, 1.0),  # 1: MIN_X, MIN_Y, MAX_Z
        (1.0, 0.0, 1.0),  # 2: MAX_X, MIN_Y, MAX_Z
        (1.0, 1.0, 1.0),  # 3: MAX_X, MAX_Y, MAX_Z
    ],
    "west": [
        (0.0, 1.0, 0.0),  # 0: MIN_X, MAX_Y, MIN_Z
        (0.0, 0.0, 0.0),  # 1: MIN_X, MIN_Y, MIN_Z
        (0.0, 0.0, 1.0),  # 2: MIN_X, MIN_Y, MAX_Z
        (0.0, 1.0, 1.0),  # 3: MIN_X, MAX_Y, MAX_Z
    ],
    "east": [
        (1.0, 1.0, 1.0),  # 0: MAX_X, MAX_Y, MAX_Z
        (1.0, 0.0, 1.0),  # 1: MAX_X, MIN_Y, MAX_Z
        (1.0, 0.0, 0.0),  # 2: MAX_X, MIN_Y, MIN_Z
        (1.0, 1.0, 0.0),  # 3: MAX_X, MAX_Y, MIN_Z
    ]
}


def round_vec3(v: Vec3) -> tuple[int, int, int]:
    return (int(round(v[0])), int(round(v[1])), int(round(v[2])))


def get_face_canonical_vertex(facing: str, from_pos: Vec3, to_pos: Vec3, index: int) -> Vec3:
    """Returns the 3D position of vertex index (0..3) in [0..1] space matching FaceInfo.select."""
    fx, fy, fz = from_pos[0] / 16.0, from_pos[1] / 16.0, from_pos[2] / 16.0
    tx, ty, tz = to_pos[0] / 16.0, to_pos[1] / 16.0, to_pos[2] / 16.0

    if facing == "down":
        extents = [(fx, fy, tz), (fx, fy, fz), (tx, fy, fz), (tx, fy, tz)]
    elif facing == "up":
        extents = [(fx, ty, fz), (fx, ty, tz), (tx, ty, tz), (tx, ty, fz)]
    elif facing == "north":
        extents = [(tx, ty, fz), (tx, fy, fz), (fx, fy, fz), (fx, ty, fz)]
    elif facing == "south":
        extents = [(fx, ty, tz), (fx, fy, tz), (tx, fy, tz), (tx, ty, tz)]
    elif facing == "west":
        extents = [(fx, ty, fz), (fx, fy, fz), (fx, fy, tz), (fx, ty, tz)]
    elif facing == "east":
        extents = [(tx, ty, tz), (tx, fy, tz), (tx, fy, fz), (tx, ty, fz)]
    else:
        extents = [(fx, fy, fz), (tx, fy, fz), (tx, ty, fz), (fx, ty, fz)]
    return extents[index]


def default_face_uv(facing: str, from_pos: Vec3, to_pos: Vec3) -> Tuple[float, float, float, float]:
    """Calculate default (minU, minV, maxU, maxV) in [0..16] matching FaceBakery.defaultFaceUV."""
    fx, fy, fz = from_pos
    tx, ty, tz = to_pos
    if facing == "down":
        return (fx, 16.0 - tz, tx, 16.0 - fz)
    elif facing == "up":
        return (fx, fz, tx, tz)
    elif facing == "north":
        return (16.0 - tx, 16.0 - ty, 16.0 - fx, 16.0 - fy)
    elif facing == "south":
        return (fx, 16.0 - ty, tx, 16.0 - fy)
    elif facing == "west":
        return (fz, 16.0 - ty, tz, 16.0 - fy)
    elif facing == "east":
        return (16.0 - tz, 16.0 - ty, 16.0 - fz, 16.0 - fy)
    return (0.0, 0.0, 16.0, 16.0)


def cuboid_face_get_u(uvs: Tuple[float, float, float, float], rot_shift: int, vertex: int, uv_base: float = 16.0) -> float:
    min_u, min_v, max_u, max_v = uvs
    idx = (vertex + rot_shift) % 4
    base = float(uv_base) if uv_base > 0.0 else 16.0
    return (max_u if (idx != 0 and idx != 1) else min_u) / base


def cuboid_face_get_v(uvs: Tuple[float, float, float, float], rot_shift: int, vertex: int, uv_base: float = 16.0) -> float:
    min_u, min_v, max_u, max_v = uvs
    idx = (vertex + rot_shift) % 4
    base = float(uv_base) if uv_base > 0.0 else 16.0
    return (max_v if (idx != 0 and idx != 3) else min_v) / base


# 3D Matrix & Rotation Math
def rotate_x(v: Vec3, deg: float) -> Vec3:
    rad = -math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    x, y, z = v
    return (x, y * c - z * s, y * s + z * c)


def rotate_y(v: Vec3, deg: float) -> Vec3:
    rad = -math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    x, y, z = v
    return (x * c + z * s, y, -x * s + z * c)


def rotate_z(v: Vec3, deg: float) -> Vec3:
    rad = -math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    x, y, z = v
    return (x * c - y * s, x * s + y * c, z)


def rotate_point(p: Vec3, rot_x: float, rot_y: float, origin: Vec3 = (0.5, 0.5, 0.5)) -> Vec3:
    """Apply BlockModelRotation (X rotation first, then Y rotation around origin)."""
    px = p[0] - origin[0]
    py = p[1] - origin[1]
    pz = p[2] - origin[2]

    v = rotate_x((px, py, pz), rot_x)
    v = rotate_y(v, rot_y)

    return (v[0] + origin[0], v[1] + origin[1], v[2] + origin[2])


def rotate_element_point(p: Vec3, rotation_dict: Optional[dict]) -> Vec3:
    """Apply local element rotation (axis, origin [0..16], angle, rescale).
    Matches Minecraft BlockElementRotation right-hand rule transformations.
    """
    if not rotation_dict:
        return p

    origin_raw = rotation_dict.get("origin", [8.0, 8.0, 8.0])
    origin = (origin_raw[0] / 16.0, origin_raw[1] / 16.0, origin_raw[2] / 16.0)
    axis = rotation_dict.get("axis", "y").lower()
    angle = float(rotation_dict.get("angle", 0.0))
    rescale = bool(rotation_dict.get("rescale", False))

    px = p[0] - origin[0]
    py = p[1] - origin[1]
    pz = p[2] - origin[2]

    rad = math.radians(angle)
    c, s = math.cos(rad), math.sin(rad)

    if axis == "x":
        v = (px, py * c - pz * s, py * s + pz * c)
    elif axis == "y":
        v = (px * c + pz * s, py, -px * s + pz * c)
    elif axis == "z":
        v = (px * c - py * s, px * s + py * c, pz)
    else:
        v = (px, py, pz)

    if rescale and abs(angle) in (22.5, 45.0, 67.5):
        scale = 1.0 / math.cos(rad)
        if axis == "x":
            v = (v[0], v[1] * scale, v[2] * scale)
        elif axis == "y":
            v = (v[0] * scale, v[1], v[2] * scale)
        elif axis == "z":
            v = (v[0] * scale, v[1] * scale, v[2])

    return (v[0] + origin[0], v[1] + origin[1], v[2] + origin[2])


def rotate_direction(direction: str, rot_x: float, rot_y: float) -> str:
    """Rotate a face normal string by (rot_x, rot_y)."""
    if direction not in DIR_VECTORS:
        return direction
    norm = DIR_VECTORS[direction]
    v = rotate_x(norm, rot_x)
    v = rotate_y(v, rot_y)
    rounded = round_vec3(v)
    return VECTOR_TO_DIR.get(rounded, direction)


def calculate_facing(positions: List[Vec3]) -> str:
    """Calculate the closest Minecraft face direction from 4 quad vertex positions."""
    p0, p1, p2, _ = positions
    v1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
    v2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
    nx = v1[1] * v2[2] - v1[2] * v2[1]
    ny = v1[2] * v2[0] - v1[0] * v2[2]
    nz = v1[0] * v2[1] - v1[1] * v2[0]

    best_dir = "up"
    best_dot = -999.0
    for dname, dvec in DIR_VECTORS.items():
        dot = nx * dvec[0] + ny * dvec[1] + nz * dvec[2]
        if dot > best_dot:
            best_dot = dot
            best_dir = dname
    return best_dir


def recalculate_winding(positions: List[Vec3], uvs: List[Vec2], final_dir: str) -> None:
    """
    Exact implementation of Minecraft FaceBakery.recalculateWinding:
    Reorders positions and uvs so vertices match FaceInfo.fromFacing(final_dir) canonical order.
    """
    min_x = min(p[0] for p in positions)
    min_y = min(p[1] for p in positions)
    min_z = min(p[2] for p in positions)
    max_x = max(p[0] for p in positions)
    max_y = max(p[1] for p in positions)
    max_z = max(p[2] for p in positions)

    from_pos = (min_x * 16.0, min_y * 16.0, min_z * 16.0)
    to_pos = (max_x * 16.0, max_y * 16.0, max_z * 16.0)

    for vertex in range(4):
        target_pos = get_face_canonical_vertex(final_dir, from_pos, to_pos, vertex)
        match_idx = -1
        for i in range(vertex, 4):
            p = positions[i]
            if (abs(p[0] - target_pos[0]) < 1e-4 and
                abs(p[1] - target_pos[1]) < 1e-4 and
                abs(p[2] - target_pos[2]) < 1e-4):
                match_idx = i
                break
        if match_idx != -1 and match_idx != vertex:
            positions[vertex], positions[match_idx] = positions[match_idx], positions[vertex]
            uvs[vertex], uvs[match_idx] = uvs[match_idx], uvs[vertex]


# Matrix transformations for BlockMath UVLock
def _mat3_mul(a: Mat3, b: Mat3) -> Mat3:
    return tuple(
        tuple(sum(a[r][k] * b[k][c] for k in range(3)) for c in range(3))
        for r in range(3)
    )  # type: ignore


def _mat3_transform(m: Mat3, v: Vec3) -> Vec3:
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def _mat3_rot_x(rad: float) -> Mat3:
    c, s = math.cos(rad), math.sin(rad)
    return (
        (1.0, 0.0, 0.0),
        (0.0, c, -s),
        (0.0, s, c),
    )


def _mat3_rot_y(rad: float) -> Mat3:
    c, s = math.cos(rad), math.sin(rad)
    return (
        (c, 0.0, s),
        (0.0, 1.0, 0.0),
        (-s, 0.0, c),
    )


def _mat3_inverse(m: Mat3) -> Mat3:
    return (
        (m[0][0], m[1][0], m[2][0]),
        (m[0][1], m[1][1], m[2][1]),
        (m[0][2], m[1][2], m[2][2]),
    )


# Local to global face transforms from BlockMath.java
VANILLA_UV_TRANSFORM_LOCAL_TO_GLOBAL: dict[str, Mat3] = {
    "south": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "east": _mat3_rot_y(math.pi / 2.0),
    "west": _mat3_rot_y(-math.pi / 2.0),
    "north": _mat3_rot_y(math.pi),
    "up": _mat3_rot_x(-math.pi / 2.0),
    "down": _mat3_rot_x(math.pi / 2.0),
}

VANILLA_UV_TRANSFORM_GLOBAL_TO_LOCAL: dict[str, Mat3] = {
    k: _mat3_inverse(v) for k, v in VANILLA_UV_TRANSFORM_LOCAL_TO_GLOBAL.items()
}


def get_face_uvlock_transform(rot_x: float, rot_y: float, original_side: str) -> Mat3:
    """Compute exact BlockMath.getFaceTransformation inverse for UVLock."""
    mx = _mat3_rot_x(-math.radians(rot_x))
    my = _mat3_rot_y(-math.radians(rot_y))
    model_rot = _mat3_mul(my, mx)

    local_to_global = VANILLA_UV_TRANSFORM_LOCAL_TO_GLOBAL.get(original_side, ((1,0,0),(0,1,0),(0,0,1)))
    face_action = _mat3_mul(model_rot, local_to_global)

    transformed_normal = _mat3_transform(face_action, (0.0, 0.0, 1.0))
    rounded = round_vec3(transformed_normal)
    new_side = VECTOR_TO_DIR.get(rounded, "south")

    global_to_local = VANILLA_UV_TRANSFORM_GLOBAL_TO_LOCAL.get(new_side, ((1,0,0),(0,1,0),(0,0,1)))
    face_transform = _mat3_mul(global_to_local, face_action)

    return _mat3_inverse(face_transform)


def apply_uvlock_to_uvs(
    uvs: list[Vec2],
    orig_direction: str,
    rot_x: float,
    rot_y: float
) -> list[Vec2]:
    """Apply exact UVLock counter-rotation to UV coordinates."""
    if rot_x == 0.0 and rot_y == 0.0:
        return list(uvs)

    inv_uv_transform = get_face_uvlock_transform(rot_x, rot_y, orig_direction)
    new_uvs = []
    for u, v in uvs:
        cu, cv = u - 0.5, v - 0.5
        tu, tv, _ = _mat3_transform(inv_uv_transform, (cu, cv, 0.0))
        new_uvs.append((tu + 0.5, tv + 0.5))
    return new_uvs


def bake_face_exact(
    orig_dir: str,
    from_pos: Vec3,
    to_pos: Vec3,
    uv_bounds: Optional[Tuple[float, float, float, float]],
    face_rotation_deg: float,
    rot_x: float = 0.0,
    rot_y: float = 0.0,
    elem_rotation: Optional[dict] = None,
    uvlock: bool = False,
    uv_base: float = 16.0,
) -> Tuple[str, float, List[Vec3], List[Vec2], Tuple[float, float, float, float]]:
    """
    Exact FaceBakery.bakeQuad pipeline:
    Calculates final face direction, accurate 3D vertex positions, loop UVs,
    and effective 6-face summary UV rotation (0/90/180/270).
    """
    if uv_bounds is None:
        uv_bounds = default_face_uv(orig_dir, from_pos, to_pos)

    rot_shift = int(round(face_rotation_deg / 90.0)) % 4

    # 1. Raw canonical vertices and UVs
    raw_positions = [get_face_canonical_vertex(orig_dir, from_pos, to_pos, i) for i in range(4)]
    raw_uvs = [(cuboid_face_get_u(uv_bounds, rot_shift, i, uv_base=uv_base), cuboid_face_get_v(uv_bounds, rot_shift, i, uv_base=uv_base)) for i in range(4)]

    # 2. Transform 3D vertices (local element rotation first, then model variant rotation)
    transformed_positions = []
    for p in raw_positions:
        p_elem = rotate_element_point(p, elem_rotation) if elem_rotation else p
        p_world = rotate_point(p_elem, rot_x, rot_y)
        transformed_positions.append(p_world)

    # 3. Apply UVLock if active
    if uvlock and (rot_x != 0.0 or rot_y != 0.0):
        transformed_uvs = apply_uvlock_to_uvs(raw_uvs, orig_dir, rot_x, rot_y)
    else:
        transformed_uvs = list(raw_uvs)

    # 4. Final direction
    final_dir = calculate_facing(transformed_positions)

    # 5. Recalculate winding for canonical face order
    if elem_rotation is None:
        recalculate_winding(transformed_positions, transformed_uvs, final_dir)

    # 6. Extract canonical uv_rot & uv_bounds
    u0, v0 = transformed_uvs[0]
    u1, v1 = transformed_uvs[1]
    u2, v2 = transformed_uvs[2]
    u3, v3 = transformed_uvs[3]

    min_u = min(u0, u1, u2, u3)
    max_u = max(u0, u1, u2, u3)
    min_v = min(v0, v1, v2, v3)
    max_v = max(v0, v1, v2, v3)

    # In canonical FaceInfo order: 0: Top-Left, 1: Bottom-Left, 2: Bottom-Right, 3: Top-Right
    # Gradient of V_file along U_local (horizontal) and V_local (vertical):
    dv_du = (v3 + v2) - (v0 + v1)
    dv_dv = (v0 + v3) - (v1 + v2)

    dir_x = -dv_du  # Positive if Top of texture points towards Right (+U_local)
    dir_y = -dv_dv  # Positive if Top of texture points towards Top (+V_local)

    if abs(dir_x) < 1e-4 and abs(dir_y) < 1e-4:
        du_du = (u3 + u2) - (u0 + u1)
        du_dv = (u0 + u3) - (u1 + u2)
        dir_x = du_du
        dir_y = du_dv
        angle_rad = math.atan2(dir_y, dir_x)
        deg = -math.degrees(angle_rad)
        detected_rot = (round(deg / 90.0) * 90.0) % 360.0
    else:
        angle_rad = math.atan2(dir_x, dir_y)
        deg = math.degrees(angle_rad)
        detected_rot = (round(deg / 90.0) * 90.0) % 360.0

    return final_dir, detected_rot, transformed_positions, transformed_uvs, (min_u, min_v, max_u, max_v)


def get_face_raw_vertices(direction: str, from_pos: Vec3, to_pos: Vec3) -> list[Vec3]:
    """Returns the 4 canonical vertices in [0..1] space."""
    return [get_face_canonical_vertex(direction, from_pos, to_pos, i) for i in range(4)]


def get_face_loop_uvs(uv_bounds: tuple[float, float, float, float], rotation_deg: float = 0.0) -> list[Vec2]:
    rot_shift = int(round(rotation_deg / 90.0)) % 4
    return [(cuboid_face_get_u(uv_bounds, rot_shift, i), cuboid_face_get_v(uv_bounds, rot_shift, i)) for i in range(4)]


def calculate_uv_rotation(
    orig_direction: str,
    new_direction: str,
    face_rotation: float = 0.0,
    rot_x: float = 0.0,
    rot_y: float = 0.0,
    uvlock: bool = False
) -> float:
    """Wrapper that computes exact UV rotation via bake_face_exact."""
    _, detected_rot, _, _, _ = bake_face_exact(
        orig_dir=orig_direction,
        from_pos=(0, 0, 0),
        to_pos=(16, 16, 16),
        uv_bounds=(0, 0, 16, 16),
        face_rotation_deg=face_rotation,
        rot_x=rot_x,
        rot_y=rot_y,
        uvlock=uvlock,
    )
    return detected_rot

"""
Mathematical utilities for 3D transformation, Quad baking, and UV calculations
based directly on Minecraft official FaceBakery / FaceInfo bytecode.
"""

from __future__ import annotations
import math
from typing import Tuple, List, Optional

Vec3 = Tuple[float, float, float]
Vec2 = Tuple[float, float]

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


def round_vec3(v: Vec3) -> tuple[int, int, int]:
    return (int(round(v[0])), int(round(v[1])), int(round(v[2])))


def rotate_x(v: Vec3, angle_deg: float) -> Vec3:
    rad = math.radians(-angle_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    x, y, z = v
    return (
        x,
        y * cos_a - z * sin_a,
        y * sin_a + z * cos_a,
    )


def rotate_y(v: Vec3, angle_deg: float) -> Vec3:
    rad = math.radians(-angle_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    x, y, z = v
    return (
        x * cos_a + z * sin_a,
        y,
        -x * sin_a + z * cos_a,
    )


def rotate_z(v: Vec3, angle_deg: float) -> Vec3:
    rad = math.radians(-angle_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    x, y, z = v
    return (
        x * cos_a - y * sin_a,
        x * sin_a + y * cos_a,
        z,
    )


def rotate_point(p: Vec3, rot_x: float, rot_y: float, origin: Vec3 = (0.5, 0.5, 0.5)) -> Vec3:
    """Apply BlockModelRotation (Y then X rotation around origin)."""
    px = p[0] - origin[0]
    py = p[1] - origin[1]
    pz = p[2] - origin[2]

    v = rotate_y((px, py, pz), rot_y)
    v = rotate_x(v, rot_x)

    return (v[0] + origin[0], v[1] + origin[1], v[2] + origin[2])


def rotate_element_point(p: Vec3, rotation_dict: Optional[dict]) -> Vec3:
    """Apply local element rotation (axis, origin [0..16], angle, rescale)."""
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

    if axis == "x":
        v = rotate_x((px, py, pz), angle)
    elif axis == "y":
        v = rotate_y((px, py, pz), angle)
    elif axis == "z":
        v = rotate_z((px, py, pz), angle)
    else:
        v = (px, py, pz)

    if rescale and abs(angle) in (22.5, 45.0, 67.5):
        scale = 1.0 / math.cos(math.radians(angle))
        if axis == "x":
            v = (v[0], v[1] * scale, v[2] * scale)
        elif axis == "y":
            v = (v[0] * scale, v[1], v[2] * scale)
        elif axis == "z":
            v = (v[0] * scale, v[1] * scale, v[2])

    return (v[0] + origin[0], v[1] + origin[1], v[2] + origin[2])


def rotate_direction(direction: str, rot_x: float, rot_y: float) -> str:
    if direction not in DIR_VECTORS:
        return direction
    norm = DIR_VECTORS[direction]
    v = rotate_y(norm, rot_y)
    v = rotate_x(v, rot_x)
    rounded = round_vec3(v)
    return VECTOR_TO_DIR.get(rounded, direction)


def default_face_uv(direction: str, from_pos: Vec3, to_pos: Vec3) -> tuple[float, float, float, float]:
    """
    Calculate default (minU, minV, maxU, maxV) in [0..16] space
    directly matching FaceBakery.defaultFaceUV.
    """
    fx, fy, fz = from_pos
    tx, ty, tz = to_pos

    if direction == "down":
        return (fx, 16.0 - tz, tx, 16.0 - fz)
    elif direction == "up":
        return (fx, fz, tx, tz)
    elif direction == "north":
        return (16.0 - tx, 16.0 - ty, 16.0 - fx, 16.0 - fy)
    elif direction == "south":
        return (fx, 16.0 - ty, tx, 16.0 - fy)
    elif direction == "west":
        return (fz, 16.0 - ty, tz, 16.0 - fy)
    elif direction == "east":
        return (16.0 - tz, 16.0 - ty, 16.0 - fz, 16.0 - fy)
    return (0.0, 0.0, 16.0, 16.0)


def get_face_raw_vertices(direction: str, from_pos: Vec3, to_pos: Vec3) -> list[Vec3]:
    """
    Returns the 4 quad vertices (0..3) in Minecraft [0..1] space
    directly matching FaceInfo vertex selection tables.
    """
    fx, fy, fz = from_pos[0] / 16.0, from_pos[1] / 16.0, from_pos[2] / 16.0
    tx, ty, tz = to_pos[0] / 16.0, to_pos[1] / 16.0, to_pos[2] / 16.0

    if direction == "down":
        return [(fx, fy, tz), (fx, fy, fz), (tx, fy, fz), (tx, fy, tz)]
    elif direction == "up":
        return [(fx, ty, fz), (fx, ty, tz), (tx, ty, tz), (tx, ty, fz)]
    elif direction == "north":
        return [(tx, ty, fz), (tx, fy, fz), (fx, fy, fz), (fx, ty, fz)]
    elif direction == "south":
        return [(fx, ty, tz), (fx, fy, tz), (tx, fy, tz), (tx, ty, tz)]
    elif direction == "west":
        return [(fx, ty, fz), (fx, fy, fz), (fx, fy, tz), (fx, ty, tz)]
    elif direction == "east":
        return [(tx, ty, tz), (tx, fy, tz), (tx, fy, fz), (tx, ty, fz)]
    return []


def get_face_loop_uvs(uv_bounds: tuple[float, float, float, float], rotation_deg: float = 0.0) -> list[Vec2]:
    """
    Calculate the 4 loop UV coordinates [0..1] matching CuboidFace.getU/getV.
    uv_bounds: (minU, minV, maxU, maxV) in [0..16].
    """
    min_u, min_v, max_u, max_v = (
        uv_bounds[0] / 16.0,
        uv_bounds[1] / 16.0,
        uv_bounds[2] / 16.0,
        uv_bounds[3] / 16.0,
    )

    quadrant = int(round(rotation_deg / 90.0)) % 4

    corners = [
        (min_u, min_v),  # v=0
        (min_u, max_v),  # v=1
        (max_u, max_v),  # v=2
        (max_u, min_v),  # v=3
    ]

    return [corners[(v + quadrant) % 4] for v in range(4)]


def apply_uvlock_to_uvs(
    uvs: list[Vec2],
    orig_direction: str,
    rot_x: float,
    rot_y: float
) -> list[Vec2]:
    """
    Apply UVLock counter-rotation to the 4 loop UVs.
    """
    if rot_x == 0.0 and rot_y == 0.0:
        return uvs

    # Project on face plane: calculate UV rotation angle needed
    # When uvlock is active, determine effective angle to rotate around center (0.5, 0.5)
    rot_angle = 0.0
    if orig_direction in ("up", "down"):
        if orig_direction == "up":
            rot_angle = -rot_y
        else:
            rot_angle = rot_y
    elif rot_x != 0.0 and orig_direction in ("east", "west"):
        rot_angle = -rot_x if orig_direction == "east" else rot_x

    if abs(rot_angle % 360.0) < 1e-4:
        return uvs

    rad = math.radians(rot_angle)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)

    new_uvs = []
    for u, v in uvs:
        uc = u - 0.5
        vc = v - 0.5
        ur = uc * cos_a - vc * sin_a
        vr = uc * sin_a + vc * cos_a
        new_uvs.append((ur + 0.5, vr + 0.5))

    return new_uvs


def calculate_uv_rotation(
    orig_direction: str,
    new_direction: str,
    face_rotation: float = 0.0,
    rot_x: float = 0.0,
    rot_y: float = 0.0,
    uvlock: bool = False
) -> float:
    base_rot = face_rotation % 360.0

    if not uvlock:
        if orig_direction == "up":
            return (base_rot + rot_y) % 360.0
        elif orig_direction == "down":
            return (base_rot - rot_y) % 360.0

        if orig_direction in ("east", "west") and rot_x != 0.0:
            if orig_direction == "east":
                return (base_rot + rot_x) % 360.0
            else:
                return (base_rot - rot_x) % 360.0

        if rot_x == 90.0:
            if orig_direction == "north" and new_direction == "up":
                return (base_rot + 180.0) % 360.0
            elif orig_direction == "south" and new_direction == "down":
                return (base_rot + 0.0) % 360.0

        return base_rot

    return base_rot

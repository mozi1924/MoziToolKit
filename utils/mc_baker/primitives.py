"""
Procedural Geometry Builders & Utilities for Minecraft BakedModel instances.
Provides clean, reusable builders for cuboids, planes, and directional rotations
without raw manual coordinate boilerplate.
"""

from __future__ import annotations
import math
from typing import Optional, Tuple, Dict, Sequence, Union, Any

from .types import BakedModel, BakedElement, BakedFace, MC_DIRECTIONS

Vec3 = Tuple[float, float, float]
Vec2 = Tuple[float, float]
Rect2D = Tuple[float, float, float, float]  # (u0, v0, u1, v1)


# ---------------------------------------------------------------------------
# Rotation Utilities
# ---------------------------------------------------------------------------

def rotate_y_point(v: Vec3, deg: float) -> Vec3:
    """
    Rotate a point (x, y, z) around origin (0, 0, 0) by deg degrees matching jmc2obj Transform.rotation(0, deg, 0).
    Formula: x' = x*cos(b) - z*sin(b), z' = x*sin(b) + z*cos(b).
    """
    if deg == 0.0:
        return v
    rad = math.radians(deg)
    c = math.cos(rad)
    s = math.sin(rad)
    x, y, z = v
    nx = x * c - z * s
    nz = x * s + z * c
    return (nx, y, nz)


def rotate_point_by_facing(v: Vec3, facing: str) -> Vec3:
    """
    Rotate a vertex around block center (0, 0, 0) for the 6 standard Minecraft Shulker/Box facings.
    """
    x, y, z = v
    f = facing.lower()
    if f == "up":
        return (x, y, z)
    elif f == "down":
        return (x, -y, -z)
    elif f == "north":
        return (x, z, -y)
    elif f == "south":
        return (x, -z, y)
    elif f == "west":
        return (-y, x, z)
    elif f == "east":
        return (y, -x, z)
    return (x, y, z)


def get_entity_facing_angle_y(facing: str) -> float:
    """
    Return Y-rotation angle in degrees for entity models whose unrotated front is South (+Z).
    South: 0, North: 180, East: 270 (-90), West: 90.
    """
    facing_map = {
        "south": 0.0,
        "north": 180.0,
        "east": 270.0,
        "west": 90.0,
    }
    return facing_map.get(facing.lower(), 0.0)


def get_block_facing_angle_y(facing: str) -> float:
    """
    Return Y-rotation angle in degrees for block models whose unrotated front is North (-Z).
    North: 0, East: 90, South: 180, West: 270.
    """
    facing_map = {
        "north": 0.0,
        "east": 90.0,
        "south": 180.0,
        "west": 270.0,
    }
    return facing_map.get(facing.lower(), 0.0)


def calculate_normal(p0: Vec3, p1: Vec3, p2: Vec3) -> Vec3:
    """Calculate normalized face normal from 3 vertices."""
    v1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
    v2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
    nx = v1[1] * v2[2] - v1[2] * v2[1]
    ny = v1[2] * v2[0] - v1[0] * v2[2]
    nz = v1[0] * v2[1] - v1[1] * v2[0]
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length > 1e-6:
        return (nx / length, ny / length, nz / length)
    return (0.0, 1.0, 0.0)


def normal_to_mc_direction(normal: Vec3) -> str:
    """Map a 3D normal vector to the closest standard Minecraft face direction name."""
    nx, ny, nz = normal
    abs_x, abs_y, abs_z = abs(nx), abs(ny), abs(nz)
    if abs_y >= abs_x and abs_y >= abs_z:
        return "up" if ny > 0 else "down"
    elif abs_x >= abs_z:
        return "east" if nx > 0 else "west"
    else:
        return "south" if nz > 0 else "north"


# ---------------------------------------------------------------------------
# Procedural Box & Cuboid Builders
# ---------------------------------------------------------------------------

def compute_box_face_uvs(
    u_origin: float,
    v_origin: float,
    dx: float,
    dy: float,
    dz: float,
    tex_w: float = 64.0,
    tex_h: float = 64.0,
) -> Dict[str, Tuple[Vec2, Vec2, Vec2, Vec2]]:
    """
    Compute standard Minecraft entity box UV quad mappings conforming to FaceBakery.
    Layout starting from (u_origin, v_origin):
      - up:    SW (u+dz, v+dz), SE (u+dz+dx, v+dz), NE (u+dz+dx, v), NW (u+dz, v)
      - down:  NW (u+dz+dx, v), NE (u+dz+2*dx, v), SE (u+dz+2*dx, v+dz), SW (u+dz+dx, v+dz)
      - north: BR (u+dz+dx, v+dz+dy), BL (u+dz, v+dz+dy), TL (u+dz, v+dz), TR (u+dz+dx, v+dz)
      - south: BL (u+2*dz+dx, v+dz+dy), BR (u+2*(dz+dx), v+dz+dy), TR (u+2*(dz+dx), v+dz), TL (u+2*dz+dx, v+dz)
      - west:  BL (u, v+dz+dy), BR (u+dz, v+dz+dy), TR (u+dz, v+dz), TL (u, v+dz)
      - east:  BL (u+dz, v+dz+dy), BR (u+2*dz, v+dz+dy), TR (u+2*dz, v+dz), TL (u+dz, v+dz)
    """
    def norm(u: float, v: float) -> Vec2:
        return (u / tex_w, v / tex_h)

    u0, v0 = u_origin, v_origin
    return {
        "up": (
            norm(u0 + dz, v0 + dz),
            norm(u0 + dz + dx, v0 + dz),
            norm(u0 + dz + dx, v0),
            norm(u0 + dz, v0),
        ),
        "down": (
            norm(u0 + dz + dx, v0),
            norm(u0 + dz + 2 * dx, v0),
            norm(u0 + dz + 2 * dx, v0 + dz),
            norm(u0 + dz + dx, v0 + dz),
        ),
        "north": (
            norm(u0 + dz + dx, v0 + dz + dy),
            norm(u0 + dz, v0 + dz + dy),
            norm(u0 + dz, v0 + dz),
            norm(u0 + dz + dx, v0 + dz),
        ),
        "south": (
            norm(u0 + 2 * dz + dx, v0 + dz + dy),
            norm(u0 + 2 * (dz + dx), v0 + dz + dy),
            norm(u0 + 2 * (dz + dx), v0 + dz),
            norm(u0 + 2 * dz + dx, v0 + dz),
        ),
        "west": (
            norm(u0, v0 + dz + dy),
            norm(u0 + dz, v0 + dz + dy),
            norm(u0 + dz, v0 + dz),
            norm(u0, v0 + dz),
        ),
        "east": (
            norm(u0 + dz + dx, v0 + dz + dy),
            norm(u0 + 2 * dz + dx, v0 + dz + dy),
            norm(u0 + 2 * dz + dx, v0 + dz),
            norm(u0 + dz + dx, v0 + dz),
        ),
    }


def build_cuboid_element(
    bounds_min: Vec3,
    bounds_max: Vec3,
    texture: str,
    uvs_by_face: Optional[Dict[str, Sequence[Vec2]]] = None,
    rot_facing: Optional[str] = None,
    rot_y: float = 0.0,
    tint_index: int = -1,
) -> Tuple[BakedElement, list[BakedFace]]:
    """
    Construct a canonical 6-faced BakedElement for a cuboid defined in centered local coordinates [-0.5, 0.5].
    """
    x0, y0, z0 = bounds_min
    x1, y1, z1 = bounds_max

    raw_face_vertices = {
        "up": [(-0.5 + (x0+0.5), y1, z1), (-0.5 + (x1+0.5), y1, z1), (-0.5 + (x1+0.5), y1, z0), (-0.5 + (x0+0.5), y1, z0)],
        "down": [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
        "north": [(x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0)],
        "south": [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
        "west": [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)],
        "east": [(x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1)],
    }

    elem_faces: Dict[str, BakedFace] = {}
    faces_list: list[BakedFace] = []

    for d, verts in raw_face_vertices.items():
        transformed: list[Vec3] = []
        for v in verts:
            vt = v
            if rot_facing:
                vt = rotate_point_by_facing(vt, rot_facing)
            if rot_y != 0.0:
                vt = rotate_y_point(vt, rot_y)
            transformed.append((vt[0] + 0.5, vt[1] + 0.5, vt[2] + 0.5))

        norm = calculate_normal(transformed[0], transformed[1], transformed[2])
        calc_dir = normal_to_mc_direction(norm)

        face_uvs = tuple(uvs_by_face[d]) if uvs_by_face and d in uvs_by_face else (
            (0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)
        )
        min_u = min(u for u, _ in face_uvs)
        max_u = max(u for u, _ in face_uvs)
        min_v = min(v for _, v in face_uvs)
        max_v = max(v for _, v in face_uvs)

        bf = BakedFace(
            direction=calc_dir,
            texture=texture,
            uv_bounds=(min_u, min_v, max_u, max_v),
            vertices=tuple(transformed),
            uvs=face_uvs,
            tint_index=tint_index,
        )
        elem_faces[calc_dir] = bf
        faces_list.append(bf)

    xs = [v[0] for f in elem_faces.values() for v in f.vertices]
    ys = [v[1] for f in elem_faces.values() for v in f.vertices]
    zs = [v[2] for f in elem_faces.values() for v in f.vertices]
    elem = BakedElement(
        from_pos=(min(xs) * 16.0, min(ys) * 16.0, min(zs) * 16.0),
        to_pos=(max(xs) * 16.0, max(ys) * 16.0, max(zs) * 16.0),
        faces=elem_faces,
    )
    return elem, faces_list


def build_plane_element(
    v0: Vec3,
    v1: Vec3,
    v2: Vec3,
    v3: Vec3,
    texture: str,
    uvs: Tuple[Vec2, Vec2, Vec2, Vec2] = ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)),
    double_sided: bool = True,
) -> Tuple[BakedElement, list[BakedFace]]:
    """Construct a planar quad element with optional double-sided faces."""
    norm = calculate_normal(v0, v1, v2)
    dir_front = normal_to_mc_direction(norm)

    min_u = min(u for u, _ in uvs)
    max_u = max(u for u, _ in uvs)
    min_v = min(v for _, v in uvs)
    max_v = max(v for _, v in uvs)

    bf_front = BakedFace(
        direction=dir_front,
        texture=texture,
        uv_bounds=(min_u, min_v, max_u, max_v),
        vertices=(v0, v1, v2, v3),
        uvs=uvs,
    )
    faces_dict = {dir_front: bf_front}
    faces_list = [bf_front]

    if double_sided:
        opp_norm = (-norm[0], -norm[1], -norm[2])
        dir_back = normal_to_mc_direction(opp_norm)
        rev_v = (v1, v0, v3, v2)
        rev_uvs = (uvs[1], uvs[0], uvs[3], uvs[2])
        bf_back = BakedFace(
            direction=dir_back,
            texture=texture,
            uv_bounds=(min_u, min_v, max_u, max_v),
            vertices=rev_v,
            uvs=rev_uvs,
        )
        faces_dict[dir_back] = bf_back
        faces_list.append(bf_back)

    xs = [v[0] for v in (v0, v1, v2, v3)]
    ys = [v[1] for v in (v0, v1, v2, v3)]
    zs = [v[2] for v in (v0, v1, v2, v3)]
    elem = BakedElement(
        from_pos=(min(xs) * 16.0, min(ys) * 16.0, min(zs) * 16.0),
        to_pos=(max(xs) * 16.0, max(ys) * 16.0, max(zs) * 16.0),
        faces=faces_dict,
    )
    return elem, faces_list

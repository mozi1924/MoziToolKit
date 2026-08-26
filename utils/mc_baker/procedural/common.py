"""
Common utility functions for procedural Minecraft model generation.
Implements ModelPart-accurate box UV unwrapping and orientation transformations.
"""

from __future__ import annotations
from typing import Optional, Any


def make_box_element(
    from_pos: tuple[float, float, float] | list[float],
    to_pos: tuple[float, float, float] | list[float],
    tex_u: float,
    tex_v: float,
    tex_name: str,
    tex_size: float = 64.0,
    elem_rot: Optional[dict[str, Any]] = None,
    tintindex: int = -1,
    cullface_map: Optional[dict[str, str]] = None,
    custom_faces: Optional[dict[str, dict]] = None,
    omitted_faces: Optional[list[str]] = None,
) -> dict:
    """
    Construct a canonical 6-face Minecraft element dict from box coordinates
    and ModelPart texture offset (u, v) using official Java UV unwrapping logic.
    """
    dx = float(to_pos[0] - from_pos[0])
    dy = float(to_pos[1] - from_pos[1])
    dz = float(to_pos[2] - from_pos[2])

    cull = cullface_map or {}

    # Official Minecraft Java ModelPart$Cube face unwrapping:
    # Up:    [u + dz,      v,           u + dz + dx,      v + dz]
    # Down:  [u + dz + dx, v,           u + dz + 2*dx,    v + dz]
    # West:  [u,           v + dz,      u + dz,           v + dz + dy]
    # North: [u + dz,      v + dz,      u + dz + dx,      v + dz + dy]
    # East:  [u + dz + dx, v + dz,      u + 2*dz + dx,    v + dz + dy]
    # South: [u + 2*dz+dx, v + dz,      u + 2*dz + 2*dx,  v + dz + dy]
    faces = {
        "up": {
            "texture": tex_name,
            "uv": [tex_u + dz, tex_v, tex_u + dz + dx, tex_v + dz],
            "uv_size": tex_size,
            "tintindex": tintindex,
        },
        "down": {
            "texture": tex_name,
            "uv": [tex_u + dz + dx, tex_v, tex_u + dz + 2 * dx, tex_v + dz],
            "uv_size": tex_size,
            "tintindex": tintindex,
        },
        "west": {
            "texture": tex_name,
            "uv": [tex_u, tex_v + dz, tex_u + dz, tex_v + dz + dy],
            "uv_size": tex_size,
            "tintindex": tintindex,
        },
        "north": {
            "texture": tex_name,
            "uv": [tex_u + dz, tex_v + dz, tex_u + dz + dx, tex_v + dz + dy],
            "uv_size": tex_size,
            "tintindex": tintindex,
        },
        "east": {
            "texture": tex_name,
            "uv": [tex_u + dz + dx, tex_v + dz, tex_u + 2 * dz + dx, tex_v + dz + dy],
            "uv_size": tex_size,
            "tintindex": tintindex,
        },
        "south": {
            "texture": tex_name,
            "uv": [tex_u + 2 * dz + dx, tex_v + dz, tex_u + 2 * dz + 2 * dx, tex_v + dz + dy],
            "uv_size": tex_size,
            "tintindex": tintindex,
        },
    }

    if omitted_faces:
        for face_name in omitted_faces:
            faces.pop(face_name, None)

    for d, cf in cull.items():
        if d in faces:
            faces[d]["cullface"] = cf

    if custom_faces:
        for d, f_data in custom_faces.items():
            faces[d] = f_data

    elem: dict[str, Any] = {
        "from": [float(from_pos[0]), float(from_pos[1]), float(from_pos[2])],
        "to": [float(to_pos[0]), float(to_pos[1]), float(to_pos[2])],
        "faces": faces,
    }
    if elem_rot:
        elem["rotation"] = elem_rot
    return elem


def get_facing_angle_y(facing: str) -> float:
    """Return Y-rotation angle in degrees for block models whose default unrotated front is North."""
    facing_map = {
        "north": 0.0,
        "east": 90.0,
        "south": 180.0,
        "west": 270.0,
    }
    return facing_map.get(facing.lower(), 0.0)


def get_entity_facing_angle_y(facing: str) -> float:
    """Return Y-rotation angle in degrees for entity models (Chests, etc.) whose unrotated front is South."""
    facing_map = {
        "south": 0.0,
        "north": 180.0,
        "east": 90.0,
        "west": 270.0,
    }
    return facing_map.get(facing.lower(), 0.0)

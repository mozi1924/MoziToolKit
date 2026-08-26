"""
Procedural model generator for Minecraft Skulls and Heads.
Supports Player Head, Skeleton Skull, Wither Skeleton Skull, Zombie Head,
Creeper Head, Piglin Head, and Dragon Head (Floor 16-rotations and Wall mounts).
"""

from __future__ import annotations
from typing import Optional
from .common import make_box_element, get_facing_angle_y


def get_skull_texture(short_name: str) -> tuple[str, float]:
    """Return (texture_path, tex_size) for skull type."""
    name = short_name.replace("_wall_", "_").removesuffix("_skull").removesuffix("_head")
    if name == "skeleton":
        return "minecraft:entity/skeleton/skeleton", 64.0
    elif name == "wither_skeleton":
        return "minecraft:entity/skeleton/wither_skeleton", 64.0
    elif name == "zombie":
        return "minecraft:entity/zombie/zombie", 64.0
    elif name == "creeper":
        return "minecraft:entity/creeper/creeper", 64.0
    elif name == "piglin":
        return "minecraft:entity/piglin/piglin", 64.0
    elif name == "dragon":
        return "minecraft:entity/enderdragon/dragon", 64.0
    # default player
    return "minecraft:entity/player/wide/steve", 64.0


def build_skull_elements(short_name: str, props: dict[str, str]) -> list[dict]:
    """Construct 3D elements for floor or wall mounted skull/head."""
    is_wall = "_wall_" in short_name
    tex, tex_size = get_skull_texture(short_name)
    has_hat = any(k in short_name for k in ("player", "zombie"))
    is_piglin = "piglin" in short_name
    is_dragon = "dragon" in short_name

    elements = []

    if is_wall:
        facing = props.get("facing", "north").lower()
        angle_y = get_facing_angle_y(facing)
        elem_rot = {"origin": [8, 8, 8], "axis": "y", "angle": angle_y} if angle_y != 0.0 else None

        # Wall skull base pos (mounted against south wall, facing north)
        if is_piglin:
            head = make_box_element([3, 4, 8], [13, 12, 16], 0, 0, tex, tex_size, elem_rot)
            elements.append(head)
        elif is_dragon:
            head = make_box_element([2, 4, 6], [14, 12, 18], 0, 0, tex, tex_size, elem_rot)
            elements.append(head)
        else:
            head = make_box_element([4, 4, 8], [12, 12, 16], 0, 0, tex, tex_size, elem_rot)
            elements.append(head)
            if has_hat:
                hat = make_box_element([3.75, 3.75, 7.75], [12.25, 12.25, 16.25], 32, 0, tex, tex_size, elem_rot)
                elements.append(hat)

    else:
        rot_idx = int(props.get("rotation", "0")) if "rotation" in props else 0
        angle = (180.0 - rot_idx * 22.5) % 360.0
        elem_rot = {"origin": [8, 4, 8], "axis": "y", "angle": angle} if angle != 0.0 else None

        if is_piglin:
            head = make_box_element([3, 0, 4], [13, 8, 12], 0, 0, tex, tex_size, elem_rot)
            elements.append(head)
        elif is_dragon:
            head = make_box_element([2, 0, 2], [14, 8, 14], 0, 0, tex, tex_size, elem_rot)
            elements.append(head)
        else:
            head = make_box_element([4, 0, 4], [12, 8, 12], 0, 0, tex, tex_size, elem_rot)
            elements.append(head)
            if has_hat:
                hat = make_box_element([3.75, -0.25, 3.75], [12.25, 8.25, 12.25], 32, 0, tex, tex_size, elem_rot)
                elements.append(hat)

    return elements

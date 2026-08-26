"""
Procedural model generator for Minecraft Chests.
Supports Single chests, Double chests (left/right), Trapped chests, Ender chests, and Copper chests.
"""

from __future__ import annotations
from typing import Optional
from .common import make_box_element, get_facing_angle_y


def get_chest_texture_stem(short_name: str) -> str:
    """Resolve entity texture stem for chest variant."""
    name = short_name.removeprefix("waxed_")
    if name == "trapped_chest":
        return "minecraft:entity/chest/trapped"
    elif name == "ender_chest":
        return "minecraft:entity/chest/ender"
    elif name in ("copper_chest", "exposed_copper_chest", "weathered_copper_chest", "oxidized_copper_chest"):
        return f"minecraft:entity/chest/{name}"
    return "minecraft:entity/chest/normal"


def build_chest_elements(short_name: str, props: dict[str, str]) -> list[dict]:
    """Generate 3D elements for chest models based on blockstate properties."""
    chest_type = props.get("type", "single")
    facing = props.get("facing", "north")
    angle_y = get_facing_angle_y(facing)
    elem_rot = {"origin": [8, 8, 8], "axis": "y", "angle": angle_y} if angle_y != 0.0 else None

    base_tex = get_chest_texture_stem(short_name)

    if chest_type == "single":
        # Single chest
        bottom = make_box_element(
            from_pos=[1, 0, 1],
            to_pos=[15, 10, 15],
            tex_u=0, tex_v=19,
            tex_name=base_tex,
            elem_rot=elem_rot,
        )
        lid = make_box_element(
            from_pos=[1, 9, 1],
            to_pos=[15, 14, 15],
            tex_u=0, tex_v=0,
            tex_name=base_tex,
            elem_rot=elem_rot,
        )
        lock = make_box_element(
            from_pos=[7, 7, 0],
            to_pos=[9, 11, 1],
            tex_u=0, tex_v=0,
            tex_name=base_tex,
            elem_rot=elem_rot,
        )
        return [bottom, lid, lock]

    elif chest_type == "left":
        tex = f"{base_tex}_left"
        bottom = make_box_element(
            from_pos=[0, 0, 1],
            to_pos=[15, 10, 15],
            tex_u=0, tex_v=19,
            tex_name=tex,
            elem_rot=elem_rot,
        )
        lid = make_box_element(
            from_pos=[0, 9, 1],
            to_pos=[15, 14, 15],
            tex_u=0, tex_v=0,
            tex_name=tex,
            elem_rot=elem_rot,
        )
        lock = make_box_element(
            from_pos=[0, 7, 0],
            to_pos=[1, 11, 1],
            tex_u=0, tex_v=0,
            tex_name=tex,
            elem_rot=elem_rot,
        )
        return [bottom, lid, lock]

    else:  # right
        tex = f"{base_tex}_right"
        bottom = make_box_element(
            from_pos=[1, 0, 1],
            to_pos=[16, 10, 15],
            tex_u=0, tex_v=19,
            tex_name=tex,
            elem_rot=elem_rot,
        )
        lid = make_box_element(
            from_pos=[1, 9, 1],
            to_pos=[16, 14, 15],
            tex_u=0, tex_v=0,
            tex_name=tex,
            elem_rot=elem_rot,
        )
        lock = make_box_element(
            from_pos=[15, 7, 0],
            to_pos=[16, 11, 1],
            tex_u=0, tex_v=0,
            tex_name=tex,
            elem_rot=elem_rot,
        )
        return [bottom, lid, lock]

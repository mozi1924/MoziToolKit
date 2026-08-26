"""
Procedural model generator for Minecraft Chests.
Supports Single chests, Double chests (left/right), Trapped chests, Ender chests, and Copper chests.
Accurately implements Minecraft Java Edition ModelPart geometry, UV unwrap, and block rotations.
"""

from __future__ import annotations
from typing import Optional
from .common import make_box_element, get_entity_facing_angle_y


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
    """Generate 3D elements for chest models based on blockstate properties.

    Minecraft Chest Coordinate System:
    - Base unrotated model faces South (+Z).
    - Single chest bottom: [1, 0, 1] to [15, 10, 15] (14x10x14)
    - Single chest lid: [1, 9, 1] to [15, 14, 15] (14x5x14)
    - Single chest lock: [7, 7, 15] to [9, 11, 16] (2x4x1) on the South front face
    - Double chest left: x spans [0, 15], omitting inner 'west' connecting face
    - Double chest right: x spans [1, 16], omitting inner 'east' connecting face
    - Rotation: South=0°, North=180°, East=90°, West=270° around [8, 8, 8].
    """
    chest_type = props.get("type", "single")
    facing = props.get("facing", "north")
    angle_y = get_entity_facing_angle_y(facing)
    elem_rot = {"origin": [8, 8, 8], "axis": "y", "angle": angle_y} if angle_y != 0.0 else None

    base_tex = get_chest_texture_stem(short_name)

    if chest_type == "single":
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
            from_pos=[7, 7, 15],
            to_pos=[9, 11, 16],
            tex_u=0, tex_v=0,
            tex_name=base_tex,
            elem_rot=elem_rot,
        )
        return [bottom, lid, lock]

    elif chest_type == "left":
        tex = f"{base_tex}_left"
        # Connected on west (-X in unrotated space), omitting west face
        bottom = make_box_element(
            from_pos=[0, 0, 1],
            to_pos=[15, 10, 15],
            tex_u=0, tex_v=19,
            tex_name=tex,
            elem_rot=elem_rot,
            omitted_faces=["west"],
        )
        lid = make_box_element(
            from_pos=[0, 9, 1],
            to_pos=[15, 14, 15],
            tex_u=0, tex_v=0,
            tex_name=tex,
            elem_rot=elem_rot,
            omitted_faces=["west"],
        )
        lock = make_box_element(
            from_pos=[0, 7, 15],
            to_pos=[1, 11, 16],
            tex_u=0, tex_v=0,
            tex_name=tex,
            elem_rot=elem_rot,
            omitted_faces=["west"],
        )
        return [bottom, lid, lock]

    else:  # right
        tex = f"{base_tex}_right"
        # Connected on east (+X in unrotated space), omitting east face
        bottom = make_box_element(
            from_pos=[1, 0, 1],
            to_pos=[16, 10, 15],
            tex_u=0, tex_v=19,
            tex_name=tex,
            elem_rot=elem_rot,
            omitted_faces=["east"],
        )
        lid = make_box_element(
            from_pos=[1, 9, 1],
            to_pos=[16, 14, 15],
            tex_u=0, tex_v=0,
            tex_name=tex,
            elem_rot=elem_rot,
            omitted_faces=["east"],
        )
        lock = make_box_element(
            from_pos=[15, 7, 15],
            to_pos=[16, 11, 16],
            tex_u=0, tex_v=0,
            tex_name=tex,
            elem_rot=elem_rot,
            omitted_faces=["east"],
        )
        return [bottom, lid, lock]

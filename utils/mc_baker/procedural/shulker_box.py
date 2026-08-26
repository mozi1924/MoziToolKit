"""
Procedural model generator for Minecraft Shulker Boxes.
Supports undyed and 16 dyed shulker boxes across all 6 directional facings.
"""

from __future__ import annotations
from typing import Optional
from .common import make_box_element


def get_shulker_texture(short_name: str) -> str:
    """Resolve entity texture for shulker box color."""
    if short_name == "shulker_box":
        return "minecraft:entity/shulker/shulker"
    color = short_name.replace("_shulker_box", "")
    return f"minecraft:entity/shulker/shulker_{color}"


def build_shulker_box_elements(short_name: str, props: dict[str, str]) -> list[dict]:
    """Generate 3D elements for shulker boxes with directional orientation."""
    tex = get_shulker_texture(short_name)
    facing = props.get("facing", "up").lower()

    # Directional rotation mapping
    elem_rot = None
    if facing == "down":
        elem_rot = {"origin": [8, 8, 8], "axis": "x", "angle": 180.0}
    elif facing == "north":
        elem_rot = {"origin": [8, 8, 8], "axis": "x", "angle": 270.0}
    elif facing == "south":
        elem_rot = {"origin": [8, 8, 8], "axis": "x", "angle": 90.0}
    elif facing == "west":
        elem_rot = {"origin": [8, 8, 8], "axis": "z", "angle": 90.0}
    elif facing == "east":
        elem_rot = {"origin": [8, 8, 8], "axis": "z", "angle": 270.0}

    base = make_box_element(
        from_pos=[0, 0, 0],
        to_pos=[16, 8, 16],
        tex_u=0, tex_v=28,
        tex_name=tex,
        elem_rot=elem_rot,
    )
    lid = make_box_element(
        from_pos=[0, 4, 0],
        to_pos=[16, 16, 16],
        tex_u=0, tex_v=0,
        tex_name=tex,
        elem_rot=elem_rot,
    )
    return [base, lid]

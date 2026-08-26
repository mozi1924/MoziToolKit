"""
Procedural model generator for Minecraft Bell body.
Matches official BellModel dimensions and entity texture mapping.
"""

from __future__ import annotations
from .common import make_box_element


def build_bell_elements(short_name: str, props: dict[str, str]) -> list[dict]:
    """Construct 3D elements for the bell body and flange."""
    bell_tex = "minecraft:entity/bell/bell_body"

    # Bell Body: [5, 4, 5] to [11, 11, 11]
    body = make_box_element(
        from_pos=[5, 4, 5],
        to_pos=[11, 11, 11],
        tex_u=0, tex_v=0,
        tex_name=bell_tex,
        tex_size=32.0,
    )
    # Bell Bottom Flange: [4, 2, 4] to [12, 4, 12]
    flange = make_box_element(
        from_pos=[4, 2, 4],
        to_pos=[12, 4, 12],
        tex_u=0, tex_v=13,
        tex_name=bell_tex,
        tex_size=32.0,
    )
    return [body, flange]

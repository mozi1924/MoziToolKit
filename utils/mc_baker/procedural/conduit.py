"""
Procedural model generator for Minecraft Conduits.
Accurately generates the outer conduit shell/cage and inner eye core.
"""

from __future__ import annotations
from .common import make_box_element


def build_conduit_elements(short_name: str, props: dict[str, str]) -> list[dict]:
    """Construct 3D elements for active/inactive conduit."""
    shell_tex = "minecraft:entity/conduit/base"
    eye_tex = "minecraft:entity/conduit/open_eye"

    # Outer cage / shell
    shell = make_box_element(
        from_pos=[4, 4, 4],
        to_pos=[12, 12, 12],
        tex_u=0, tex_v=0,
        tex_name=shell_tex,
        tex_size=32.0,
    )
    # Inner eye core
    eye = make_box_element(
        from_pos=[5, 5, 5],
        to_pos=[11, 11, 11],
        tex_u=0, tex_v=0,
        tex_name=eye_tex,
        tex_size=32.0,
    )
    return [shell, eye]

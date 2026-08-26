"""
Procedural model generator for Minecraft Decorated Pots.
Accurately generates the pot body, neck, and rim matching DecoratedPotRenderer.
"""

from __future__ import annotations
from .common import make_box_element


def build_decorated_pot_elements(short_name: str, props: dict[str, str]) -> list[dict]:
    """Construct multipart 3D elements for decorated pot."""
    base_tex = "minecraft:entity/decorated_pot/decorated_pot_base"

    # Main Body: [1, 0, 1] to [15, 14, 15]
    body = make_box_element(
        from_pos=[1, 0, 1],
        to_pos=[15, 14, 15],
        tex_u=0, tex_v=22,
        tex_name=base_tex,
        tex_size=64.0,
    )
    # Neck: [4, 14, 4] to [12, 15, 12]
    neck = make_box_element(
        from_pos=[4, 14, 4],
        to_pos=[12, 15, 12],
        tex_u=0, tex_v=0,
        tex_name=base_tex,
        tex_size=64.0,
    )
    # Top Rim: [3, 15, 3] to [13, 16, 13]
    rim = make_box_element(
        from_pos=[3, 15, 3],
        to_pos=[13, 16, 13],
        tex_u=0, tex_v=9,
        tex_name=base_tex,
        tex_size=64.0,
    )
    return [body, neck, rim]

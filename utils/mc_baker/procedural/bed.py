"""
Procedural model generator for Minecraft Beds.
Accurately generates foot and head parts for all 16 colored bed variants.
"""

from __future__ import annotations
from typing import Optional

MC_DIRECTIONS = ["east", "west", "up", "down", "south", "north"]


def build_bed_elements(short_name: str, props: dict[str, str]) -> list[dict]:
    """Construct multipart 3D elements for beds (legs + mattress + blanket/pillow)."""
    color = short_name.replace("_bed", "")
    part = props.get("part", "foot")

    wood_tex = "minecraft:block/oak_planks"
    wool_tex = f"minecraft:block/{color}_wool" if color else "minecraft:block/red_wool"
    white_wool = "minecraft:block/white_wool"

    elements = []
    if part == "foot":
        elements.append({
            "from": [0, 0, 13], "to": [3, 3, 16],
            "faces": {d: {"texture": wood_tex} for d in MC_DIRECTIONS}
        })
        elements.append({
            "from": [13, 0, 13], "to": [16, 3, 16],
            "faces": {d: {"texture": wood_tex} for d in MC_DIRECTIONS}
        })
        elements.append({
            "from": [0, 3, 0], "to": [16, 9, 16],
            "faces": {
                "up": {"texture": wool_tex},
                "down": {"texture": wood_tex},
                "north": {"texture": wool_tex},
                "south": {"texture": wool_tex},
                "east": {"texture": wool_tex},
                "west": {"texture": wool_tex},
            }
        })
    else:
        elements.append({
            "from": [0, 0, 0], "to": [3, 3, 3],
            "faces": {d: {"texture": wood_tex} for d in MC_DIRECTIONS}
        })
        elements.append({
            "from": [13, 0, 0], "to": [16, 3, 3],
            "faces": {d: {"texture": wood_tex} for d in MC_DIRECTIONS}
        })
        elements.append({
            "from": [0, 3, 0], "to": [16, 9, 16],
            "faces": {
                "up": {"texture": white_wool},
                "down": {"texture": wood_tex},
                "north": {"texture": white_wool},
                "south": {"texture": wool_tex},
                "east": {"texture": wool_tex},
                "west": {"texture": wool_tex},
            }
        })

    return elements

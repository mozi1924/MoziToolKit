"""
Procedural model generator for Minecraft Banners.
Accurately generates standing and wall banners matching official ModelBanner dimensions.
"""

from __future__ import annotations
from typing import Optional


def build_banner_elements(short_name: str, props: dict[str, str]) -> list[dict]:
    """Construct multipart 3D elements for standing and wall banners.

    Uses the authoritative 64x64 entity texture 'minecraft:entity/banner/banner_base'
    with exact official Minecraft ModelBanner / BannerFlagModel dimensions:
    - Standing banner: 2-block height frame with seamless pole-to-crossbar joint and front-facing cloth.
    - Wall banner: Wall-mounted crossbar with front-facing cloth hanging downwards.
    """
    is_wall = "_wall_banner" in short_name
    banner_tex = "minecraft:entity/banner/banner_base"

    if is_wall:
        # Wall banners are mounted against the south wall by default in the base model (facing north).
        cloth = {
            "from": [1.333333, -13.0, 13.666667],
            "to": [14.666667, 13.666667, 14.333333],
            "faces": {
                "north": {"texture": banner_tex, "uv": [1, 1, 21, 41], "uv_size": 64, "tintindex": 0},
                "south": {"texture": banner_tex, "uv": [22, 1, 42, 41], "uv_size": 64, "tintindex": 0},
                "west": {"texture": banner_tex, "uv": [0, 1, 1, 41], "uv_size": 64, "tintindex": 0},
                "east": {"texture": banner_tex, "uv": [21, 1, 22, 41], "uv_size": 64, "tintindex": 0},
                "up": {"texture": banner_tex, "uv": [1, 0, 21, 1], "uv_size": 64, "tintindex": 0},
                "down": {"texture": banner_tex, "uv": [21, 0, 41, 1], "uv_size": 64, "tintindex": 0},
            },
        }
        crossbar = {
            "from": [1.333333, 12.333333, 14.333333],
            "to": [14.666667, 13.666667, 15.666667],
            "faces": {
                "north": {"texture": banner_tex, "uv": [2, 44, 22, 46], "uv_size": 64, "tintindex": -1},
                "south": {"texture": banner_tex, "uv": [24, 44, 44, 46], "uv_size": 64, "tintindex": -1},
                "up": {"texture": banner_tex, "uv": [2, 42, 22, 44], "uv_size": 64, "tintindex": -1},
                "down": {"texture": banner_tex, "uv": [22, 42, 42, 44], "uv_size": 64, "tintindex": -1},
                "west": {"texture": banner_tex, "uv": [0, 44, 2, 46], "uv_size": 64, "tintindex": -1},
                "east": {"texture": banner_tex, "uv": [22, 44, 24, 46], "uv_size": 64, "tintindex": -1},
            },
        }
        return [cloth, crossbar]
    else:
        rot_idx = int(props.get("rotation", "0")) if "rotation" in props else 0
        angle = (180.0 - rot_idx * 22.5) % 360.0
        elem_rot = {"origin": [8, 8, 8], "axis": "y", "angle": angle} if angle != 0.0 else None

        cloth = {
            "from": [1.333333, 2.666667, 6.666667],
            "to": [14.666667, 29.333333, 7.333333],
            "faces": {
                "north": {"texture": banner_tex, "uv": [1, 1, 21, 41], "uv_size": 64, "tintindex": 0},
                "south": {"texture": banner_tex, "uv": [22, 1, 42, 41], "uv_size": 64, "tintindex": 0},
                "west": {"texture": banner_tex, "uv": [0, 1, 1, 41], "uv_size": 64, "tintindex": 0},
                "east": {"texture": banner_tex, "uv": [21, 1, 22, 41], "uv_size": 64, "tintindex": 0},
                "up": {"texture": banner_tex, "uv": [1, 0, 21, 1], "uv_size": 64, "tintindex": 0},
                "down": {"texture": banner_tex, "uv": [21, 0, 41, 1], "uv_size": 64, "tintindex": 0},
            },
        }
        crossbar = {
            "from": [1.333333, 28.0, 7.333333],
            "to": [14.666667, 29.333333, 8.666667],
            "faces": {
                "north": {"texture": banner_tex, "uv": [2, 44, 22, 46], "uv_size": 64, "tintindex": -1},
                "south": {"texture": banner_tex, "uv": [24, 44, 44, 46], "uv_size": 64, "tintindex": -1},
                "west": {"texture": banner_tex, "uv": [0, 44, 2, 46], "uv_size": 64, "tintindex": -1},
                "east": {"texture": banner_tex, "uv": [22, 44, 24, 46], "uv_size": 64, "tintindex": -1},
                "up": {"texture": banner_tex, "uv": [2, 42, 22, 44], "uv_size": 64, "tintindex": -1},
                "down": {"texture": banner_tex, "uv": [22, 42, 42, 44], "uv_size": 64, "tintindex": -1},
            },
        }
        pole = {
            "from": [7.333333, 0.0, 7.333333],
            "to": [8.666667, 28.0, 8.666667],
            "faces": {
                "north": {"texture": banner_tex, "uv": [44, 2, 46, 44], "uv_size": 64, "tintindex": -1},
                "south": {"texture": banner_tex, "uv": [48, 2, 50, 44], "uv_size": 64, "tintindex": -1},
                "east": {"texture": banner_tex, "uv": [50, 2, 52, 44], "uv_size": 64, "tintindex": -1},
                "west": {"texture": banner_tex, "uv": [46, 2, 48, 44], "uv_size": 64, "tintindex": -1},
                "up": {"texture": banner_tex, "uv": [46, 0, 48, 2], "uv_size": 64, "tintindex": -1},
                "down": {"texture": banner_tex, "uv": [48, 0, 50, 2], "uv_size": 64, "tintindex": -1},
            },
        }
        elements = [cloth, crossbar, pole]
        if elem_rot:
            for elem in elements:
                elem["rotation"] = elem_rot
        return elements

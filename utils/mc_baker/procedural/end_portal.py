"""
Procedural model generator for Minecraft End Portal & End Gateway planes.
Matches TheEndPortalRenderer planar geometry and orientation.
"""

from __future__ import annotations


def build_end_portal_elements(short_name: str, props: dict[str, str]) -> list[dict]:
    """Construct planar 3D element for end portal / gateway."""
    tex = "minecraft:entity/end_portal"

    portal_plane = {
        "from": [0.0, 12.0, 0.0],
        "to": [16.0, 12.0, 16.0],
        "faces": {
            "up": {"texture": tex, "uv": [0, 0, 16, 16], "uv_size": 16},
            "down": {"texture": tex, "uv": [0, 0, 16, 16], "uv_size": 16},
        },
    }
    return [portal_plane]

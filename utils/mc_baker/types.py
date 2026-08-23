"""
Data structures for Headless Minecraft Model Baker.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Any

# Standard Minecraft 6 Directions
# Index 0: East (+X), Index 1: West (-X), Index 2: Up (+Y), Index 3: Down (-Y), Index 4: South (+Z), Index 5: North (-Z)
MC_DIRECTIONS = ("east", "west", "up", "down", "south", "north")

DIR_TO_INDEX = {
    "east": 0,
    "west": 1,
    "up": 2,
    "down": 3,
    "south": 4,
    "north": 5,
}

INDEX_TO_DIR = {v: k for k, v in DIR_TO_INDEX.items()}

# Vector normal for each direction in Minecraft space
DIR_NORMALS = {
    "east": (1.0, 0.0, 0.0),
    "west": (-1.0, 0.0, 0.0),
    "up": (0.0, 1.0, 0.0),
    "down": (0.0, -1.0, 0.0),
    "south": (0.0, 0.0, 1.0),
    "north": (0.0, 0.0, -1.0),
}


@dataclass
class BakedFace:
    """Represents a single baked quad face with texture, UV bounds, and UV rotation."""
    direction: str  # "east", "west", "up", "down", "south", "north"
    texture: str    # e.g. "minecraft:block/magenta_glazed_terracotta"
    uv_rot: float = 0.0  # In degrees: 0.0, 90.0, 180.0, 270.0 (clockwise)
    uv_bounds: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)  # min_u, min_v, max_u, max_v in [0..1]
    tint_index: int = -1
    cullface: Optional[str] = None
    # 4 quad vertices in Minecraft block space [0..1]
    vertices: tuple[tuple[float, float, float], ...] = field(default_factory=tuple)
    # 4 quad UV coordinates in texture space [0..1]
    uvs: tuple[tuple[float, float], ...] = field(default_factory=tuple)


@dataclass
class BakedElement:
    """Represents a 3D box element of a baked model."""
    from_pos: tuple[float, float, float]  # [0..16]
    to_pos: tuple[float, float, float]    # [0..16]
    faces: dict[str, BakedFace] = field(default_factory=dict)
    rotation: Optional[dict[str, Any]] = None


@dataclass
class BakedModel:
    """Full baked model result containing all elements and the standard 6-face summary."""
    block_state: str
    elements: list[BakedElement] = field(default_factory=list)
    # Standard 6-face summary (East, West, Up, Down, South, North) for cubic / point-cloud fast dispatch
    faces: list[BakedFace] = field(default_factory=list)
    is_cube: bool = True
    is_opaque: bool = True
    is_emissive: bool = False
    emissive_level: float = 0.0

    def get_face(self, direction: str) -> Optional[BakedFace]:
        """Get BakedFace by direction name (east/west/up/down/south/north or +X/-X/+Y/-Y/+Z/-Z)."""
        alias_map = {"+x": "east", "-x": "west", "+y": "up", "-y": "down", "+z": "south", "-z": "north"}
        dir_clean = alias_map.get(direction.lower(), direction.lower())
        idx = DIR_TO_INDEX.get(dir_clean)
        if idx is not None and idx < len(self.faces):
            return self.faces[idx]
        return None

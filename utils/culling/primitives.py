"""
Standard Minecraft Voxel Geometric Primitives and Coordinate Transforms.

Provides authoritative cube face vertex coordinates, canonical [0..1] texture UVs,
6-direction coordinate offsets, and Minecraft-to-Blender space transformation utilities
for both real-time synchronization and offline static mesh reconstruction.
"""

from __future__ import annotations

from typing import Dict, Sequence, Tuple

# Minecraft 6-Direction Neighbor Offsets (dx, dy, dz) in Minecraft Grid Coordinates:
# MC: +X is East, -X is West, +Y is Up, -Y is Down, +Z is South, -Z is North
MC_DIR_OFFSETS: dict[str, tuple[int, int, int]] = {
    "east": (1, 0, 0),
    "west": (-1, 0, 0),
    "up": (0, 1, 0),
    "down": (0, -1, 0),
    "south": (0, 0, 1),
    "north": (0, 0, -1),
}

DIR_TO_INDEX: dict[str, int] = {
    "east": 0,
    "west": 1,
    "up": 2,
    "down": 3,
    "south": 4,
    "north": 5,
}

INDEX_TO_DIR: dict[int, str] = {
    0: "east",
    1: "west",
    2: "up",
    3: "down",
    4: "south",
    5: "north",
}

# Standard Unit Cube Quads in Minecraft local coordinates [0..1]
CUBE_FACE_MC_VERTICES: dict[str, tuple[tuple[float, float, float], ...]] = {
    "east": ((1.0, 1.0, 1.0), (1.0, 0.0, 1.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)),
    "west": ((0.0, 1.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 1.0)),
    "up": ((0.0, 1.0, 0.0), (0.0, 1.0, 1.0), (1.0, 1.0, 1.0), (1.0, 1.0, 0.0)),
    "top": ((0.0, 1.0, 0.0), (0.0, 1.0, 1.0), (1.0, 1.0, 1.0), (1.0, 1.0, 0.0)),
    "down": ((0.0, 0.0, 1.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0)),
    "bottom": ((0.0, 0.0, 1.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0)),
    "south": ((0.0, 1.0, 1.0), (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0)),
    "north": ((1.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
}

# Standard Default Face UVs in Minecraft texture space [0..1] (v=0 is top, v=1 is bottom)
CUBE_FACE_CANONICAL_UVS: dict[str, tuple[tuple[float, float], ...]] = {
    "east": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
    "west": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
    "up": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
    "top": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
    "down": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
    "bottom": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
    "south": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
    "north": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
}


def mc_local_to_blender(lx: float, ly: float, lz: float) -> tuple[float, float, float]:
    """
    Convert Minecraft local offset [0..1] relative to block center to Blender coordinate space.
    
    Transforms:
    - Minecraft +X (East) -> Blender +X
    - Minecraft -Z (North) -> Blender +Y (Minecraft North is Blender +Y, South is Blender -Y)
    - Minecraft +Y (Up) -> Blender +Z
    """
    return (
        lx - 0.5,
        -(lz - 0.5),
        ly - 0.5,
    )


def get_cube_face_geometry(
    direction: str,
) -> tuple[tuple[tuple[float, float, float], ...], tuple[tuple[float, float], ...]]:
    """Return canonical (local_vertices, canonical_uvs) for a standard unit cube face direction."""
    norm_dir = direction.lower().strip()
    verts = CUBE_FACE_MC_VERTICES.get(norm_dir, CUBE_FACE_MC_VERTICES["east"])
    uvs = CUBE_FACE_CANONICAL_UVS.get(norm_dir, CUBE_FACE_CANONICAL_UVS["east"])
    return verts, uvs

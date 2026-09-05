"""
Common test fixtures and mock builders for Live Sync test suites.
"""

from __future__ import annotations
from typing import Any, Dict, Optional


def make_dummy_atlas_params(
    width: int = 1024,
    height: int = 512,
    tile_size: int = 16,
    tiles_per_row: int = 64,
    extra_textures: Optional[Dict[str, Dict[str, Any]]] = None,
    chunks: Optional[list] = None,
) -> Dict[str, Any]:
    """Create a standardized dummy atlas_params dict for Live Sync mesh building."""
    mapping = {
        "textures": {
            "minecraft:block/stone": {
                "chunk_id": 0,
                "tile_column": 2,
                "tile_row": 1,
            },
            "minecraft:block/dirt": {
                "chunk_id": 0,
                "tile_column": 3,
                "tile_row": 1,
            },
            "minecraft:block/oak_planks": {
                "chunk_id": 0,
                "tile_column": 4,
                "tile_row": 1,
            },
            "minecraft:block/glass": {
                "chunk_id": 0,
                "tile_column": 1,
                "tile_row": 3,
            },
            "minecraft:block/water_still": {
                "chunk_id": 0,
                "tile_column": 13,
                "tile_row": 12,
            },
            "minecraft:block/water_flow": {
                "chunk_id": 0,
                "tile_column": 14,
                "tile_row": 12,
            },
            "minecraft:block/lava_still": {
                "chunk_id": 0,
                "tile_column": 13,
                "tile_row": 14,
            },
        }
    }
    if extra_textures:
        mapping["textures"].update(extra_textures)
    if chunks is not None:
        mapping["chunks"] = chunks

    return {
        "width": width,
        "height": height,
        "tile_size": tile_size,
        "tiles_per_row": tiles_per_row,
        "mapping": mapping,
    }

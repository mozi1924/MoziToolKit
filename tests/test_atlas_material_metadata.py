"""
Unit tests for Atlas Material Metadata, Dimensions, and Cross-Project Integration with Yefira.
"""

import sys
import unittest
import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from utils.materials import (
    PROP_ATLAS_WIDTH,
    PROP_ATLAS_HEIGHT,
    PROP_TILE_SIZE,
    PROP_TILES_PER_ROW,
    PROP_ATLAS_MAPPING,
    get_atlas_mapping_from_material,
    get_material_atlas_dimensions,
)


class MockMaterial:
    """Mock Blender Material for headless testing without bpy."""

    def __init__(self, name="Mock_Atlas_Mat"):
        self.name = name
        self.properties = {}
        self.node_tree = MockNodeTree()

    def __getitem__(self, key):
        return self.properties[key]

    def __setitem__(self, key, value):
        self.properties[key] = value

    def __contains__(self, key):
        return key in self.properties

    def get(self, key, default=None):
        return self.properties.get(key, default)


class MockNodeTree:
    """Mock Material Node Tree."""

    def __init__(self):
        self.properties = {}

    def __getitem__(self, key):
        return self.properties[key]

    def __setitem__(self, key, value):
        self.properties[key] = value

    def __contains__(self, key):
        return key in self.properties

    def get(self, key, default=None):
        return self.properties.get(key, default)


class TestAtlasMaterialMetadata(unittest.TestCase):

    def test_constants_defined(self):
        self.assertEqual(PROP_ATLAS_WIDTH, "mtk_atlas_width")
        self.assertEqual(PROP_ATLAS_HEIGHT, "mtk_atlas_height")
        self.assertEqual(PROP_TILE_SIZE, "mtk_tile_size")
        self.assertEqual(PROP_TILES_PER_ROW, "mtk_tiles_per_row")
        self.assertEqual(PROP_ATLAS_MAPPING, "mtk:atlas_mapping")

    def test_get_material_atlas_dimensions_from_custom_props(self):
        mat = MockMaterial("mtk:minecraft:atlas_chunk_000")
        mat["mtk_atlas_width"] = 2048.0
        mat["mtk_atlas_height"] = 1024.0
        mat["mtk_tile_size"] = 32.0
        mat["mtk_tiles_per_row"] = 64

        dims = get_material_atlas_dimensions(mat)
        self.assertEqual(dims["width"], 2048.0)
        self.assertEqual(dims["height"], 1024.0)
        self.assertEqual(dims["tile_size"], 32.0)
        self.assertEqual(dims["tiles_per_row"], 64)

    def test_get_material_atlas_dimensions_fallback_from_mapping(self):
        mat = MockMaterial("MC_Atlas_Material")
        sample_mapping = {
            "tile_size": 16,
            "chunks": [
                {
                    "chunk_id": 0,
                    "width": 1024,
                    "height": 512,
                    "tile_size": 16,
                    "tiles_per_row": 64,
                }
            ],
            "textures": {},
            "materials": [],
        }
        mat["mtk:atlas_mapping"] = json.dumps(sample_mapping)

        # Mapping is parsed
        parsed_mapping = get_atlas_mapping_from_material(mat)
        self.assertIsNotNone(parsed_mapping)
        self.assertEqual(parsed_mapping["tile_size"], 16)

        # Dimensions are resolved from chunk
        dims = get_material_atlas_dimensions(mat)
        self.assertEqual(dims["width"], 1024.0)
        self.assertEqual(dims["height"], 512.0)
        self.assertEqual(dims["tile_size"], 16.0)
        self.assertEqual(dims["tiles_per_row"], 64)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

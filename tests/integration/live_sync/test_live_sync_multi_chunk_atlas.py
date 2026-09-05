"""
Unit tests for Live Sync multi-chunk atlas adaptation.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy

# Bootstrap MoziToolKit package (also activates the isolated test sandbox)
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from utils.materials.yefira.atlas_integration import (
    extract_atlas_parameters,
    find_active_atlas_material,
)
from utils.materials.yefira import refresh_baker_sources as yefira_refresh_baker
from utils.live_sync import VoxelStorage, build_world_mesh


class TestLiveSyncMultiChunkAtlas(unittest.TestCase):
    def setUp(self):
        # Clear existing materials & node groups created during tests
        for mat in list(bpy.data.materials):
            bpy.data.materials.remove(mat)
        for group in list(bpy.data.node_groups):
            bpy.data.node_groups.remove(group)
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj)

    def test_extract_atlas_parameters_multi_chunk(self):
        """Verify extract_atlas_parameters dynamically resolves blocks vs animation chunks."""
        mat = bpy.data.materials.new(name="mtk:minecraft:blocks_chunk_000")
        mapping = {
            "format_version": 10,
            "tile_size": 16,
            "chunks": [
                {
                    "chunk_id": 0,
                    "category": "blocks",
                    "kind": "static",
                    "width": 2048,
                    "height": 2048,
                    "tile_size": 16,
                    "tiles_per_row": 128,
                },
                {
                    "chunk_id": 1,
                    "category": "items",
                    "kind": "static",
                    "width": 1024,
                    "height": 1024,
                    "tile_size": 16,
                    "tiles_per_row": 64,
                },
                {
                    "chunk_id": 2,
                    "category": "particles",
                    "kind": "animation",
                    "width": 512,
                    "height": 1024,
                    "tile_size": 16,
                },
            ],
            "textures": {},
            "materials": [],
        }
        mat["mtk:atlas_mapping"] = json.dumps(mapping)

        params = extract_atlas_parameters(mat)
        # Static blocks chunk should determine main width/height
        self.assertEqual(params["width"], 2048.0)
        self.assertEqual(params["height"], 2048.0)
        self.assertEqual(params["tiles_per_row"], 128)

        # Animation chunk (chunk 2) should be dynamically extracted
        self.assertEqual(params["anim_atlas_width"], 512.0)
        self.assertEqual(params["anim_atlas_height"], 1024.0)
        self.assertEqual(params["anim_frame_width"], 16.0)
        self.assertEqual(params["anim_frame_height"], 16.0)

    def test_find_active_atlas_material_new_naming(self):
        """Verify find_active_atlas_material detects new mtk:namespace:category_chunk_id naming."""
        mat = bpy.data.materials.new(name="mtk:minecraft:blocks_chunk_000")
        found = find_active_atlas_material()
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "mtk:minecraft:blocks_chunk_000")

    def test_refresh_baker_sources(self):
        """Verify refresh_baker_sources executes cleanly."""
        yefira_refresh_baker()

    def test_direct_mesh_multi_chunk_and_uv_rotations(self):
        """Verify Direct Mesh correctly handles multi-chunk atlas textures and native UVMap."""
        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:oak_log[axis=y]")
        storage.set_block(1, 0, 0, "minecraft:water")

        atlas_params = {
            "width": 1024,
            "height": 512,
            "tile_size": 16,
            "tiles_per_row": 64,
            "anim_atlas_width": 896,
            "anim_atlas_height": 1024,
            "mapping": {
                "textures": {
                    "minecraft:block/oak_log": {"chunk_id": 0, "tile_column": 10, "tile_row": 2},
                    "minecraft:block/oak_log_top": {"chunk_id": 0, "tile_column": 11, "tile_row": 2},
                    "minecraft:block/water_still": {
                        "chunk_id": 1,
                        "kind": "animation",
                        "pixel_x": 0,
                        "pixel_y": 0,
                        "frame_width": 16,
                        "frame_height": 16,
                    },
                }
            }
        }

        res = build_world_mesh(bpy.context, storage, atlas_params=atlas_params)
        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data

        self.assertIn("UVMap", mesh.uv_layers)
        self.assertIn("Color", mesh.color_attributes)
        self.assertEqual(res.cubes_count, 1)
        self.assertEqual(res.fluids_count, 1)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

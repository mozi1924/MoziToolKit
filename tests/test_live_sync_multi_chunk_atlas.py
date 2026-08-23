"""
Unit tests for Live Sync multi-chunk atlas adaptation.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
import bpy

from utils.geometry_nodes.groups.atlas_uv import (
    GROUP_NAME_ATLAS_UV_CALCULATOR,
    ATLAS_UV_CALCULATOR_VERSION,
    get_or_create_atlas_uv_calculator_group,
)
from utils.geometry_nodes.world_tree import (
    WORLD_TREE_NAME,
    WORLD_TREE_SCHEMA_VERSION,
    setup_world_geometry_nodes,
)
from utils.materials.atlas_integration import (
    extract_atlas_parameters,
    find_active_atlas_material,
)
from utils.live_sync.point_cloud import refresh_baker_sources as sync_refresh_baker
from utils.materials.yefira import refresh_baker_sources as yefira_refresh_baker


class TestLiveSyncMultiChunkAtlas(unittest.TestCase):
    def setUp(self):
        # Clear existing materials & node groups created during tests
        for mat in list(bpy.data.materials):
            bpy.data.materials.remove(mat)
        for group in list(bpy.data.node_groups):
            bpy.data.node_groups.remove(group)
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj)

    def test_atlas_uv_calculator_anim_frame_count(self):
        """Verify Yefira_Atlas_UV_Calculator compares Anim Frame Count > 1.0."""
        tree = get_or_create_atlas_uv_calculator_group()
        self.assertIsNotNone(tree)
        self.assertEqual(tree.get("mozi_group_version"), ATLAS_UV_CALCULATOR_VERSION)

        # Check interface sockets
        socket_names = [item.name for item in tree.interface.items_tree if item.item_type == "SOCKET"]
        self.assertIn("Anim Frame Count", socket_names)
        self.assertIn("Chunk ID", socket_names)
        self.assertIn("Atlas UV", socket_names)

        # Find the compare node
        compare_nodes = [n for n in tree.nodes if n.bl_idname == "FunctionNodeCompare"]
        self.assertTrue(len(compare_nodes) > 0)
        cmp_node = compare_nodes[0]
        self.assertEqual(cmp_node.data_type, "FLOAT")
        self.assertEqual(cmp_node.operation, "GREATER_THAN")
        self.assertAlmostEqual(cmp_node.inputs["B"].default_value, 1.0)

        # Verify cmp_node input A is connected from Anim Frame Count
        links_to_cmp = [l for l in tree.links if l.to_node == cmp_node and l.to_socket == cmp_node.inputs["A"]]
        self.assertEqual(len(links_to_cmp), 1)
        self.assertEqual(links_to_cmp[0].from_socket.name, "Anim Frame Count")

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
        sync_refresh_baker()
        yefira_refresh_baker()

    def test_point_cloud_directional_uv_rotations_not_overwritten(self):
        """Verify oak_log[axis=y] maintains 0.0 UV rotation and is not corrupted by atlas static LUT."""
        from utils.live_sync import VoxelStorage, update_world_point_cloud
        from utils.materials.atlas_integration import build_block_face_uv_rot_lut

        storage = VoxelStorage()
        storage.min_x = storage.min_y = storage.min_z = 0
        storage.size_x = storage.size_y = storage.size_z = 1
        storage.block_map[(0, 0, 0)] = "minecraft:oak_log[axis=y]"

        mock_mapping = {
            "materials": [
                {
                    "name": "minecraft:oak_log",
                    "faces": {
                        "+X": {"uv_rotation": 90.0},
                        "-X": {"uv_rotation": 90.0},
                        "+Y": {"uv_rotation": 0.0},
                        "-Y": {"uv_rotation": 0.0},
                        "+Z": {"uv_rotation": 90.0},
                        "-Z": {"uv_rotation": 90.0},
                    },
                }
            ]
        }
        rot_lut = build_block_face_uv_rot_lut(mock_mapping)

        res = update_world_point_cloud(bpy.context, storage, block_face_uv_rot_lut=rot_lut)
        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data
        for face in ("east", "west", "top", "bottom", "south", "north"):
            val = mesh.attributes[f"mtk_uv_rot_{face}"].data[0].value
            self.assertEqual(val, 0.0, f"Face {face} for oak_log[axis=y] had non-zero rotation: {val}")


if __name__ == "__main__":
    unittest.main()

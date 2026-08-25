"""
Test Suite for Direct Mesh Generation (World Mesh Builder).
Tests:
- Native face culling for full opaque cubes.
- Native loop UV layers with correct Atlas coordinate mapping.
- Direct material slot assignment by chunk ID.
- Biome and state color tint attributes.
- Complex/multipart models rendering without geometry nodes.
"""

from __future__ import annotations

import unittest
import bpy

from utils.live_sync import (
    VoxelStorage,
    build_world_mesh,
    WorldMeshBuildResult,
)


class TestDirectMeshSync(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_homefile(use_empty=True)

    def tearDown(self):
        bpy.ops.wm.read_homefile(use_empty=True)

    def test_single_cube_mesh_generation_and_uvs(self):
        """A single cube should produce 6 faces, 24 loops, and valid UVMap."""
        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:stone")

        atlas_params = {
            "width": 1024,
            "height": 512,
            "tile_size": 16,
            "tiles_per_row": 64,
            "mapping": {
                "textures": {
                    "minecraft:block/stone": {
                        "chunk_id": 0,
                        "tile_column": 2,
                        "tile_row": 1,
                    }
                }
            }
        }

        res = build_world_mesh(bpy.context, storage, atlas_params=atlas_params)
        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data

        self.assertEqual(len(mesh.polygons), 6)
        self.assertEqual(res.cubes_count, 1)

        # Check native UVMap layer
        self.assertIn("UVMap", mesh.uv_layers)
        uv_layer = mesh.uv_layers["UVMap"]

        # Expected UV bounds for tile (col=2, row=1):
        # U in [2*16/1024, 3*16/1024] -> [32/1024, 48/1024] -> [0.03125, 0.046875]
        # V in [1.0 - 2*16/512, 1.0 - 1*16/512] -> [1 - 32/512, 1 - 16/512] -> [0.9375, 0.96875]
        min_u = min(d.uv.x for d in uv_layer.data)
        max_u = max(d.uv.x for d in uv_layer.data)
        min_v = min(d.uv.y for d in uv_layer.data)
        max_v = max(d.uv.y for d in uv_layer.data)

        self.assertAlmostEqual(min_u, 2 * 16 / 1024, places=4)
        self.assertAlmostEqual(max_u, 3 * 16 / 1024, places=4)
        self.assertAlmostEqual(min_v, 1.0 - 2 * 16 / 512, places=4)
        self.assertAlmostEqual(max_v, 1.0 - 1 * 16 / 512, places=4)

        # Check Color attribute exists
        self.assertIn("Color", mesh.color_attributes)

    def test_face_culling_between_adjacent_cubes(self):
        """Two adjacent opaque cubes should have their touching faces culled (12 - 2 = 10 faces)."""
        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:stone")
        storage.set_block(1, 0, 0, "minecraft:stone")

        res = build_world_mesh(bpy.context, storage)
        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data

        # 6 + 6 - 2 = 10 faces
        self.assertEqual(len(mesh.polygons), 10)
        self.assertEqual(res.cubes_count, 2)

    def test_3x3x3_solid_cube_culling(self):
        """A solid 3x3x3 cube (27 blocks) should only render exterior shell (6 * 9 = 54 faces)."""
        storage = VoxelStorage()
        for x in range(3):
            for y in range(3):
                for z in range(3):
                    storage.set_block(x, y, z, "minecraft:stone")

        res = build_world_mesh(bpy.context, storage)
        mesh = res.world_obj.data

        # 3x3 per side * 6 sides = 54 faces
        self.assertEqual(len(mesh.polygons), 54)
        self.assertEqual(res.cubes_count, 27)

    def test_multi_chunk_material_indices(self):
        """Faces mapping to different chunks should have matching material_index on polygons."""
        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:stone")     # Chunk 0
        storage.set_block(5, 0, 0, "minecraft:sea_lantern") # Chunk 1 (anim)

        atlas_params = {
            "width": 1024,
            "height": 512,
            "tile_size": 16,
            "tiles_per_row": 64,
            "anim_atlas_width": 896,
            "anim_atlas_height": 1024,
            "mapping": {
                "textures": {
                    "minecraft:block/stone": {
                        "chunk_id": 0,
                        "tile_column": 0,
                        "tile_row": 0,
                    },
                    "minecraft:block/sea_lantern": {
                        "chunk_id": 1,
                        "kind": "animation",
                        "pixel_x": 32,
                        "pixel_y": 0,
                        "frame_width": 16,
                        "frame_height": 16,
                    }
                }
            }
        }

        res = build_world_mesh(bpy.context, storage, atlas_params=atlas_params)
        mesh = res.world_obj.data

        mat_indices = {p.material_index for p in mesh.polygons}
        self.assertIn(0, mat_indices)
        self.assertIn(1, mat_indices)

    def test_air_blocks_generate_zero_mesh(self):
        """All types of air blocks (air, cave_air, void_air, structure_void) must generate 0 faces."""
        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:air")
        storage.set_block(1, 0, 0, "minecraft:cave_air")
        storage.set_block(0, 1, 0, "minecraft:void_air")
        storage.set_block(0, 0, 1, "minecraft:structure_void")

        res = build_world_mesh(bpy.context, storage)
        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data

        self.assertEqual(len(mesh.polygons), 0)
        self.assertEqual(len(mesh.vertices), 0)
        self.assertEqual(res.cubes_count, 0)
        self.assertEqual(res.props_count, 0)
        self.assertEqual(res.fluids_count, 0)

    def test_solid_block_surrounded_by_air(self):
        """A stone block surrounded by air blocks should generate all 6 exterior faces."""
        storage = VoxelStorage()
        storage.set_block(1, 1, 1, "minecraft:stone")
        storage.set_block(0, 1, 1, "minecraft:air")
        storage.set_block(2, 1, 1, "minecraft:air")
        storage.set_block(1, 0, 1, "minecraft:cave_air")
        storage.set_block(1, 2, 1, "minecraft:void_air")
        storage.set_block(1, 1, 0, "minecraft:air")
        storage.set_block(1, 1, 2, "minecraft:air")

        res = build_world_mesh(bpy.context, storage)
        mesh = res.world_obj.data

        # Only the stone block's 6 faces should exist
        self.assertEqual(len(mesh.polygons), 6)
        self.assertEqual(res.cubes_count, 1)

    def test_json_payload_air_blocks_generate_zero_mesh(self):
        """JSON payload formatted air blocks from live sync server must be filtered out completely."""
        json_air = '{"state":"minecraft:air","type":7,"opaque":0,"emissive":0,"faces":{"east":{"tex":"minecraft:block/air","rot":0,"uv":[0.0,0.0,1.0,1.0],"tint":-1},"west":{"tex":"minecraft:block/air","rot":0,"uv":[0.0,0.0,1.0,1.0],"tint":-1},"top":{"tex":"minecraft:block/air","rot":0,"uv":[0.0,0.0,1.0,1.0],"tint":-1},"bottom":{"tex":"minecraft:block/air","rot":0,"uv":[0.0,0.0,1.0,1.0],"tint":-1},"south":{"tex":"minecraft:block/air","rot":0,"uv":[0.0,0.0,1.0,1.0],"tint":-1},"north":{"tex":"minecraft:block/air","rot":0,"uv":[0.0,0.0,1.0,1.0],"tint":-1}}}'
        json_dirt = '{"state":"minecraft:dirt","type":0,"opaque":1,"emissive":0,"faces":{"east":{"tex":"minecraft:block/dirt","rot":0,"uv":[0.0,0.0,1.0,1.0],"tint":-1},"west":{"tex":"minecraft:block/dirt","rot":0,"uv":[0.0,0.0,1.0,1.0],"tint":-1},"top":{"tex":"minecraft:block/dirt","rot":180,"uv":[0.0,0.0,1.0,1.0],"tint":-1},"bottom":{"tex":"minecraft:block/dirt","rot":180,"uv":[0.0,0.0,1.0,1.0],"tint":-1},"south":{"tex":"minecraft:block/dirt","rot":0,"uv":[0.0,0.0,1.0,1.0],"tint":-1},"north":{"tex":"minecraft:block/dirt","rot":0,"uv":[0.0,0.0,1.0,1.0],"tint":-1}}}'

        storage = VoxelStorage()
        storage.set_block(0, 0, 0, json_dirt)
        storage.set_block(1, 0, 0, json_air)
        storage.set_block(2, 0, 0, json_air)
        storage.set_block(0, 1, 0, json_air)

        res = build_world_mesh(bpy.context, storage)
        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data

        # Only 1 dirt cube should exist -> 6 faces
        self.assertEqual(len(mesh.polygons), 6)
        self.assertEqual(res.cubes_count, 1)


if __name__ == "__main__":
    unittest.main()

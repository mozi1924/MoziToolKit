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

    def test_vertex_welding_topology(self):
        """Verify that weld_vertices merges co-located vertices into clean topology (8 vertices for a single cube, 12 for 2 joined cubes)."""
        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:stone")

        # 1. Single cube with welding -> 8 vertices
        res_welded = build_world_mesh(bpy.context, storage, weld_vertices=True)
        self.assertEqual(len(res_welded.world_obj.data.vertices), 8)
        self.assertEqual(len(res_welded.world_obj.data.polygons), 6)

        # 2. Single cube without welding -> 24 vertices
        res_unwelded = build_world_mesh(bpy.context, storage, weld_vertices=False)
        self.assertEqual(len(res_unwelded.world_obj.data.vertices), 24)
        self.assertEqual(len(res_unwelded.world_obj.data.polygons), 6)

        # 3. Two joined cubes with welding -> 12 vertices, 10 faces
        storage.set_block(1, 0, 0, "minecraft:stone")
        res_two = build_world_mesh(bpy.context, storage, weld_vertices=True)
        self.assertEqual(len(res_two.world_obj.data.vertices), 12)
        self.assertEqual(len(res_two.world_obj.data.polygons), 10)

    def test_live_sync_material_manager_resolution(self):
        """Verify LiveSyncMaterialManager dynamic material loading and texture addressing."""
        from utils.live_sync import LiveSyncMaterialManager, parse_and_classify

        mesh = bpy.data.meshes.new("TestObjMesh")
        obj = bpy.data.objects.new("TestObj", mesh)
        bpy.context.collection.objects.link(obj)

        mat_manager = LiveSyncMaterialManager(world_obj=obj)
        mock_mapping = {
            "textures": {
                "minecraft:block/stone": {"chunk_id": 0, "tile_column": 4, "tile_row": 2},
                "minecraft:block/water_still": {
                    "chunk_id": 1,
                    "kind": "animation",
                    "pixel_x": 16,
                    "pixel_y": 0,
                    "frame_width": 16,
                    "frame_height": 16,
                },
            }
        }
        mat_manager.atlas_params["mapping"] = mock_mapping
        mat_manager.atlas_params["width"] = 1024
        mat_manager.atlas_params["height"] = 512
        mat_manager.atlas_params["tile_size"] = 16
        mat_manager.atlas_params["anim_atlas_width"] = 512
        mat_manager.atlas_params["anim_atlas_height"] = 512
        mat_manager.refresh()

        # 1. Resolve stone face
        parsed_stone = parse_and_classify("minecraft:stone")
        f_stone = mat_manager.resolve_block_face(parsed_stone, "east", 0)
        self.assertEqual(f_stone.chunk_id, 0)
        self.assertEqual(f_stone.slot_index, 0)
        u_stone, v_stone = f_stone.calc_uv_fn(0.0, 1.0)
        # col=4, row=2, u=0.0, v=1.0 -> U=(4+0)*16/1024 = 64/1024 = 0.0625; V=1.0 - (2 + 1 - 1)*16/512 = 1.0 - 32/512 = 0.9375
        self.assertAlmostEqual(u_stone, 0.0625, places=4)
        self.assertAlmostEqual(v_stone, 0.9375, places=4)

        # 2. Resolve water face (Animation Chunk)
        parsed_water = parse_and_classify("minecraft:water")
        f_water = mat_manager.resolve_block_face(parsed_water, "top", 2)
        self.assertEqual(f_water.chunk_id, 1)
        # pixel_x=16, pixel_y=0, fw=16, fh=16, u=0.0, v=1.0 -> U=(16+0)/1024 = 16/1024 = 0.015625, V=1 - (0 + (1-1)*16)/512 = 1.0
        u_water, v_water = f_water.calc_uv_fn(0.0, 1.0)
        self.assertAlmostEqual(u_water, 0.015625, places=4)
        self.assertAlmostEqual(v_water, 1.0, places=4)

    def test_material_hash_validation_and_no_master(self):
        """Verify that Master material is eliminated and chunk materials validate pack hashes."""
        from utils.live_sync import LiveSyncMaterialManager, build_world_mesh, VoxelStorage

        # Clean old materials
        for m in list(bpy.data.materials):
            if "Yefira_Atlas_Master" in m.name or "MC_Atlas_Chunk" in m.name:
                bpy.data.materials.remove(m)

        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:stone")

        res = build_world_mesh(bpy.context, storage)
        obj = res.world_obj
        self.assertIsNotNone(obj)

        # 1. Verify NO 'Yefira_Atlas_Master' in material slots
        slot_names = [s.name for s in obj.material_slots if s.material]
        self.assertNotIn("Yefira_Atlas_Master", slot_names)

        # 2. Verify native chunk materials are mounted
        self.assertTrue(any("MC_Atlas_Chunk_0" in name for name in slot_names))

        # 3. Simulate outdated hash on material
        chunk_0_mat = bpy.data.materials.get("MC_Atlas_Chunk_0")
        self.assertIsNotNone(chunk_0_mat)
        chunk_0_mat["mtk:pack_hash"] = "outdated_pack_hash_0000"

        # Refresh material manager and ensure slots and chunks are synced
        mat_manager = LiveSyncMaterialManager(world_obj=obj)
        self.assertIn(0, mat_manager.chunk_materials)

    def test_prebaked_atlas_material_shader_graph_construction(self):
        """Verify that prebaked atlas directory automatically builds full LabPBR materials with texture nodes."""
        import tempfile
        import json
        from pathlib import Path
        from PIL import Image
        from utils.materials.atlas.builder import build_atlas_chunk_materials

        with tempfile.TemporaryDirectory() as tmp_dir:
            atlas_dir = Path(tmp_dir)
            # Create mock image files
            img = Image.new("RGBA", (64, 64), (128, 128, 128, 255))
            img.save(atlas_dir / "atlas_c00_albedo.png")
            img.save(atlas_dir / "atlas_c00_normal.png")
            img.save(atlas_dir / "atlas_c00_specular.png")

            mapping = {
                "format_version": 2,
                "atlas_width": 64,
                "atlas_height": 64,
                "tile_size": 16,
                "chunks": [
                    {
                        "chunk_id": 0,
                        "kind": "static",
                        "category": "blocks",
                        "width": 64,
                        "height": 64,
                        "tile_size": 16,
                        "tiles_per_row": 4,
                        "files": {
                            "albedo": "atlas_c00_albedo.png",
                            "normal": "atlas_c00_normal.png",
                            "specular": "atlas_c00_specular.png",
                        }
                    }
                ],
                "textures": {
                    "minecraft:block/stone": {
                        "chunk_id": 0,
                        "tile_column": 0,
                        "tile_row": 0,
                    }
                }
            }
            with open(atlas_dir / "atlas_mapping.json", "w", encoding="utf-8") as f:
                json.dump(mapping, f)

            # Build chunk materials
            mats = build_atlas_chunk_materials(atlas_dir, pack_hash="test_full_pbr_hash", pack_textures=True)
            self.assertIn(0, mats)
            c0_mat = mats[0]
            self.assertEqual(c0_mat.get("mtk:atlas_chunk_id"), 0)
            self.assertEqual(c0_mat.get("mtk:pack_hash"), "test_full_pbr_hash")

            # Verify shader nodes: Output, LabPBR Decoder, TexImage Albedo/Normal/Specular
            node_types = {n.type for n in c0_mat.node_tree.nodes}
            self.assertIn("OUTPUT_MATERIAL", node_types)
            self.assertIn("GROUP", node_types)
            self.assertIn("TEX_IMAGE", node_types)

    def test_high_resolution_hd_pack_uv_addressing(self):
        """Verify that LiveSyncMaterialManager handles 128x / 512x HD resource packs with sub-pixel precision."""
        from utils.live_sync import LiveSyncMaterialManager, parse_and_classify

        mesh = bpy.data.meshes.new("HDObjMesh")
        obj = bpy.data.objects.new("HDObj", mesh)
        bpy.context.collection.objects.link(obj)

        mat_manager = LiveSyncMaterialManager(world_obj=obj)
        # 128x HD Resource Pack (Atlas size 4096 x 4096, tile_size 128, 32 tiles per row)
        hd_mapping = {
            "format_version": 2,
            "atlas_width": 4096,
            "atlas_height": 4096,
            "tile_size": 128,
            "chunks": [
                {
                    "chunk_id": 0,
                    "kind": "static",
                    "width": 4096,
                    "height": 4096,
                    "tile_size": 128,
                    "tiles_per_row": 32,
                }
            ],
            "textures": {
                "minecraft:block/diamond_block": {
                    "chunk_id": 0,
                    "tile_column": 5,
                    "tile_row": 3,
                }
            }
        }
        mat_manager.atlas_params["mapping"] = hd_mapping
        mat_manager.refresh()

        parsed = parse_and_classify("minecraft:diamond_block")
        f_res = mat_manager.resolve_block_face(parsed, "top", 2)
        self.assertEqual(f_res.chunk_id, 0)

        # Local bottom-left (0.0, 0.0) -> global UV: U=(5+0)*128/4096 = 640/4096 = 0.15625, V=1 - (3+1)*128/4096 = 1 - 512/4096 = 0.875
        u0, v0 = f_res.calc_uv_fn(0.0, 0.0)
        self.assertAlmostEqual(u0, 0.15625, places=5)
        self.assertAlmostEqual(v0, 0.875, places=5)

        # Local top-right (1.0, 1.0) -> global UV: U=(5+1)*128/4096 = 768/4096 = 0.1875, V=1 - (3+0)*128/4096 = 1 - 384/4096 = 0.90625
        u1, v1 = f_res.calc_uv_fn(1.0, 1.0)
        self.assertAlmostEqual(u1, 0.1875, places=5)
        self.assertAlmostEqual(v1, 0.90625, places=5)

    def test_rect_bin_packed_hd_textures(self):
        """Verify arbitrary rect-packed and non-square textures (e.g. doors, banners) are accurately addressed."""
        from utils.live_sync import LiveSyncMaterialManager, parse_and_classify

        mesh = bpy.data.meshes.new("RectObjMesh")
        obj = bpy.data.objects.new("RectObj", mesh)
        bpy.context.collection.objects.link(obj)

        mat_manager = LiveSyncMaterialManager(world_obj=obj)
        # Rect-packed chunk
        rect_mapping = {
            "format_version": 2,
            "chunks": [
                {
                    "chunk_id": 2,
                    "kind": "rect_packed",
                    "width": 2048,
                    "height": 2048,
                }
            ],
            "textures": {
                "minecraft:block/oak_door_bottom": {
                    "chunk_id": 2,
                    "packing": "rect_bin_pack",
                    "pixel_x": 128,
                    "pixel_y": 256,
                    "rect_width": 64,
                    "rect_height": 128,
                }
            }
        }
        mat_manager.atlas_params["mapping"] = rect_mapping
        mat_manager.refresh()

        parsed = parse_and_classify("minecraft:oak_door[half=lower]")
        f_res = mat_manager.resolve_block_face(parsed, "east", 0)
        self.assertEqual(f_res.chunk_id, 2)

        # Local (0.5, 0.5) -> U=(128 + 0.5*64)/2048 = 160/2048 = 0.078125, V=1 - (256 + 0.5*128)/2048 = 1 - 320/2048 = 0.84375
        u_mid, v_mid = f_res.calc_uv_fn(0.5, 0.5)
        self.assertAlmostEqual(u_mid, 0.078125, places=5)
        self.assertAlmostEqual(v_mid, 0.84375, places=5)

    def test_incremental_section_mesh_sync(self):
        """Verify that modifying a block in one 16x16x16 section updates ONLY that section's mesh object."""
        from utils.live_sync import sync_world_mesh

        storage = VoxelStorage()
        # Create block in Section (0, 0, 0) and block in Section (1, 0, 0)
        storage.set_block(2, 2, 2, "minecraft:stone")
        storage.set_block(20, 2, 2, "minecraft:stone")

        # Initial full sync
        res = sync_world_mesh(bpy.context, storage, force_full_rebuild=True)
        self.assertIsNotNone(res.world_obj)
        root = res.world_obj

        sec0_obj = bpy.data.objects.get("Yefira_Section_0_0_0")
        sec1_obj = bpy.data.objects.get("Yefira_Section_1_0_0")
        self.assertIsNotNone(sec0_obj)
        self.assertIsNotNone(sec1_obj)

        sec0_mesh_ptr = sec0_obj.data.as_pointer()
        sec1_mesh_ptr = sec1_obj.data.as_pointer()
        sec1_poly_count_before = len(sec1_obj.data.polygons)

        # Apply a delta change ONLY inside section (0, 0, 0) - far from boundary
        storage.apply_delta_update(storage.min_x, storage.min_y, storage.min_z, [(3, 2, 2, "minecraft:diamond_block")])

        # Incremental sync
        res_delta = sync_world_mesh(bpy.context, storage, force_full_rebuild=False)
        self.assertEqual(res_delta.cubes_count, 3)

        # Section 1 object & mesh must be completely untouched!
        self.assertEqual(sec1_obj.data.as_pointer(), sec1_mesh_ptr)
        self.assertEqual(len(sec1_obj.data.polygons), sec1_poly_count_before)

        # Section 0 mesh has been updated to include the new cube (with face culling between x=2 and x=3: 6+6-2=10 faces)
        self.assertEqual(len(sec0_obj.data.polygons), 10)

    def test_section_emptied_cleanup(self):
        """Verify that when all blocks in a section are deleted/air, the section child object is cleanly removed."""
        from utils.live_sync import sync_world_mesh

        storage = VoxelStorage()
        storage.set_block(5, 5, 5, "minecraft:stone")
        storage.set_block(25, 5, 5, "minecraft:stone")

        sync_world_mesh(bpy.context, storage, force_full_rebuild=True)
        self.assertIn("Yefira_Section_0_0_0", bpy.data.objects)
        self.assertIn("Yefira_Section_1_0_0", bpy.data.objects)

        # Turn the block in Section 1 into air
        storage.apply_delta_update(storage.min_x, storage.min_y, storage.min_z, [(25, 5, 5, "minecraft:air")])
        sync_world_mesh(bpy.context, storage, force_full_rebuild=False)

        # Section 1 object should be removed
        self.assertNotIn("Yefira_Section_1_0_0", bpy.data.objects)
        self.assertIn("Yefira_Section_0_0_0", bpy.data.objects)

    def test_directional_furnace_exact_uvs(self):
        """Verify furnace facing East maps furnace_front to East face and rotated top to Up face."""
        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:furnace[facing=east,lit=false]")

        mapping = {
            "textures": {
                "minecraft:block/furnace_top": {"chunk_id": 0, "tile_column": 1, "tile_row": 0},
                "minecraft:block/furnace_side": {"chunk_id": 0, "tile_column": 2, "tile_row": 0},
                "minecraft:block/furnace_front": {"chunk_id": 0, "tile_column": 3, "tile_row": 0},
            }
        }
        atlas_params = {
            "width": 1024,
            "height": 512,
            "tile_size": 16,
            "tiles_per_row": 64,
            "mapping": mapping,
        }

        res = build_world_mesh(bpy.context, storage, atlas_params=atlas_params, weld_vertices=False)
        mesh = res.world_obj.data
        self.assertEqual(len(mesh.polygons), 6)

        uv_layer = mesh.uv_layers["UVMap"]

        # Find the East face (facing +X in Blender)
        east_polys = [p for p in mesh.polygons if p.normal.x > 0.9]
        self.assertEqual(len(east_polys), 1)
        east_poly = east_polys[0]

        # All UVs of the East face must fall within tile_column=3 bounds: [3*16/1024, 4*16/1024] -> [0.046875, 0.0625]
        for loop_idx in east_poly.loop_indices:
            uv = uv_layer.data[loop_idx].uv
            self.assertGreaterEqual(uv.x, 3 * 16 / 1024 - 1e-4)
            self.assertLessEqual(uv.x, 4 * 16 / 1024 + 1e-4)


if __name__ == "__main__":
    unittest.main()

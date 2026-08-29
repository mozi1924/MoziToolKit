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

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Bootstrap MoziToolKit package (also activates the isolated test sandbox)
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

import bpy

from utils.live_sync import (
    VoxelStorage,
    build_world_mesh,
    sync_world_mesh,
    apply_block_delta_to_world,
    WorldMeshBuildResult,
    clear_mesh_builder_caches,
)


class TestDirectMeshSync(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_homefile(use_empty=True)
        clear_mesh_builder_caches()

    def tearDown(self):
        bpy.ops.wm.read_homefile(use_empty=True)
        clear_mesh_builder_caches()

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

        # Check source texture key attribute exists on faces
        self.assertIn("mtk_source_texture_key", mesh.attributes)
        first_key = mesh.attributes["mtk_source_texture_key"].data[0].value
        if isinstance(first_key, bytes):
            first_key = first_key.decode("utf-8")
        self.assertEqual(first_key, "minecraft:block/stone")

    def test_section_slots_follow_compact_special_chunk_indices(self):
        """A sparse banner chunk must not become empty slots or a block-material face."""
        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:red_banner[rotation=0]")

        atlas_params = {
            "mapping": {
                "chunks": [
                    {"chunk_id": 0, "category": "blocks", "kind": "static", "width": 512, "height": 512, "tile_size": 16},
                    {"chunk_id": 7, "category": "banner_patterns", "kind": "static", "width": 256, "height": 128, "packing": "rect_bin_pack"},
                ],
                "textures": {
                    "minecraft:block/oak_planks": {"chunk_id": 0, "tile_column": 0, "tile_row": 0, "category": "blocks"},
                    "minecraft:entity/banner/banner_base": {
                        "chunk_id": 7, "pixel_x": 0, "pixel_y": 0,
                        "rect_width": 64, "rect_height": 64, "category": "banner_patterns",
                    },
                },
            }
        }
        for cid in [0, 7]:
            m = bpy.data.materials.new(name=f"MC_Atlas_Chunk_{cid}")
            m["mtk:atlas_chunk_id"] = cid

        result = sync_world_mesh(bpy.context, storage, atlas_params=atlas_params, force_full_rebuild=True)
        section = next(child for child in result.world_obj.children if "_Section_" in child.name)
        self.assertEqual(len(section.data.materials), 2)
        self.assertTrue(all(material is not None for material in section.data.materials))

        source_key = section.data.attributes["mtk_source_texture_key"]
        banner_poly = next(
            poly for poly in section.data.polygons
            if (
                source_key.data[poly.index].value.decode("utf-8")
                if isinstance(source_key.data[poly.index].value, bytes)
                else source_key.data[poly.index].value
            ) == "minecraft:entity/banner/banner_base"
        )
        banner_mat = section.data.materials[banner_poly.material_index]
        self.assertEqual(banner_mat["mtk:atlas_chunk_id"], 7)

    def test_section_slots_for_skulls_and_end_portal_entity_chunks(self):
        """Skulls, heads, and end portal must address entities_chunk (chunk 8), never falling back to blocks_chunk_001 (chunk 0)."""
        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:skeleton_skull[rotation=0]")
        storage.set_block(1, 0, 0, "minecraft:end_portal")
        storage.set_block(2, 0, 0, "minecraft:dragon_head[rotation=0]")

        atlas_params = {
            "mapping": {
                "chunks": [
                    {"chunk_id": 0, "category": "blocks", "kind": "static", "width": 512, "height": 512, "tile_size": 16},
                    {"chunk_id": 8, "category": "entities", "kind": "static", "width": 512, "height": 512, "packing": "rect_bin_pack"},
                ],
                "textures": {
                    "minecraft:entity/skeleton/skeleton": {"chunk_id": 8, "pixel_x": 0, "pixel_y": 0, "rect_width": 64, "rect_height": 32, "category": "entities"},
                    "minecraft:entity/end_portal": {"chunk_id": 8, "pixel_x": 0, "pixel_y": 32, "rect_width": 16, "rect_height": 16, "category": "entities"},
                    "minecraft:entity/enderdragon/dragon": {"chunk_id": 8, "pixel_x": 64, "pixel_y": 0, "rect_width": 128, "rect_height": 64, "category": "entities"},
                },
            }
        }
        for cid in [0, 8]:
            m = bpy.data.materials.new(name=f"MC_Atlas_Chunk_{cid}")
            m["mtk:atlas_chunk_id"] = cid

        result = sync_world_mesh(bpy.context, storage, atlas_params=atlas_params, force_full_rebuild=True)
        section = next(child for child in result.world_obj.children if "_Section_" in child.name)
        self.assertTrue(any(mat and mat.get("mtk:atlas_chunk_id") == 8 for mat in section.data.materials))

        source_key = section.data.attributes["mtk_source_texture_key"]
        chunk_id_attr = section.data.attributes["mtk_atlas_chunk_id"]

        def _get_key(poly_idx):
            v = source_key.data[poly_idx].value
            return v.decode("utf-8") if isinstance(v, bytes) else v

        skull_polys = [p for p in section.data.polygons if _get_key(p.index) == "minecraft:entity/skeleton/skeleton"]
        portal_polys = [p for p in section.data.polygons if _get_key(p.index) == "minecraft:entity/end_portal"]
        dragon_polys = [p for p in section.data.polygons if _get_key(p.index) == "minecraft:entity/enderdragon/dragon"]

        self.assertGreater(len(skull_polys), 0, "Skeleton skull polygons missing")
        self.assertGreater(len(portal_polys), 0, "End portal polygons missing")
        self.assertGreater(len(dragon_polys), 0, "Dragon head polygons missing")

        for poly in skull_polys:
            mat = section.data.materials[poly.material_index]
            self.assertEqual(mat["mtk:atlas_chunk_id"], 8, "Skeleton skull assigned to wrong chunk material")
            self.assertEqual(chunk_id_attr.data[poly.index].value, 8)

        for poly in portal_polys:
            mat = section.data.materials[poly.material_index]
            self.assertEqual(mat["mtk:atlas_chunk_id"], 8, "End portal assigned to wrong chunk material")
            self.assertEqual(chunk_id_attr.data[poly.index].value, 8)

        for poly in dragon_polys:
            mat = section.data.materials[poly.material_index]
            self.assertEqual(mat["mtk:atlas_chunk_id"], 8, "Dragon head assigned to wrong chunk material")
            self.assertEqual(chunk_id_attr.data[poly.index].value, 8)

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

        for cid in [0, 1]:
            m = bpy.data.materials.new(name=f"MC_Atlas_Chunk_{cid}")
            m["mtk:atlas_chunk_id"] = cid

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

        for cid in [0]:
            m = bpy.data.materials.new(name=f"MC_Atlas_Chunk_{cid}")
            m["mtk:atlas_chunk_id"] = cid

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

        # 3. Simulate outdated hash on material - must reject outdated material
        chunk_0_mat = bpy.data.materials.get("MC_Atlas_Chunk_0")
        self.assertIsNotNone(chunk_0_mat)
        chunk_0_mat["mtk:pack_hash"] = "outdated_pack_hash_0000"

        # Refresh material manager and ensure outdated material is rejected
        mat_manager = LiveSyncMaterialManager(world_obj=obj)
        self.assertNotIn(0, mat_manager.chunk_materials)

        # Restoring matching hash allows loading
        chunk_0_mat["mtk:pack_hash"] = mat_manager._target_pack_hash
        mat_manager.refresh()
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

        sec0_obj = bpy.data.objects.get("Yefira_World_Section_0_0_0")
        sec1_obj = bpy.data.objects.get("Yefira_World_Section_1_0_0")
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
        self.assertIn("Yefira_World_Section_0_0_0", bpy.data.objects)
        self.assertIn("Yefira_World_Section_1_0_0", bpy.data.objects)

        # Turn the block in Section 1 into air
        storage.apply_delta_update(storage.min_x, storage.min_y, storage.min_z, [(25, 5, 5, "minecraft:air")])
        sync_world_mesh(bpy.context, storage, force_full_rebuild=False)

        # Section 1 object should be removed
        self.assertNotIn("Yefira_World_Section_1_0_0", bpy.data.objects)
        self.assertIn("Yefira_World_Section_0_0_0", bpy.data.objects)

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

    def test_material_category_lazy_loading(self):
        """Verify that UI/items chunks are NOT loaded into scene by default, and loaded on-demand when needed."""
        from utils.live_sync.material_manager import LiveSyncMaterialManager
        from utils.live_sync.classifier import parse_and_classify

        mapping = {
            "chunks": [
                {"chunk_id": 0, "category": "blocks", "kind": "static", "width": 512, "height": 512, "tile_size": 16},
                {"chunk_id": 1, "category": "blocks", "kind": "animation", "width": 512, "height": 512, "tile_size": 16},
                {"chunk_id": 2, "category": "items", "kind": "static", "width": 512, "height": 512, "tile_size": 16},
                {"chunk_id": 3, "category": "gui", "kind": "static", "width": 512, "height": 512, "tile_size": 16},
            ],
            "textures": {
                "minecraft:block/stone": {"chunk_id": 0, "category": "blocks", "tile_column": 0, "tile_row": 0},
                "minecraft:item/diamond_sword": {"chunk_id": 2, "category": "items", "tile_column": 0, "tile_row": 0},
                "minecraft:gui/widgets": {"chunk_id": 3, "category": "gui", "tile_column": 0, "tile_row": 0},
            },
            "animations": [
                {
                    "name": "minecraft:block/water_still",
                    "texture_key": "minecraft:block/water_still",
                    "category": "blocks",
                    "chunk_id": 1,
                    "pixel_x": 0,
                    "frame_width": 16,
                    "frame_height": 16,
                    "frame_count": 32,
                }
            ]
        }

        # Clear any preexisting test materials
        for m in list(bpy.data.materials):
            if m.name.startswith("MC_Atlas_Chunk_"):
                bpy.data.materials.remove(m, do_unlink=True)

        for cid in [0, 1, 2, 3]:
            m = bpy.data.materials.new(name=f"MC_Atlas_Chunk_{cid}")
            m["mtk:atlas_chunk_id"] = cid

        world_obj = bpy.data.objects.new("TestWorld", bpy.data.meshes.new("TestWorldMesh"))
        bpy.context.collection.objects.link(world_obj)

        mat_mgr = LiveSyncMaterialManager(world_obj=world_obj, atlas_params={"mapping": mapping})

        # By default, only category 'blocks' chunks (0 and 1) should be loaded
        self.assertIn(0, mat_mgr.chunk_materials)
        self.assertIn(1, mat_mgr.chunk_materials)
        # Chunks 2 (items) and 3 (gui) must NOT be loaded yet!
        self.assertNotIn(2, mat_mgr.chunk_materials)
        self.assertNotIn(3, mat_mgr.chunk_materials)

        # Now resolve a block that uses an item texture (chunk 2)
        parsed_item = parse_and_classify("minecraft:diamond_sword")
        res_item = mat_mgr.resolve_block_face(parsed_item, "north", 0)
        self.assertEqual(res_item.chunk_id, 2)

        # Chunk 2 must now be loaded on-demand, while chunk 3 (gui) STILL remains unloaded!
        self.assertIn(2, mat_mgr.chunk_materials)
        self.assertNotIn(3, mat_mgr.chunk_materials)

        # Cleanup
        bpy.data.objects.remove(world_obj, do_unlink=True)

    def test_animated_materials_frame_0_addressing(self):
        """Verify that animated textures (water, lava, sea_lantern, fire, etc.) address Frame 0 in animation chunk."""
        from utils.live_sync.material_manager import LiveSyncMaterialManager
        from utils.live_sync.classifier import parse_and_classify

        mapping = {
            "chunks": [
                {"chunk_id": 0, "category": "blocks", "kind": "static", "width": 512, "height": 512, "tile_size": 16},
                {"chunk_id": 1, "category": "blocks", "kind": "animation", "width": 512, "height": 512, "tile_size": 16},
            ],
            "textures": {
                "minecraft:block/stone": {"chunk_id": 0, "category": "blocks", "tile_column": 0, "tile_row": 0},
                # Even if mapping has a stale static placeholder entry for water:
                "minecraft:block/water_still": {"chunk_id": 0, "category": "blocks", "tile_column": 1, "tile_row": 0},
            },
            "animations": [
                {
                    "name": "minecraft:block/water_still",
                    "texture_key": "minecraft:block/water_still",
                    "category": "blocks",
                    "chunk_id": 1,
                    "pixel_x": 32,
                    "frame_width": 16,
                    "frame_height": 16,
                    "frame_count": 32,
                },
                {
                    "name": "minecraft:block/lava_still",
                    "texture_key": "minecraft:block/lava_still",
                    "category": "blocks",
                    "chunk_id": 1,
                    "pixel_x": 48,
                    "frame_width": 16,
                    "frame_height": 16,
                    "frame_count": 32,
                },
                {
                    "name": "minecraft:block/sea_lantern",
                    "texture_key": "minecraft:block/sea_lantern",
                    "category": "blocks",
                    "chunk_id": 1,
                    "pixel_x": 64,
                    "frame_width": 16,
                    "frame_height": 16,
                    "frame_count": 5,
                },
            ]
        }

        mat_mgr = LiveSyncMaterialManager(atlas_params={"mapping": mapping})

        # Test water addressing
        parsed_water = parse_and_classify("minecraft:water")
        res_water = mat_mgr.resolve_block_face(parsed_water, "up", 2)
        self.assertEqual(res_water.chunk_id, 1, "Water must resolve to animation chunk ID 1, not static chunk 0")

        # Evaluate UVs on Frame 0:
        # In Minecraft space: top-left (0, 0), bottom-right (1, 1).
        # In Blender space: u_local in [0, 1], v_local in [0, 1].
        # Frame 0 spans U in [32/512, 48/512] -> [0.0625, 0.09375]
        # Frame 0 spans V in [1.0 - 16/512, 1.0] -> [0.96875, 1.0]
        uv_bl = res_water.calc_uv_fn(0.0, 0.0) # bottom-left in Blender
        uv_tr = res_water.calc_uv_fn(1.0, 1.0) # top-right in Blender

        self.assertAlmostEqual(uv_bl[0], 32.0 / 512.0, places=5)
        self.assertAlmostEqual(uv_bl[1], 1.0 - 16.0 / 512.0, places=5)
        self.assertAlmostEqual(uv_tr[0], 48.0 / 512.0, places=5)
        self.assertAlmostEqual(uv_tr[1], 1.0, places=5)

        # Test sea_lantern addressing
        parsed_sl = parse_and_classify("minecraft:sea_lantern")
        res_sl = mat_mgr.resolve_block_face(parsed_sl, "north", 4)
        self.assertEqual(res_sl.chunk_id, 1, "Sea lantern must resolve to animation chunk ID 1")
        uv_sl_bl = res_sl.calc_uv_fn(0.0, 0.0)
        self.assertAlmostEqual(uv_sl_bl[0], 64.0 / 512.0, places=5)
        self.assertAlmostEqual(uv_sl_bl[1], 1.0 - 16.0 / 512.0, places=5)

    def test_mesh_face_attributes_written(self):
        """Verify that BMesh generation creates and populates all shader face attributes."""
        mapping = {
            "chunks": [
                {"chunk_id": 0, "category": "blocks", "kind": "static", "width": 512, "height": 512, "tile_size": 16},
                {"chunk_id": 1, "category": "blocks", "kind": "animation", "width": 512, "height": 512, "tile_size": 16},
            ],
            "textures": {
                "minecraft:block/stone": {"chunk_id": 0, "category": "blocks", "tile_column": 0, "tile_row": 0},
                "minecraft:block/grass_block_top": {"chunk_id": 0, "category": "blocks", "tile_column": 1, "tile_row": 0, "default_tint_weight": 1.0},
                "minecraft:block/grass_block_side": {"chunk_id": 0, "category": "blocks", "tile_column": 2, "tile_row": 0},
                "minecraft:block/dirt": {"chunk_id": 0, "category": "blocks", "tile_column": 3, "tile_row": 0},
            },
            "animations": [
                {
                    "name": "minecraft:block/water_still",
                    "texture_key": "minecraft:block/water_still",
                    "category": "blocks",
                    "chunk_id": 1,
                    "pixel_x": 32,
                    "frame_width": 16,
                    "frame_height": 16,
                    "frame_count": 32,
                    "frametime": 2,
                    "interpolate": True,
                    "default_tint_weight": 1.0,
                },
            ]
        }

        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:stone")
        storage.set_block(1, 0, 0, "minecraft:grass_block")
        storage.set_block(2, 0, 0, "minecraft:water")

        res = build_world_mesh(bpy.context, storage, atlas_params={"mapping": mapping})
        mesh = res.world_obj.data

        # 1. Assert all 6 face attributes exist on the mesh
        expected_attrs = [
            ("mtk_uv_rotation", "FLOAT"),
            ("mtk_anim_timing", "FLOAT_COLOR"),
            ("mtk_anim_frame_size", "FLOAT_COLOR"),
            ("mtk_uv_tiling_transform", "FLOAT_COLOR"),
            ("mtk_biome_tint_data", "FLOAT_COLOR"),
            ("mtk_biome_tint_color", "FLOAT_COLOR"),
        ]
        for attr_name, expected_type in expected_attrs:
            self.assertIn(attr_name, mesh.attributes, f"Mesh must contain face attribute '{attr_name}'")
            attr = mesh.attributes[attr_name]
            self.assertEqual(attr.domain, "FACE", f"Attribute '{attr_name}' must be on FACE domain")
            self.assertEqual(attr.data_type, expected_type, f"Attribute '{attr_name}' must be data_type {expected_type}")
            self.assertEqual(len(attr.data), len(mesh.polygons), f"Attribute '{attr_name}' must match polygon count")

        # 2. Check timing attribute values
        timing_attr = mesh.attributes["mtk_anim_timing"]
        tint_data_attr = mesh.attributes["mtk_biome_tint_data"]
        tint_color_attr = mesh.attributes["mtk_biome_tint_color"]

        found_animated_water = False
        found_tinted_grass = False
        found_untinted_stone = False

        for poly_idx in range(len(mesh.polygons)):
            timing = list(timing_attr.data[poly_idx].color)
            tint_data = list(tint_data_attr.data[poly_idx].color)
            tint_col = list(tint_color_attr.data[poly_idx].color)

            # Water face: Total Frames = 32, Frametime = 2, Interpolate = 1.0
            if timing[0] == 32.0 and timing[1] == 2.0 and timing[2] == 1.0:
                found_animated_water = True
                self.assertEqual(tint_data[2], 1.0, "Water face must have Tint Weight == 1.0")

            # Tinted grass face: Tint Weight == 1.0, green tint
            if tint_data[2] == 1.0 and abs(tint_col[0] - 0.35) < 0.01:
                found_tinted_grass = True

            # Untinted stone face: Tint Weight == 0.0, White tint color, Total Frames == 1.0
            if tint_data[2] == 0.0 and timing[0] == 1.0 and abs(tint_col[0] - 1.0) < 0.01:
                found_untinted_stone = True

        self.assertTrue(found_animated_water, "Mesh must contain water face with correct animation timing attribute")
        self.assertTrue(found_tinted_grass, "Mesh must contain grass face with correct biome tint attribute")
        self.assertTrue(found_untinted_stone, "Mesh must contain stone face with default attributes")

    def test_directional_block_uv_rotation_attribute_is_zero(self):
        """Verify that directional blocks have mtk_uv_rotation=0.0 to prevent shader double-rotation."""
        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:furnace[facing=east,lit=false]")
        storage.set_block(1, 0, 0, "minecraft:piston[facing=up]")
        storage.set_block(2, 0, 0, "minecraft:oak_log[axis=x]")

        res = build_world_mesh(bpy.context, storage)
        mesh = res.world_obj.data

        self.assertIn("mtk_uv_rotation", mesh.attributes)
        rot_attr = mesh.attributes["mtk_uv_rotation"]

        # All solid/directional block faces must have mtk_uv_rotation == 0.0
        for poly_idx in range(len(mesh.polygons)):
            rot_val = rot_attr.data[poly_idx].value
            self.assertEqual(rot_val, 0.0, f"Polygon {poly_idx} must have mtk_uv_rotation == 0.0 (no double rotation)")

    def test_grass_block_and_translucent_culling(self):
        """Test Geometry Nodes compatible culling for grass blocks, translucent blocks, and fluids."""
        # 1. Two adjacent grass blocks (6 + 6 - 2 = 10 faces)
        s1 = VoxelStorage()
        s1.set_block(0, 0, 0, "minecraft:grass_block")
        s1.set_block(1, 0, 0, "minecraft:grass_block")
        r1 = build_world_mesh(bpy.context, s1)
        self.assertEqual(len(r1.world_obj.data.polygons), 10, "2 adjacent grass blocks must have exactly 10 faces")

        # 2. 3x3x3 solid grass blocks (6 * 9 = 54 faces)
        s2 = VoxelStorage()
        for x in range(3):
            for y in range(3):
                for z in range(3):
                    s2.set_block(x, y, z, "minecraft:grass_block")
        r2 = build_world_mesh(bpy.context, s2)
        self.assertEqual(len(r2.world_obj.data.polygons), 54, "3x3x3 solid grass blocks must have exactly 54 faces")

        # 3. Grass block touching stone (6 + 6 - 2 = 10 faces)
        s3 = VoxelStorage()
        s3.set_block(0, 0, 0, "minecraft:grass_block")
        s3.set_block(0, -1, 0, "minecraft:stone")
        r3 = build_world_mesh(bpy.context, s3)
        self.assertEqual(len(r3.world_obj.data.polygons), 10, "Grass block touching stone must have touching faces culled")

        # 4. Two adjacent glass blocks (6 + 6 - 2 = 10 faces)
        s4 = VoxelStorage()
        s4.set_block(0, 0, 0, "minecraft:glass")
        s4.set_block(1, 0, 0, "minecraft:glass")
        r4 = build_world_mesh(bpy.context, s4)
        self.assertEqual(len(r4.world_obj.data.polygons), 10, "Adjacent same translucent blocks must cull internal faces")

        # 5. Two adjacent leaves blocks (6 + 6 - 2 = 10 faces)
        s5 = VoxelStorage()
        s5.set_block(0, 0, 0, "minecraft:oak_leaves")
        s5.set_block(0, 1, 0, "minecraft:oak_leaves")
        r5 = build_world_mesh(bpy.context, s5)
        self.assertEqual(len(r5.world_obj.data.polygons), 10, "Adjacent same leaves must cull internal faces")

        # 6. Two adjacent water blocks (6 + 6 - 2 = 10 faces)
        s6 = VoxelStorage()
        s6.set_block(0, 0, 0, "minecraft:water")
        s6.set_block(1, 0, 0, "minecraft:water")
        r6 = build_world_mesh(bpy.context, s6)
        self.assertEqual(len(r6.world_obj.data.polygons), 10, "Adjacent fluids must cull internal faces")

    def test_empty_root_world_container_and_renaming(self):
        """Verify root object is an Empty container and renaming root propagates prefix to child sections."""
        # 1. Operator creation
        res_op = bpy.ops.mozi.add_yefira_world(name="Custom_World")
        self.assertEqual(res_op, {'FINISHED'})

        custom_root = bpy.data.objects.get("Custom_World")
        self.assertIsNotNone(custom_root)
        self.assertEqual(custom_root.type, 'EMPTY')
        self.assertTrue(custom_root.get("mtk:is_yefira_world"))

        # 2. Sync world geometry under custom empty root
        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:stone")
        storage.set_block(16, 0, 0, "minecraft:oak_planks")

        res_sync = sync_world_mesh(bpy.context, storage, target_obj=custom_root, force_full_rebuild=True)
        self.assertEqual(res_sync.world_obj.name, "Custom_World")
        self.assertEqual(res_sync.world_obj.type, 'EMPTY')

        sec0 = bpy.data.objects.get("Custom_World_Section_0_0_0")
        sec1 = bpy.data.objects.get("Custom_World_Section_1_0_0")
        self.assertIsNotNone(sec0)
        self.assertIsNotNone(sec1)
        self.assertEqual(sec0.parent, custom_root)
        self.assertEqual(sec1.parent, custom_root)

        # 3. Rename root object and verify propagation on subsequent sync
        custom_root.name = "My_Castle"
        self.assertEqual(custom_root.name, "My_Castle")

        # Delta sync
        storage.apply_delta_update(0, 0, 0, [(1, 0, 0, "minecraft:glass")])
        res_delta = apply_block_delta_to_world(
            context=bpy.context,
            storage=storage,
            changes=[(1, 0, 0, "minecraft:glass")],
            target_obj=custom_root,
        )

        renamed_sec0 = bpy.data.objects.get("My_Castle_Section_0_0_0")
        renamed_sec1 = bpy.data.objects.get("My_Castle_Section_1_0_0")
        self.assertIsNotNone(renamed_sec0, "Section 0 must be renamed to My_Castle_Section_0_0_0")
        self.assertIsNotNone(renamed_sec1, "Section 1 must be renamed to My_Castle_Section_1_0_0")
        self.assertIsNone(bpy.data.objects.get("Custom_World_Section_0_0_0"))
        self.assertIsNone(bpy.data.objects.get("Custom_World_Section_1_0_0"))

    def test_immediate_depsgraph_rename_propagation(self):
        """Verify that renaming an empty container immediately updates all child sections and meshes via depsgraph handler."""
        res_op = bpy.ops.mozi.add_yefira_world(name="Base_World")
        self.assertEqual(res_op, {'FINISHED'})

        root = bpy.data.objects.get("Base_World")
        self.assertIsNotNone(root)

        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:stone")
        storage.set_block(16, 0, 0, "minecraft:oak_planks")
        sync_world_mesh(bpy.context, storage, target_obj=root, force_full_rebuild=True)

        sec0 = bpy.data.objects.get("Base_World_Section_0_0_0")
        self.assertIsNotNone(sec0)
        self.assertEqual(sec0.data.name, "Mesh_Base_World_Section_0_0_0")

        # Rename root object directly in Blender (as user does in Outliner or Properties panel)
        root.name = "Fortress"
        # Trigger depsgraph update
        bpy.context.view_layer.update()

        # Check that children and their meshes were immediately renamed
        new_sec0 = bpy.data.objects.get("Fortress_Section_0_0_0")
        new_sec1 = bpy.data.objects.get("Fortress_Section_1_0_0")
        self.assertIsNotNone(new_sec0)
        self.assertIsNotNone(new_sec1)
        self.assertEqual(new_sec0.data.name, "Mesh_Fortress_Section_0_0_0")
        self.assertEqual(new_sec1.data.name, "Mesh_Fortress_Section_1_0_0")
        self.assertIsNone(bpy.data.objects.get("Base_World_Section_0_0_0"))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

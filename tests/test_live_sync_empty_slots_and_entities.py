"""
Test Suite for MoziToolKit Live Sync:
- Zero Empty Material Slots on World Mesh Object
- Accurate 3D Model Baking for Chests, Banners, Beds
- Entity Texture Resolution and Non-Block Category Isolation (No Map Decoration Pollution)
"""

import unittest
from pathlib import Path
import bpy
import bmesh
from mathutils import Vector

from utils.live_sync.material_manager import LiveSyncMaterialManager, PROP_ATLAS_CHUNK_ID, PROP_PACK_HASH
from utils.live_sync.classifier import parse_and_classify, atlas_lookup_keys, BlockTypeEnum
from utils.mc_baker import StateBaker, get_shared_state_baker
from utils.mc_baker.model_parser import ModelParser


class TestLiveSyncEmptySlotsAndEntities(unittest.TestCase):

    def setUp(self):
        # Create a fresh test mesh object
        self.mesh = bpy.data.meshes.new(name="Test_World_Mesh")
        self.obj = bpy.data.objects.new(name="Test_World_Object", object_data=self.mesh)
        bpy.context.collection.objects.link(self.obj)

    def tearDown(self):
        if self.obj and self.obj.name in bpy.data.objects:
            bpy.data.objects.remove(self.obj, do_unlink=True)
        if self.mesh and self.mesh.name in bpy.data.meshes:
            bpy.data.meshes.remove(self.mesh, do_unlink=True)

    def test_zero_empty_material_slots(self):
        """Verify that world mesh never receives None / empty material slots even with non-contiguous chunk IDs."""
        atlas_params = {
            "mapping": {
                "chunks": [
                    {"chunk_id": 0, "category": "blocks", "width": 512, "height": 512, "tile_size": 16},
                    {"chunk_id": 1, "category": "blocks", "kind": "animation", "width": 16, "height": 512},
                    {"chunk_id": 5, "category": "chest", "width": 512, "height": 512, "packing": "rect_bin_pack"},
                    {"chunk_id": 12, "category": "map_decorations", "width": 256, "height": 256},
                ],
                "textures": {
                    "minecraft:block/stone": {"chunk_id": 0, "tile_column": 0, "tile_row": 0, "category": "blocks"},
                    "minecraft:entity/chest/normal": {"chunk_id": 5, "pixel_x": 0, "pixel_y": 0, "rect_width": 64, "rect_height": 64, "category": "chest"},
                    "minecraft:map/decorations/banner_white": {"chunk_id": 12, "pixel_x": 0, "pixel_y": 0, "rect_width": 8, "rect_height": 8, "category": "map_decorations"},
                }
            }
        }

        mgr = LiveSyncMaterialManager(world_obj=self.obj, atlas_params=atlas_params)

        # Verify no empty / None slots were appended to obj.data.materials
        for idx, slot_mat in enumerate(self.obj.data.materials):
            self.assertIsNotNone(slot_mat, f"Slot {idx} is None (empty material slot)!")

        # Every atlas category usable by a streamed block model is prepared
        # before geometry generation.  Map decorations remain excluded.
        self.assertIn(0, mgr.chunk_materials)
        self.assertIn(1, mgr.chunk_materials)
        self.assertIn(5, mgr.chunk_materials)
        self.assertNotIn(12, mgr.chunk_materials)  # map_decorations must NOT be preloaded

        # Slot count should exactly match number of loaded chunk materials
        self.assertEqual(len(self.obj.data.materials), len(mgr.chunk_materials))

        # A previously loaded special-model chunk retains a valid slot.
        slot_5 = mgr.get_slot_for_chunk(5)
        self.assertGreaterEqual(slot_5, 0)
        self.assertIn(5, mgr.chunk_materials)
        self.assertEqual(len(self.obj.data.materials), len(mgr.chunk_materials))
        for idx, slot_mat in enumerate(self.obj.data.materials):
            self.assertIsNotNone(slot_mat, f"Slot {idx} became None after on-demand load!")

    def test_non_block_category_isolation(self):
        """Verify that map_decorations and non-block textures do NOT pollute short-name block lookups."""
        atlas_params = {
            "mapping": {
                "chunks": [
                    {"chunk_id": 0, "category": "blocks", "width": 512, "height": 512, "tile_size": 16},
                    {"chunk_id": 12, "category": "map_decorations", "width": 256, "height": 256},
                ],
                "textures": {
                    "minecraft:block/white_wool": {"chunk_id": 0, "tile_column": 1, "tile_row": 1, "category": "blocks"},
                    "minecraft:map/decorations/banner_white": {"chunk_id": 12, "pixel_x": 0, "pixel_y": 0, "rect_width": 8, "rect_height": 8, "category": "map_decorations"},
                }
            }
        }

        mgr = LiveSyncMaterialManager(world_obj=self.obj, atlas_params=atlas_params)

        # Lookup banner - it should resolve to block/wool or default block chunk (chunk 0), NEVER map_decorations (chunk 12)
        parsed = parse_and_classify("minecraft:white_banner[rotation=0]")
        resolved = mgr.resolve_block_face(parsed, face_name="north", face_index=5)

        self.assertNotEqual(resolved.chunk_id, 12, "White banner was mistakenly mapped to map_decorations chunk 12!")
        self.assertEqual(resolved.chunk_id, 0, "White banner should resolve to block chunk 0!")

    def test_chest_model_baking(self):
        """Verify that chests bake accurate 3D multipart models (lid + body + latch) and not 1x1x1 cubes."""
        baker = StateBaker()

        # 1. Single Chest Facing North
        baked_north = baker.bake_block_state("minecraft:chest[facing=north,type=single,waterlogged=false]")
        self.assertFalse(baked_north.is_cube, "Chest should not be classified as a full cube!")
        self.assertEqual(len(baked_north.elements), 3, "Chest should have 3 distinct 3D elements (lid, body, and latch)!")

        # Verify Lid element (element 0)
        lid_elem = baked_north.elements[0]
        lid_verts = [v for face in lid_elem.faces.values() for v in face.vertices]
        self.assertAlmostEqual(min(v[0] for v in lid_verts), 1.0 / 16.0, places=2)
        self.assertAlmostEqual(max(v[0] for v in lid_verts), 15.0 / 16.0, places=2)
        self.assertAlmostEqual(min(v[1] for v in lid_verts), 9.0 / 16.0, places=2)
        self.assertAlmostEqual(max(v[1] for v in lid_verts), 14.0 / 16.0, places=2)
        self.assertAlmostEqual(min(v[2] for v in lid_verts), 1.0 / 16.0, places=2)
        self.assertAlmostEqual(max(v[2] for v in lid_verts), 15.0 / 16.0, places=2)

        # Verify Body element (element 1)
        body_elem = baked_north.elements[1]
        body_verts = [v for face in body_elem.faces.values() for v in face.vertices]
        self.assertAlmostEqual(min(v[0] for v in body_verts), 1.0 / 16.0, places=2)
        self.assertAlmostEqual(max(v[0] for v in body_verts), 15.0 / 16.0, places=2)
        self.assertAlmostEqual(min(v[1] for v in body_verts), 0.0, places=2)
        self.assertAlmostEqual(max(v[1] for v in body_verts), 10.0 / 16.0, places=2)
        self.assertAlmostEqual(min(v[2] for v in body_verts), 1.0 / 16.0, places=2)
        self.assertAlmostEqual(max(v[2] for v in body_verts), 15.0 / 16.0, places=2)

        # Verify Latch element (element 2)
        latch_elem = baked_north.elements[2]
        latch_verts = [v for face in latch_elem.faces.values() for v in face.vertices]
        self.assertAlmostEqual(min(v[0] for v in latch_verts), 7.0 / 16.0, places=2)
        self.assertAlmostEqual(max(v[0] for v in latch_verts), 9.0 / 16.0, places=2)
        self.assertAlmostEqual(min(v[1] for v in latch_verts), 7.0 / 16.0, places=2)
        self.assertAlmostEqual(max(v[1] for v in latch_verts), 11.0 / 16.0, places=2)
        self.assertAlmostEqual(min(v[2] for v in latch_verts), 0.0, places=2)
        self.assertAlmostEqual(max(v[2] for v in latch_verts), 1.0 / 16.0, places=2)

        # Verify chest texture key is entity texture
        for face in body_elem.faces.values():
            self.assertEqual(face.texture, "minecraft:entity/chest/normal")

        # 2. Trapped Chest and Ender Chest
        trapped = baker.bake_block_state("minecraft:trapped_chest[facing=south,type=single]")
        self.assertEqual(trapped.elements[0].faces["up"].texture, "minecraft:entity/chest/trapped")

        ender = baker.bake_block_state("minecraft:ender_chest[facing=west]")
        self.assertEqual(ender.elements[0].faces["up"].texture, "minecraft:entity/chest/ender")

    def test_banner_model_baking(self):
        """Verify that standing and wall banners bake 3D multipart models with correct rotation."""
        baker = StateBaker()

        # 1. Standing Banner with rotation
        standing = baker.bake_block_state("minecraft:red_banner[rotation=4]")
        self.assertFalse(standing.is_cube)
        self.assertEqual(len(standing.elements), 3, "Standing banner should have cloth, crossbar, and pole elements!")

        # Cloth is element 0 so it takes priority in the 6-face summary; uses canonical banner_base.
        cloth_elem = standing.elements[0]
        self.assertEqual(cloth_elem.faces["north"].texture, "minecraft:entity/banner/banner_base")

        # 2. Wall Banner facing south
        wall = baker.bake_block_state("minecraft:blue_wall_banner[facing=south]")
        self.assertFalse(wall.is_cube)
        self.assertEqual(len(wall.elements), 2, "Wall banner should have cloth and crossbar elements!")
        self.assertEqual(wall.elements[0].faces["north"].texture, "minecraft:entity/banner/banner_base")

    def test_special_model_chunks_are_bound_before_face_generation(self):
        """Chest/banner model faces must select their own atlas chunks, never chunk 0/1 fallbacks."""
        atlas_params = {
            "mapping": {
                "chunks": [
                    {"chunk_id": 0, "category": "blocks", "width": 512, "height": 512, "tile_size": 16},
                    {"chunk_id": 1, "category": "blocks", "kind": "animation", "width": 16, "height": 512},
                    {"chunk_id": 5, "category": "chest", "width": 256, "height": 128, "packing": "rect_bin_pack"},
                    {"chunk_id": 6, "category": "shulker_boxes", "width": 256, "height": 128, "packing": "rect_bin_pack"},
                    {"chunk_id": 7, "category": "banner_patterns", "width": 256, "height": 128, "packing": "rect_bin_pack"},
                    {"chunk_id": 12, "category": "map_decorations", "width": 256, "height": 256},
                ],
                "textures": {
                    "minecraft:block/oak_planks": {"chunk_id": 0, "tile_column": 0, "tile_row": 0, "category": "blocks"},
                    "minecraft:entity/chest/normal": {"chunk_id": 5, "pixel_x": 0, "pixel_y": 0, "rect_width": 64, "rect_height": 64, "category": "chest"},
                    "minecraft:entity/shulker/shulker": {"chunk_id": 6, "pixel_x": 0, "pixel_y": 0, "rect_width": 64, "rect_height": 64, "category": "shulker_boxes"},
                    "minecraft:entity/banner/banner_base": {"chunk_id": 7, "pixel_x": 0, "pixel_y": 0, "rect_width": 64, "rect_height": 64, "category": "banner_patterns"},
                    "minecraft:map/decorations/banner_white": {"chunk_id": 12, "pixel_x": 0, "pixel_y": 0, "rect_width": 8, "rect_height": 8, "category": "map_decorations"},
                },
            }
        }
        mgr = LiveSyncMaterialManager(world_obj=self.obj, atlas_params=atlas_params)
        self.assertTrue({0, 1, 5, 6, 7}.issubset(mgr.chunk_materials))
        self.assertNotIn(12, mgr.chunk_materials)

        baker = StateBaker()
        chest = baker.bake_block_state("minecraft:chest[facing=north,type=single]")
        chest_resolved = mgr.resolve_block_face(
            parse_and_classify("minecraft:chest[facing=north,type=single]"), "up", 2,
            baked_face=chest.elements[0].faces["up"],
        )
        self.assertEqual(chest_resolved.chunk_id, 5)
        self.assertEqual(self.obj.material_slots[chest_resolved.slot_index].material, mgr.chunk_materials[5])

        banner = baker.bake_block_state("minecraft:red_banner[rotation=0]")
        banner_resolved = mgr.resolve_block_face(
            parse_and_classify("minecraft:red_banner[rotation=0]"), "north", 5,
            baked_face=banner.elements[0].faces["north"],
        )
        self.assertEqual(banner_resolved.chunk_id, 7)
        self.assertEqual(self.obj.material_slots[banner_resolved.slot_index].material, mgr.chunk_materials[7])

    def test_model_parser_normalize_texture(self):
        """Verify model parser preserves entity namespaces and doesn't prepend block/."""
        parser = ModelParser()
        self.assertEqual(parser._normalize_texture("entity/chest/normal"), "minecraft:entity/chest/normal")
        self.assertEqual(parser._normalize_texture("minecraft:entity/banner/base"), "minecraft:entity/banner/base")
        self.assertEqual(parser._normalize_texture("stone"), "minecraft:block/stone")
        self.assertEqual(parser._normalize_texture("block/oak_planks"), "minecraft:block/oak_planks")


if __name__ == "__main__":
    unittest.main()

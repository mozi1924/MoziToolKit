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
        """Verify that chests bake accurate 3D multipart models when JSON models with elements are provided."""
        baker = StateBaker()
        chest_model = {
            "textures": {
                "particle": "minecraft:entity/chest/normal",
                "texture": "minecraft:entity/chest/normal",
            },
            "elements": [
                {
                    "from": [1, 9, 1],
                    "to": [15, 14, 15],
                    "faces": {
                        "up": {"uv": [7, 0, 10.5, 3.5], "texture": "#texture"},
                        "down": {"uv": [3.5, 0, 7, 3.5], "texture": "#texture"},
                    }
                },
                {
                    "from": [1, 0, 1],
                    "to": [15, 10, 15],
                    "faces": {
                        "up": {"uv": [7, 4.75, 10.5, 8.25], "texture": "#texture"},
                        "down": {"uv": [3.5, 4.75, 7, 8.25], "texture": "#texture"},
                        "south": {"uv": [14, 8.25, 10.5, 10.75], "texture": "#texture"},
                    }
                },
                {
                    "from": [7, 7, 15],
                    "to": [9, 11, 16],
                    "faces": {
                        "south": {"uv": [1.5, 0.25, 1.0, 1.25], "texture": "#texture"},
                    }
                }
            ]
        }
        baker.model_parser.register_model("minecraft:block/chest", chest_model)
        baker.state_resolver.register_blockstate("minecraft:chest", {
            "variants": {
                "facing=north,type=single,waterlogged=false": {"model": "minecraft:block/chest"},
                "facing=south,type=single,waterlogged=false": {"model": "minecraft:block/chest", "y": 180},
            }
        })

        # 1. Single Chest Facing North
        baked_north = baker.bake_block_state("minecraft:chest[facing=north,type=single,waterlogged=false]")
        self.assertFalse(baked_north.is_cube, "Chest should not be classified as a full cube!")
        self.assertEqual(len(baked_north.elements), 3, "Chest should have 3 distinct 3D elements (lid, body, and latch)!")

        # Verify Lid element (element 0)
        lid_elem = baked_north.elements[0]
        self.assertEqual(lid_elem.from_pos, (1, 9, 1))
        self.assertEqual(lid_elem.to_pos, (15, 14, 15))

        # Verify Body element (element 1)
        body_elem = baked_north.elements[1]
        self.assertEqual(body_elem.from_pos, (1, 0, 1))
        self.assertEqual(body_elem.to_pos, (15, 10, 15))

        # Verify Latch element (element 2)
        latch_elem = baked_north.elements[2]
        self.assertEqual(latch_elem.from_pos, (7, 7, 15))
        self.assertEqual(latch_elem.to_pos, (9, 11, 16))

        # Verify chest texture key is entity texture
        for face in body_elem.faces.values():
            self.assertEqual(face.texture, "minecraft:entity/chest/normal")

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
        self.assertEqual(cloth_elem.faces["north"].direction, "west")

        # 2. Wall Banner facing south
        wall = baker.bake_block_state("minecraft:blue_wall_banner[facing=south]")
        self.assertFalse(wall.is_cube)
        self.assertEqual(len(wall.elements), 2, "Wall banner should have cloth and crossbar elements!")
        self.assertEqual(wall.elements[0].faces["north"].texture, "minecraft:entity/banner/banner_base")
        self.assertEqual(wall.elements[0].faces["north"].direction, "south")

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

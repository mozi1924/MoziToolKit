"""
Integration Test for MoziToolKit Live Sync and Geometry Nodes.
Verifies:
1. Updating MC_Block_Templates collection meshes directly from resource packs / JAR using mc_baker.
2. Pure Python VoxelStorage snapshot, delta updates, and CRC32 manifest validation.
3. Point cloud builder writing 20+ point-domain attributes with batch foreach_set.
4. Procedural Geometry Nodes world tree generation, culling group, and material dispatcher.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
from utils.geometry_nodes import (
    WORLD_MODIFIER_NAME,
    WORLD_TREE_NAME,
    get_or_create_culling_merge_group,
    get_or_create_material_dispatcher_group,
    setup_world_geometry_nodes,
)
from utils.live_sync import (
    BlockTypeEnum,
    VoxelStorage,
    classify_block_type_and_orientation,
    update_world_point_cloud,
)
from utils.mc_baker import (
    TEMPLATE_COLLECTION_NAME,
    update_mc_block_templates_from_pack,
)

JAR_PATH = "/Users/jaxlocke/26.2-Fabric.jar"


class TestMoziYefiraIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Path(JAR_PATH).exists():
            raise unittest.SkipTest(f"Client JAR not found at {JAR_PATH}")

    def setUp(self):
        bpy.ops.wm.read_homefile(use_empty=True)

    def test_update_mc_block_templates_from_jar(self):
        """Verify updating MC_Block_Templates from JAR creates real 3D non-full meshes with attributes."""
        count = update_mc_block_templates_from_pack(JAR_PATH)
        self.assertGreater(count, 15)

        col = bpy.data.collections.get(TEMPLATE_COLLECTION_NAME)
        self.assertIsNotNone(col)

        # Check key templates
        stairs_obj = col.objects.get("stairs_straight")
        self.assertIsNotNone(stairs_obj)
        self.assertGreater(len(stairs_obj.data.polygons), 6)
        self.assertIn("yefira_cube_face_normal", stairs_obj.data.attributes)
        self.assertIn("yefira_local_face_id", stairs_obj.data.attributes)
        self.assertIn("yefira_local_uv", stairs_obj.data.attributes)

        fence_obj = col.objects.get("fence")
        self.assertIsNotNone(fence_obj)
        self.assertGreater(len(fence_obj.data.polygons), 10)

        lantern_obj = col.objects.get("lantern")
        self.assertIsNotNone(lantern_obj)
        self.assertGreater(len(lantern_obj.data.polygons), 6)

    def test_storage_snapshot_and_delta(self):
        """Verify VoxelStorage full snapshot and delta application."""
        storage = VoxelStorage()
        palette = ["minecraft:air", "minecraft:stone", "minecraft:oak_planks"]
        grid = [1, 2, 0, 1]
        storage.set_full_snapshot(0, 0, 0, 2, 2, 1, palette, grid)

        self.assertEqual(storage.get_block(0, 0, 0), "minecraft:stone")
        self.assertEqual(storage.get_block(0, 1, 0), "minecraft:oak_planks")
        self.assertEqual(storage.get_block(1, 0, 0), "minecraft:air")
        self.assertEqual(storage.get_block(1, 1, 0), "minecraft:stone")

        # Apply delta
        storage.apply_delta_update(0, 0, 0, [(0, 1, 0, "minecraft:glass")])
        self.assertEqual(storage.get_block(0, 1, 0), "minecraft:glass")

    def test_block_classifier(self):
        """Verify block classification for cubes, stairs, props, and fluids."""
        c_type, rot, idx = classify_block_type_and_orientation("minecraft:stone")
        self.assertEqual(c_type, BlockTypeEnum.CUBE)

        s_type, rot, idx = classify_block_type_and_orientation(
            "minecraft:oak_stairs[facing=south,half=bottom,shape=straight]"
        )
        self.assertEqual(s_type, BlockTypeEnum.STAIRS)
        self.assertGreaterEqual(idx, 0)

        w_type, rot, idx = classify_block_type_and_orientation("minecraft:water[level=0]")
        self.assertEqual(w_type, BlockTypeEnum.FLUID)

        a_type, rot, idx = classify_block_type_and_orientation("minecraft:air")
        self.assertEqual(a_type, BlockTypeEnum.AIR)

    def test_point_cloud_builder_and_attributes(self):
        """Verify point cloud builder calculates 6-face attributes from pure BlockState strings."""
        storage = VoxelStorage()
        storage.min_x = 0
        storage.min_y = 64
        storage.min_z = 0
        storage.size_x = 4
        storage.size_y = 1
        storage.size_z = 1
        storage.block_map = {
            (0, 64, 0): "minecraft:magenta_glazed_terracotta[facing=east]",
            (1, 64, 0): "minecraft:observer[facing=north,powered=false]",
            (2, 64, 0): "minecraft:oak_stairs[facing=south,half=bottom,shape=straight]",
            (3, 64, 0): "minecraft:lantern[hanging=false]",
        }

        res = update_world_point_cloud(
            context=bpy.context,
            storage=storage,
        )

        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data
        self.assertEqual(len(mesh.vertices), 4)

        # Check UV rotation attribute for terracotta (facing=east has 270 deg rotation on top face)
        rot_attr = mesh.attributes.get("mtk_uv_rot_top")
        self.assertIsNotNone(rot_attr)
        self.assertEqual(float(rot_attr.data[0].value), 270.0)

        # Check Block_State attribute
        state_attr = mesh.attributes.get("yefira_block_state")
        self.assertIsNotNone(state_attr)

    def test_geometry_nodes_tree_generation(self):
        """Verify setup_world_geometry_nodes builds modifier and node tree."""
        storage = VoxelStorage()
        storage.min_x, storage.min_y, storage.min_z = 0, 0, 0
        storage.size_x, storage.size_y, storage.size_z = 2, 1, 1
        storage.block_map = {
            (0, 0, 0): "minecraft:stone",
            (1, 0, 0): "minecraft:oak_stairs[facing=east,half=bottom,shape=straight]",
        }

        res = update_world_point_cloud(context=bpy.context, storage=storage)
        mod = setup_world_geometry_nodes(res.world_obj)

        self.assertIsNotNone(mod)
        self.assertEqual(mod.name, WORLD_MODIFIER_NAME)
        self.assertEqual(mod.node_group.name, WORLD_TREE_NAME)

        # Verify sub-groups exist
        culling_group = get_or_create_culling_merge_group()
        self.assertIsNotNone(culling_group)

        mat_disp_group = get_or_create_material_dispatcher_group({})
        self.assertIsNotNone(mat_disp_group)

    def test_biome_tint_attributes_in_point_cloud(self):
        """Verify biome tint colors and data weights are correctly set on point clouds."""
        storage = VoxelStorage()
        storage.min_x, storage.min_y, storage.min_z = 0, 0, 0
        storage.size_x, storage.size_y, storage.size_z = 4, 1, 1
        storage.block_map = {
            (0, 0, 0): "minecraft:grass_block",
            (1, 0, 0): "minecraft:spruce_leaves",
            (2, 0, 0): "minecraft:oak_leaves",
            (3, 0, 0): "minecraft:stone",
        }

        res = update_world_point_cloud(context=bpy.context, storage=storage)
        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data

        # Check point tint color and data
        tint_color_attr = mesh.attributes.get("mtk_biome_tint_color")
        tint_data_attr = mesh.attributes.get("mtk_biome_tint_data")
        self.assertIsNotNone(tint_color_attr)
        self.assertIsNotNone(tint_data_attr)

        # grass_block has grass tint color and tint_weight=1.0
        grass_tint = tuple(tint_color_attr.data[0].color)
        grass_data = tuple(tint_data_attr.data[0].color)
        self.assertAlmostEqual(grass_tint[0], 0.35, places=2)
        self.assertAlmostEqual(grass_tint[1], 0.72, places=2)
        self.assertAlmostEqual(grass_data[0], 1.0, places=2)  # tint active

        # spruce_leaves has hardcoded spruce tint and is_hardcoded flag
        spruce_tint = tuple(tint_color_attr.data[1].color)
        spruce_data = tuple(tint_data_attr.data[1].color)
        self.assertAlmostEqual(spruce_tint[0], 0.38039, places=2)
        self.assertAlmostEqual(spruce_data[0], 1.0, places=2)

        # stone has no tint (white + data weight 0.0)
        stone_tint = tuple(tint_color_attr.data[3].color)
        stone_data = tuple(tint_data_attr.data[3].color)
        self.assertAlmostEqual(stone_tint[0], 1.0, places=2)
        self.assertAlmostEqual(stone_data[0], 0.0, places=2)

    def test_state_attribute_cache_persistence_and_invalidation(self):
        """Verify PrecomputedStateAttr cache persists across updates and invalidates on atlas change."""
        from utils.live_sync.point_cloud import (
            _STATE_ATTR_CACHE,
            refresh_baker_sources,
            clear_state_cache,
        )

        clear_state_cache()
        self.assertEqual(len(_STATE_ATTR_CACHE), 0)

        storage = VoxelStorage()
        storage.min_x, storage.min_y, storage.min_z = 0, 0, 0
        storage.size_x, storage.size_y, storage.size_z = 2, 1, 1
        storage.block_map = {
            (0, 0, 0): "minecraft:stone",
            (1, 0, 0): "minecraft:oak_stairs[facing=east,half=bottom,shape=straight]",
        }

        mapping_a = {"minecraft:stone": 10, "minecraft:oak_stairs": 20}
        lut_a = {"minecraft:stone": [(1, 1)] * 6, "minecraft:oak_stairs": [(2, 2)] * 6}

        # First build: cache populated
        update_world_point_cloud(
            context=bpy.context,
            storage=storage,
            atlas_mapping_dict=mapping_a,
            block_face_lut=lut_a,
        )
        self.assertIn("minecraft:stone", _STATE_ATTR_CACHE)
        stone_entry_1 = _STATE_ATTR_CACHE["minecraft:stone"]

        # Call refresh_baker_sources (no pack config changed)
        refresh_baker_sources()

        # Second build with same mapping: cache MUST persist
        update_world_point_cloud(
            context=bpy.context,
            storage=storage,
            atlas_mapping_dict=mapping_a,
            block_face_lut=lut_a,
        )
        stone_entry_2 = _STATE_ATTR_CACHE.get("minecraft:stone")
        self.assertIs(stone_entry_1, stone_entry_2, "Cache entry must be preserved across updates without rebuilding")

        # Third build with changed atlas mapping: cache MUST invalidate
        mapping_b = {"minecraft:stone": 99, "minecraft:oak_stairs": 100}
        lut_b = {"minecraft:stone": [(9, 9)] * 6, "minecraft:oak_stairs": [(8, 8)] * 6}
        update_world_point_cloud(
            context=bpy.context,
            storage=storage,
            atlas_mapping_dict=mapping_b,
            block_face_lut=lut_b,
        )
        stone_entry_3 = _STATE_ATTR_CACHE.get("minecraft:stone")
        self.assertIsNot(stone_entry_1, stone_entry_3, "Cache entry must be recomputed on atlas mapping change")
        self.assertEqual(stone_entry_3.mat_id, 99)

    def test_is_yefira_object_detection(self):
        """Verify is_yefira_object recognizes meshes by point-domain schema attributes regardless of object name."""
        from utils.materials.yefira import is_yefira_object
        from utils.live_sync.constants import BLOCK_STATE, MC_POSITION

        mesh = bpy.data.meshes.new("CustomProceduralMesh")
        mesh.from_pydata([(0.0, 0.0, 0.0)], [], [])
        mesh.update()

        obj = bpy.data.objects.new("RandomCustomName_12345", mesh)
        bpy.context.scene.collection.objects.link(obj)

        # Initially no yefira attributes
        self.assertFalse(is_yefira_object(obj))

        # Add yefira_block_state attribute
        attr = mesh.attributes.new(name=BLOCK_STATE, type="STRING", domain="POINT")
        attr.data[0].value = b"minecraft:stone"
        self.assertTrue(is_yefira_object(obj))

        # Remove BLOCK_STATE and add MC_POSITION
        mesh.attributes.remove(attr)
        self.assertFalse(is_yefira_object(obj))

        pos_attr = mesh.attributes.new(name=MC_POSITION, type="FLOAT_VECTOR", domain="POINT")
        pos_attr.data[0].vector = (1.0, 2.0, 3.0)
        self.assertTrue(is_yefira_object(obj))

        # Cleanup
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)

    def test_notify_yefira_update_decoupled_from_sync(self):
        """Test that notify_yefira_update does not trigger sync_rebuild_world or fail on non-yefira objects."""
        from MoziToolKit.utils.materials.yefira import notify_yefira_update
        from MoziToolKit.utils.live_sync.storage import voxel_storage

        # Empty storage
        voxel_storage.clear()

        # Call with None
        notify_yefira_update(None)

        # Call with standard mesh object
        mesh = bpy.data.meshes.new("StandardMesh")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [], [(0, 1, 2)])
        mesh.update()
        obj = bpy.data.objects.new("StandardObj", mesh)
        bpy.context.scene.collection.objects.link(obj)

        notify_yefira_update(obj)

        # Ensure no Yefira_World was created or rebuilt unexpectedly
        self.assertEqual(voxel_storage.size_x, 0)

        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)

    def test_standard_atlas_dimension_defaults(self):
        """Test that extract_atlas_parameters defaults match canonical constants (not test-pack 4096x80)."""
        from MoziToolKit.utils.materials.atlas_integration import extract_atlas_parameters
        from MoziToolKit.utils.live_sync.constants import (
            DEFAULT_ATLAS_WIDTH, DEFAULT_ATLAS_HEIGHT, DEFAULT_TILE_SIZE, DEFAULT_TILES_PER_ROW,
            DEFAULT_ANIM_ATLAS_WIDTH, DEFAULT_ANIM_ATLAS_HEIGHT
        )

        params = extract_atlas_parameters(None)
        self.assertEqual(params["width"], DEFAULT_ATLAS_WIDTH)
        self.assertEqual(params["height"], DEFAULT_ATLAS_HEIGHT)
        self.assertEqual(params["tile_size"], DEFAULT_TILE_SIZE)
        self.assertEqual(params["tiles_per_row"], DEFAULT_TILES_PER_ROW)
        self.assertEqual(params["chunk_0_width"], DEFAULT_ATLAS_WIDTH)
        self.assertEqual(params["chunk_0_height"], DEFAULT_ATLAS_HEIGHT)
        self.assertEqual(params["chunk_1_width"], DEFAULT_ANIM_ATLAS_WIDTH)
        self.assertEqual(params["chunk_1_height"], DEFAULT_ANIM_ATLAS_HEIGHT)

    def test_binary_protocol_packet_parsing(self):
        """Test binary live sync protocol parsing with PacketType constants and length validation."""
        import struct
        from MoziToolKit.utils.live_sync.client import SyncClientThread
        from MoziToolKit.utils.live_sync.constants import PROTOCOL_MAGIC, PROTOCOL_VERSION, PacketType

        received_events = []

        client = SyncClientThread(
            url="ws://localhost:8080",
            on_status_change=lambda s: received_events.append(("status", s)),
            on_selection_info=lambda *args: received_events.append(("selection", args)),
            on_full_snapshot=lambda *args: received_events.append(("full", args)),
            on_delta_update=lambda *args: received_events.append(("delta", args)),
        )

        # 1. Truncated packet (length < 4) - should be ignored safely
        client._parse_binary_packet(b"MC")
        self.assertEqual(len(received_events), 0)

        # 2. Invalid magic - should be ignored safely
        client._parse_binary_packet(b"XX\x01\x01")
        self.assertEqual(len(received_events), 0)

        # 3. Valid Selection Info packet (0x01)
        pkt = bytearray()
        pkt.extend(PROTOCOL_MAGIC)
        pkt.append(PROTOCOL_VERSION)
        pkt.append(PacketType.SELECTION_INFO)
        pkt.extend(struct.pack("<iiiiii", 10, 20, 30, 5, 6, 7))
        client._parse_binary_packet(bytes(pkt))

        self.assertEqual(len(received_events), 1)
        self.assertEqual(received_events[0], ("selection", (10, 20, 30, 5, 6, 7)))

        # 4. Truncated Delta packet - should not crash
        pkt = bytearray()
        pkt.extend(PROTOCOL_MAGIC)
        pkt.append(PROTOCOL_VERSION)
        pkt.append(PacketType.DELTA_UPDATE)
        pkt.extend(b"\x00" * 5)  # Truncated
        client._parse_binary_packet(bytes(pkt))
        self.assertEqual(len(received_events), 1)

    def test_mc_to_blender_local_coords(self):
        """Test Minecraft to Blender coordinate transformation helper."""
        import numpy as np
        from MoziToolKit.utils.live_sync.point_cloud import mc_to_blender_local_coords

        coords = np.array([
            [10, 64, 20],
            [12, 65, 22],
        ], dtype=np.float32)

        min_x, min_y, min_z = 10, 64, 20
        size_x, size_y, size_z = 3, 2, 3
        # half_x = 3/2 - 0.5 = 1.0; half_z = 3/2 - 0.5 = 1.0
        # for pt 0: x = 0 - 1 = -1.0; y = -(0 - 1) = 1.0; z = 0 + 0.5 = 0.5
        # for pt 1: x = 2 - 1 = 1.0; y = -(2 - 1) = -1.0; z = 1 + 0.5 = 1.5

        vertices = mc_to_blender_local_coords(coords, min_x, min_y, min_z, size_x, size_y, size_z)
        self.assertAlmostEqual(vertices[0, 0], -1.0)
        self.assertAlmostEqual(vertices[0, 1], 1.0)
        self.assertAlmostEqual(vertices[0, 2], 0.5)
        self.assertAlmostEqual(vertices[1, 0], 1.0)
        self.assertAlmostEqual(vertices[1, 1], -1.0)
        self.assertAlmostEqual(vertices[1, 2], 1.5)

    def test_precomputed_state_attr_with_wire_json_payload(self):
        """Test that PrecomputedStateAttr correctly parses Fabric mod JSON wire payload with faces metadata."""
        import json
        from MoziToolKit.utils.live_sync.point_cloud import PrecomputedStateAttr
        from MoziToolKit.utils.live_sync.classifier import BlockTypeEnum

        json_state = json.dumps({
            "state": "minecraft:piston[extended=false,facing=south]",
            "type": 0,
            "opaque": 1,
            "emissive": 0,
            "faces": {
                "east": {"tex": "minecraft:block/piston_side", "rot": 270, "uv": [0.0, 0.0, 1.0, 1.0], "tint": -1},
                "west": {"tex": "minecraft:block/piston_side", "rot": 90, "uv": [0.0, 0.0, 1.0, 1.0], "tint": -1},
                "top": {"tex": "minecraft:block/piston_side", "rot": 180, "uv": [0.0, 0.0, 1.0, 1.0], "tint": -1},
                "bottom": {"tex": "minecraft:block/piston_side", "rot": 0, "uv": [0.0, 0.0, 1.0, 1.0], "tint": -1},
                "south": {"tex": "minecraft:block/piston_top", "rot": 0, "uv": [0.0, 0.0, 1.0, 1.0], "tint": -1},
                "north": {"tex": "minecraft:block/piston_bottom", "rot": 0, "uv": [0.0, 0.0, 1.0, 1.0], "tint": -1},
            }
        })

        attr = PrecomputedStateAttr(
            state_str=json_state,
            template_indices={},
            atlas_mapping_dict={},
            atlas_mapping_textures={},
            block_face_lut={},
            block_face_chunk_lut={},
            block_face_texture_lut={},
            block_face_tint_lut={},
            block_face_anim_timing_lut={},
            block_face_anim_frame_size_lut={},
        )

        self.assertEqual(attr.name, "piston")
        self.assertEqual(attr.block_type, BlockTypeEnum.CUBE)
        self.assertEqual(attr.is_opaque, 1)
        self.assertEqual(attr.is_emissive, 0)
        # Verify per-face UV rotations: FACES order is ("east", "west", "top", "bottom", "south", "north")
        # east=270, west=90, top=180, bottom=0, south=0, north=0
        self.assertEqual(attr.face_uv_rot, (270.0, 90.0, 180.0, 0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main(argv=["dummy"])




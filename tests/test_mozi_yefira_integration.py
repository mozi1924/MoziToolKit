"""
Integration Test for MoziToolKit Live Sync and Direct Mesh Generation.
Verifies:
1. VoxelStorage snapshot, delta updates, and section handling.
2. Block classification for cubes, stairs, props, and fluids.
3. Direct Mesh Builder world generation and incremental synchronization.
4. Binary live sync wire protocol packet parsing.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
# Bootstrap MoziToolKit package (also activates the isolated test sandbox)
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from utils.live_sync import (
    BlockTypeEnum,
    VoxelStorage,
    classify_block_type_and_orientation,
    build_world_mesh,
    sync_world_mesh,
)
from utils.materials.yefira.atlas_integration import extract_atlas_parameters
from utils.live_sync.constants import (
    DEFAULT_ATLAS_WIDTH,
    DEFAULT_ATLAS_HEIGHT,
    DEFAULT_TILE_SIZE,
    DEFAULT_TILES_PER_ROW,
    DEFAULT_ANIM_ATLAS_WIDTH,
    DEFAULT_ANIM_ATLAS_HEIGHT,
    DEFAULT_WORLD_OBJECT_NAME,
)
from utils.live_sync.client import SyncClientThread
from utils.live_sync.constants import PROTOCOL_MAGIC, PROTOCOL_VERSION, PacketType


class TestMoziYefiraIntegration(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_homefile(use_empty=True)

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

    def test_direct_mesh_world_generation(self):
        """Verify Direct Mesh generation builds valid mesh and polygons from storage."""
        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:stone")
        storage.set_block(1, 0, 0, "minecraft:oak_stairs[facing=east,half=bottom,shape=straight]")

        res = build_world_mesh(context=bpy.context, storage=storage)
        self.assertIsNotNone(res.world_obj)
        self.assertEqual(res.world_obj.name, DEFAULT_WORLD_OBJECT_NAME)
        self.assertGreater(len(res.world_obj.data.polygons), 0)
        self.assertIn("UVMap", res.world_obj.data.uv_layers)

    def test_is_yefira_object_detection(self):
        """Verify is_yefira_object recognizes Yefira live sync world objects."""
        from utils.materials.yefira import is_yefira_object

        mesh = bpy.data.meshes.new("TestMesh")
        obj = bpy.data.objects.new(DEFAULT_WORLD_OBJECT_NAME, mesh)
        bpy.context.scene.collection.objects.link(obj)

        self.assertTrue(is_yefira_object(obj))

        section_obj = bpy.data.objects.new("Yefira_Section_0_0_0", mesh)
        bpy.context.scene.collection.objects.link(section_obj)
        self.assertTrue(is_yefira_object(section_obj))

        other_obj = bpy.data.objects.new("Cube", mesh)
        bpy.context.scene.collection.objects.link(other_obj)
        self.assertFalse(is_yefira_object(other_obj))

    def test_standard_atlas_dimension_defaults(self):
        """Test that extract_atlas_parameters defaults match canonical constants."""
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


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

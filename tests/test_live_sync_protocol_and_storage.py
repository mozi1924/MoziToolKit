"""
Unit tests for LiveSync binary protocol parsing, VoxelStorage CRC32 manifest validation,
section repair pipelines, and attribute contract version enforcement.
"""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
# Bootstrap MoziToolKit package (also activates the isolated test sandbox)
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from utils.live_sync.client import SyncClientThread
from utils.live_sync.constants import (
    PROTOCOL_MAGIC,
    PROTOCOL_VERSION,
    PacketType,
    HEADER_FORMAT,
    SELECTION_INFO_FORMAT,
    DELTA_HEADER_FORMAT,
    DELTA_CHANGE_PREFIX_FORMAT,
    MANIFEST_HEADER_FORMAT,
    MANIFEST_ENTRY_FORMAT,
    SECTION_SNAPSHOT_HEADER_FORMAT,
    CONTRACT_VERSION,
    CONTRACT_ATTRIBUTE_KEY,
    get_attribute_contract_version,
    is_contract_compatible,
)
from utils.live_sync.storage import VoxelStorage


class TestLiveSyncProtocolAndStorage(unittest.TestCase):
    def setUp(self):
        self.storage = VoxelStorage()

    def test_magic_and_constants(self):
        """Verify protocol magic constant and header sizing."""
        self.assertEqual(PROTOCOL_MAGIC, b"MC")
        self.assertEqual(PROTOCOL_VERSION, 1)
        self.assertEqual(PacketType.SELECTION_INFO, 0x01)
        self.assertEqual(PacketType.FULL_SNAPSHOT, 0x02)
        self.assertEqual(PacketType.DELTA_UPDATE, 0x03)
        self.assertEqual(PacketType.SECTION_MANIFEST, 0x05)
        self.assertEqual(PacketType.SECTION_SNAPSHOT, 0x06)
        self.assertEqual(PacketType.REPAIR_REQUEST, 0x81)

    def test_parse_selection_info_packet(self):
        """Test binary parsing for PacketType.SELECTION_INFO (0x01)."""
        received = {}

        def on_selection_info(min_x, min_y, min_z, size_x, size_y, size_z):
            received.update({
                "min_x": min_x, "min_y": min_y, "min_z": min_z,
                "size_x": size_x, "size_y": size_y, "size_z": size_z,
            })

        client = SyncClientThread("ws://dummy", on_status_change=lambda s: None,
                                  on_selection_info=on_selection_info,
                                  on_full_snapshot=lambda *a: None,
                                  on_delta_update=lambda *a: None)

        payload = struct.pack(SELECTION_INFO_FORMAT, 100, 64, 200, 16, 32, 16)
        packet = struct.pack(HEADER_FORMAT, PROTOCOL_MAGIC, PROTOCOL_VERSION, PacketType.SELECTION_INFO) + payload

        client._parse_binary_packet(packet)

        self.assertEqual(received["min_x"], 100)
        self.assertEqual(received["min_y"], 64)
        self.assertEqual(received["min_z"], 200)
        self.assertEqual(received["size_x"], 16)
        self.assertEqual(received["size_y"], 32)
        self.assertEqual(received["size_z"], 16)

    def test_parse_selection_info_truncated_payload(self):
        """Verify truncated payload is rejected without unhandled exceptions."""
        client = SyncClientThread("ws://dummy", on_status_change=lambda s: None,
                                  on_selection_info=lambda *a: None,
                                  on_full_snapshot=lambda *a: None,
                                  on_delta_update=lambda *a: None)
        packet = struct.pack(HEADER_FORMAT, PROTOCOL_MAGIC, PROTOCOL_VERSION, PacketType.SELECTION_INFO) + b"\x00\x00\x00\x01"
        client._parse_binary_packet(packet)

    def test_parse_full_snapshot_1byte_indices(self):
        """Test binary parsing for PacketType.FULL_SNAPSHOT with 1-byte indices."""
        received = {}

        def on_full_snapshot(min_x, min_y, min_z, size_x, size_y, size_z, palette, indices):
            received.update({
                "min_x": min_x, "min_y": min_y, "min_z": min_z,
                "size_x": size_x, "size_y": size_y, "size_z": size_z,
                "palette": palette, "indices": indices,
            })

        client = SyncClientThread("ws://dummy", on_status_change=lambda s: None,
                                  on_selection_info=lambda *a: None,
                                  on_full_snapshot=on_full_snapshot,
                                  on_delta_update=lambda *a: None)

        palette = ["minecraft:air", "minecraft:stone", "minecraft:dirt"]
        encoded_palette = b""
        for s in palette:
            b_str = s.encode("utf-8")
            encoded_palette += struct.pack("<H", len(b_str)) + b_str

        # 2x2x2 = 8 blocks
        indices = [0, 1, 2, 1, 0, 0, 1, 2]
        indices_bytes = bytes(indices)

        bounds = struct.pack(SELECTION_INFO_FORMAT, 10, 20, 30, 2, 2, 2)
        payload = bounds + struct.pack("<H", len(palette)) + encoded_palette + b"\x01" + indices_bytes
        packet = struct.pack(HEADER_FORMAT, PROTOCOL_MAGIC, PROTOCOL_VERSION, PacketType.FULL_SNAPSHOT) + payload

        client._parse_binary_packet(packet)

        self.assertEqual(received["min_x"], 10)
        self.assertEqual(received["min_y"], 20)
        self.assertEqual(received["min_z"], 30)
        self.assertEqual(received["size_x"], 2)
        self.assertEqual(received["size_y"], 2)
        self.assertEqual(received["size_z"], 2)
        self.assertEqual(received["palette"], palette)
        self.assertEqual(list(received["indices"]), indices)

    def test_parse_full_snapshot_2byte_indices(self):
        """Test binary parsing for PacketType.FULL_SNAPSHOT with 2-byte indices."""
        received = {}

        def on_full_snapshot(min_x, min_y, min_z, size_x, size_y, size_z, palette, indices):
            received.update({
                "palette_len": len(palette),
                "indices": indices,
            })

        client = SyncClientThread("ws://dummy", on_status_change=lambda s: None,
                                  on_selection_info=lambda *a: None,
                                  on_full_snapshot=on_full_snapshot,
                                  on_delta_update=lambda *a: None)

        palette = [f"minecraft:block_{i}" for i in range(300)]
        encoded_palette = b""
        for s in palette:
            b_str = s.encode("utf-8")
            encoded_palette += struct.pack("<H", len(b_str)) + b_str

        # 2x2x1 = 4 blocks
        indices = [0, 100, 200, 299]
        indices_bytes = b"".join(struct.pack("<H", idx) for idx in indices)

        bounds = struct.pack(SELECTION_INFO_FORMAT, 0, 0, 0, 2, 2, 1)
        payload = bounds + struct.pack("<H", len(palette)) + encoded_palette + b"\x02" + indices_bytes
        packet = struct.pack(HEADER_FORMAT, PROTOCOL_MAGIC, PROTOCOL_VERSION, PacketType.FULL_SNAPSHOT) + payload

        client._parse_binary_packet(packet)

        self.assertEqual(received["palette_len"], 300)
        self.assertEqual(list(received["indices"]), indices)

    def test_parse_delta_update_packet(self):
        """Test binary parsing for PacketType.DELTA_UPDATE (0x03)."""
        received = {}

        def on_delta_update(min_x, min_y, min_z, changes, seq_id):
            received["min_x"] = min_x
            received["min_y"] = min_y
            received["min_z"] = min_z
            received["seq_id"] = seq_id
            received["changes"] = changes

        client = SyncClientThread("ws://dummy", on_status_change=lambda s: None,
                                  on_selection_info=lambda *a: None,
                                  on_full_snapshot=lambda *a: None,
                                  on_delta_update=on_delta_update)

        deltas_raw = [
            (1, 2, 3, "minecraft:stone"),
            (0, 5, 1, "minecraft:air"),
            (7, 8, 9, "minecraft:oak_log[axis=y]"),
        ]

        encoded_deltas = b""
        for rx, ry, rz, st in deltas_raw:
            b_st = st.encode("utf-8")
            encoded_deltas += struct.pack(DELTA_CHANGE_PREFIX_FORMAT, rx, ry, rz, len(b_st)) + b_st

        # delta header: seq_id(I), min_x(i), min_y(i), min_z(i), change_count(H)
        header_payload = struct.pack(DELTA_HEADER_FORMAT, 42, 100, 200, 300, len(deltas_raw))
        payload = header_payload + encoded_deltas
        packet = struct.pack(HEADER_FORMAT, PROTOCOL_MAGIC, PROTOCOL_VERSION, PacketType.DELTA_UPDATE) + payload

        client._parse_binary_packet(packet)

        self.assertEqual(received["seq_id"], 42)
        self.assertEqual(len(received["changes"]), 3)
        self.assertEqual(received["changes"][0], (101, 202, 303, "minecraft:stone"))
        self.assertEqual(received["changes"][1], (100, 205, 301, "minecraft:air"))
        self.assertEqual(received["changes"][2], (107, 208, 309, "minecraft:oak_log[axis=y]"))

    def test_parse_section_manifest_packet(self):
        """Test binary parsing for PacketType.SECTION_MANIFEST (0x05)."""
        received = {}

        def on_section_manifest(server_seq_id, manifests):
            received["server_seq_id"] = server_seq_id
            received["manifests"] = manifests

        client = SyncClientThread("ws://dummy", on_status_change=lambda s: None,
                                  on_selection_info=lambda *a: None,
                                  on_full_snapshot=lambda *a: None,
                                  on_delta_update=lambda *a: None,
                                  on_section_manifest=on_section_manifest)

        manifests_raw = [
            (0, 4, 0, 123456789),
            (0, 5, 0, 987654321),
            (-1, 4, 2, 345678912),
        ]

        payload = struct.pack(MANIFEST_HEADER_FORMAT, 108, len(manifests_raw))
        for sx, sy, sz, crc in manifests_raw:
            payload += struct.pack(MANIFEST_ENTRY_FORMAT, sx, sy, sz, crc)

        packet = struct.pack(HEADER_FORMAT, PROTOCOL_MAGIC, PROTOCOL_VERSION, PacketType.SECTION_MANIFEST) + payload

        client._parse_binary_packet(packet)

        self.assertEqual(received["server_seq_id"], 108)
        self.assertEqual(len(received["manifests"]), 3)
        self.assertEqual(received["manifests"], manifests_raw)

    def test_parse_section_snapshot_packet(self):
        """Test binary parsing for PacketType.SECTION_SNAPSHOT (0x06)."""
        received = {}

        def on_section_snapshot(sec_x, sec_y, sec_z, start_x, start_y, start_z, size_x, size_y, size_z, palette, indices):
            received.update({
                "sec_x": sec_x, "sec_y": sec_y, "sec_z": sec_z,
                "start_x": start_x, "start_y": start_y, "start_z": start_z,
                "size_x": size_x, "size_y": size_y, "size_z": size_z,
                "palette": palette, "indices": indices,
            })

        client = SyncClientThread("ws://dummy", on_status_change=lambda s: None,
                                  on_selection_info=lambda *a: None,
                                  on_full_snapshot=lambda *a: None,
                                  on_delta_update=lambda *a: None,
                                  on_section_snapshot=on_section_snapshot)

        palette = ["minecraft:air", "minecraft:gold_block"]
        encoded_palette = b""
        for s in palette:
            b_str = s.encode("utf-8")
            encoded_palette += struct.pack("<H", len(b_str)) + b_str

        # 16x16x16 = 4096 blocks
        indices = [1] * 4096
        indices_bytes = bytes(indices)

        header_data = struct.pack(SECTION_SNAPSHOT_HEADER_FORMAT, 2, 4, 3, 32, 64, 48, 16, 16, 16, len(palette))
        payload = header_data + encoded_palette + b"\x01" + indices_bytes
        packet = struct.pack(HEADER_FORMAT, PROTOCOL_MAGIC, PROTOCOL_VERSION, PacketType.SECTION_SNAPSHOT) + payload

        client._parse_binary_packet(packet)

        self.assertEqual(received["sec_x"], 2)
        self.assertEqual(received["sec_y"], 4)
        self.assertEqual(received["sec_z"], 3)
        self.assertEqual(received["start_x"], 32)
        self.assertEqual(received["palette"], palette)
        self.assertEqual(len(received["indices"]), 4096)

    def test_storage_validate_manifest_matching(self):
        """Test VoxelStorage.validate_manifest when all section CRCs match."""
        palette = ["minecraft:air", "minecraft:stone"]
        indices = [1] * 4096  # all stone
        self.storage.set_full_snapshot(0, 0, 0, 16, 16, 16, palette, indices)

        computed_crc = self.storage.calculate_and_store_section_crc(0, 0, 0)
        self.assertGreater(computed_crc, 0)

        manifest = [(0, 0, 0, computed_crc)]
        mismatched = self.storage.validate_manifest(manifest)
        self.assertEqual(mismatched, [])

    def test_storage_validate_manifest_mismatched(self):
        """Test VoxelStorage.validate_manifest returns mismatched section coords."""
        palette = ["minecraft:air", "minecraft:stone"]
        indices = [1] * 4096
        self.storage.set_full_snapshot(0, 0, 0, 16, 16, 16, palette, indices)

        computed_crc = self.storage.calculate_and_store_section_crc(0, 0, 0)

        manifest = [(0, 0, 0, computed_crc + 999), (1, 0, 0, 55555)]
        mismatched = self.storage.validate_manifest(manifest)

        self.assertEqual(len(mismatched), 2)
        self.assertIn((0, 0, 0), mismatched)
        self.assertIn((1, 0, 0), mismatched)

    def test_storage_dirty_section_crc_recomputation(self):
        """Verify modifying blocks marks section dirty and recomputes CRC upon validation."""
        palette = ["minecraft:air", "minecraft:stone"]
        indices = [1] * 4096
        self.storage.set_full_snapshot(0, 0, 0, 16, 16, 16, palette, indices)
        old_crc = self.storage.calculate_and_store_section_crc(0, 0, 0)

        # Apply a delta update inside section (0, 0, 0)
        self.storage.apply_delta_update(0, 0, 0, [(0, 0, 0, "minecraft:diamond_block")])
        self.assertIn((0, 0, 0), self.storage._dirty_sections)

        # Re-validating against old CRC will detect mismatch
        mismatched = self.storage.validate_manifest([(0, 0, 0, old_crc)])
        self.assertEqual(mismatched, [(0, 0, 0)])

        # New CRC matches the updated state
        new_crc = self.storage.section_crc_map[(0, 0, 0)]
        self.assertNotEqual(old_crc, new_crc)
        self.assertEqual(self.storage.validate_manifest([(0, 0, 0, new_crc)]), [])

    def test_storage_ignores_noop_delta(self):
        """Repeated server deltas must not schedule an expensive world rebuild."""
        palette = ["minecraft:air", "minecraft:stone"]
        self.storage.set_full_snapshot(0, 0, 0, 16, 16, 16, palette, [1] * 4096)

        self.assertFalse(
            self.storage.apply_delta_update(0, 0, 0, [(0, 0, 0, "minecraft:stone")])
        )
        self.assertNotIn((0, 0, 0), self.storage._dirty_sections)

    def test_storage_apply_section_snapshot(self):
        """Verify applying a repaired section snapshot replaces blocks and refreshes CRC."""
        palette = ["minecraft:air", "minecraft:stone"]
        indices = [1] * 4096
        self.storage.set_full_snapshot(0, 0, 0, 16, 16, 16, palette, indices)

        # Apply repaired snapshot for section (0, 0, 0)
        repair_palette = ["minecraft:air", "minecraft:gold_block"]
        repair_indices = [1] * 4096
        self.storage.set_section_snapshot(0, 0, 0, 0, 0, 0, 16, 16, 16, repair_palette, repair_indices)

        self.assertEqual(self.storage.get_block(0, 0, 0), "minecraft:gold_block")
        self.assertEqual(self.storage.get_block(15, 15, 15), "minecraft:gold_block")
        self.assertNotIn((0, 0, 0), self.storage._dirty_sections)

    def test_contract_version_read_verification(self):
        """Test read-side attribute contract version verification helpers."""
        mesh = bpy.data.meshes.new("TestContractMesh")

        self.assertIsNone(get_attribute_contract_version(mesh))
        self.assertTrue(is_contract_compatible(mesh, CONTRACT_VERSION))

        mesh[CONTRACT_ATTRIBUTE_KEY] = CONTRACT_VERSION
        self.assertEqual(get_attribute_contract_version(mesh), CONTRACT_VERSION)
        self.assertTrue(is_contract_compatible(mesh, CONTRACT_VERSION))

        mesh[CONTRACT_ATTRIBUTE_KEY] = 2
        self.assertEqual(get_attribute_contract_version(mesh), 2)
        self.assertFalse(is_contract_compatible(mesh, min_version=4))
        self.assertTrue(is_contract_compatible(mesh, min_version=2))

        bpy.data.meshes.remove(mesh)

    def test_storage_manifest_export_import(self):
        """Test VoxelStorage manifest metadata export and round-trip import."""
        palette = ["minecraft:air", "minecraft:stone"]
        indices = [1] * 4096
        self.storage.set_full_snapshot(10, 20, 30, 16, 16, 16, palette, indices)

        exported = self.storage.export_manifest_metadata()
        self.assertEqual(exported["min_x"], 10)
        self.assertEqual(exported["min_y"], 20)
        self.assertEqual(exported["min_z"], 30)
        self.assertEqual(exported["size_x"], 16)
        self.assertEqual(exported["size_y"], 16)
        self.assertEqual(exported["size_z"], 16)
        self.assertIn("0,1,1", exported["section_crcs"])

        # Import into fresh storage
        new_storage = VoxelStorage()
        success = new_storage.import_manifest_metadata(exported)
        self.assertTrue(success)
        self.assertEqual(new_storage.min_x, 10)
        self.assertEqual(new_storage.size_x, 16)
        self.assertEqual(new_storage.section_crc_map[(0, 1, 1)], exported["section_crcs"]["0,1,1"])

    def test_scene_restoration_and_manifest_persistence(self):
        """Test persisting sync manifest to scene object and restoring it."""
        from operators.sync.op_sync_connect import persist_sync_state_to_scene, restore_sync_state_from_scene
        from utils.live_sync.storage import voxel_storage
        from utils.live_sync.constants import DEFAULT_WORLD_OBJECT_NAME

        # Clean slate
        voxel_storage.clear()
        world_mesh = bpy.data.meshes.new("TestWorldMesh")
        world_obj = bpy.data.objects.new(DEFAULT_WORLD_OBJECT_NAME, world_mesh)
        bpy.context.collection.objects.link(world_obj)

        try:
            # Set storage data and persist
            voxel_storage.set_full_snapshot(0, 0, 0, 16, 16, 16, ["minecraft:air", "minecraft:stone"], [1] * 4096)
            persist_sync_state_to_scene(bpy.context)

            self.assertIn("mtk:sync_manifest", world_obj)

            # Clear memory storage to simulate reloading blend file
            voxel_storage.clear()
            self.assertEqual(voxel_storage.size_x, 0)

            # Restore from scene object
            restored = restore_sync_state_from_scene(bpy.context)
            self.assertTrue(restored)
            self.assertEqual(voxel_storage.size_x, 16)
            self.assertEqual(voxel_storage.size_y, 16)
            self.assertIn((0, 0, 0), voxel_storage.section_crc_map)
        finally:
            bpy.data.objects.remove(world_obj, do_unlink=True)
            bpy.data.meshes.remove(world_mesh, do_unlink=True)
            voxel_storage.clear()

    def test_material_reuse_convention(self):
        """Test that LiveSyncMaterialManager strictly reuses existing scene materials and avoids duplicate '.001' proliferation."""
        from utils.live_sync.material_manager import LiveSyncMaterialManager, PROP_ATLAS_CHUNK_ID, PROP_PACK_HASH

        # Pre-create standard chunk material
        mat_name = "MC_Atlas_Chunk_0"
        existing_mat = bpy.data.materials.get(mat_name) or bpy.data.materials.new(name=mat_name)
        existing_mat[PROP_ATLAS_CHUNK_ID] = 0
        existing_mat[PROP_PACK_HASH] = "test_hash"

        initial_mat_count = len(bpy.data.materials)

        # Create MaterialManager
        mgr = LiveSyncMaterialManager(atlas_params={"mapping": {"chunks": [{"chunk_id": 0}]}})
        mgr._target_pack_hash = "test_hash"
        slot = mgr.ensure_chunk_loaded(0)

        self.assertEqual(slot, 0)
        self.assertEqual(mgr.chunk_materials[0], existing_mat)
        # Verify no duplicate materials were added
        self.assertEqual(len(bpy.data.materials), initial_mat_count)
        self.assertNotIn("MC_Atlas_Chunk_0.001", bpy.data.materials)

    def test_is_snapshot_identical_matches_exact_storage(self):
        """Test is_snapshot_identical returns True for identical data and False for any modifications."""
        self.storage.set_full_snapshot(
            0, 0, 0,
            2, 2, 2,
            ["minecraft:air", "minecraft:stone", "minecraft:dirt"],
            [1, 1, 2, 2, 0, 0, 1, 2]
        )

        # Identical parameters
        self.assertTrue(
            self.storage.is_snapshot_identical(
                0, 0, 0,
                2, 2, 2,
                ["minecraft:air", "minecraft:stone", "minecraft:dirt"],
                [1, 1, 2, 2, 0, 0, 1, 2]
            )
        )

        # Different bounds
        self.assertFalse(
            self.storage.is_snapshot_identical(
                1, 0, 0,
                2, 2, 2,
                ["minecraft:air", "minecraft:stone", "minecraft:dirt"],
                [1, 1, 2, 2, 0, 0, 1, 2]
            )
        )

        # Different block data (dirt changed to stone)
        self.assertFalse(
            self.storage.is_snapshot_identical(
                0, 0, 0,
                2, 2, 2,
                ["minecraft:air", "minecraft:stone", "minecraft:dirt"],
                [1, 1, 1, 2, 0, 0, 1, 2]
            )
        )

    def test_canonical_state_str_extraction_and_crc(self):
        """Verify CRC32 calculation accurately extracts canonical states from raw JSON models."""
        from utils.live_sync.storage import _extract_canonical_state_str
        raw_json = '{"state":"minecraft:water[level=0]","type":6,"opaque":0,"emissive":0,"faces":{}}'
        self.assertEqual(_extract_canonical_state_str(raw_json), "minecraft:water[level=0]")
        self.assertEqual(_extract_canonical_state_str("minecraft:stone"), "minecraft:stone")

    def test_material_manager_standalone_slot_mapping(self):
        """Verify LiveSyncMaterialManager initializes non-empty slots and assigns proper slot indices to entity blocks."""
        from utils.live_sync.material_manager import LiveSyncMaterialManager
        from utils.live_sync.classifier import parse_and_classify
        mat_mgr = LiveSyncMaterialManager()
        self.assertGreater(len(mat_mgr._slot_to_chunk), 0)
        self.assertGreater(len(mat_mgr.chunk_to_slot), 0)

        # Nether portal uses animation chunk (Chunk 1)
        portal_res = mat_mgr.resolve_block_face(parse_and_classify("minecraft:nether_portal[axis=x]"), "north", 5)
        self.assertEqual(portal_res.chunk_id, 1)
        self.assertEqual(portal_res.slot_index, mat_mgr.get_slot_for_chunk(1))

        # End portal uses starry entity chunk (Chunk 17)
        end_portal_res = mat_mgr.resolve_block_face(parse_and_classify("minecraft:end_portal"), "top", 2)
        self.assertEqual(end_portal_res.chunk_id, 17)
        self.assertEqual(end_portal_res.slot_index, mat_mgr.get_slot_for_chunk(17))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])


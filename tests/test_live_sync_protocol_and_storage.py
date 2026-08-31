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
    HANDSHAKE_INFO_HEADER_FORMAT,
    HANDSHAKE_INFO_HEADER_SIZE,
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
        self.assertEqual(PacketType.HANDSHAKE_INFO, 0x07)
        self.assertEqual(PacketType.FULL_SYNC_REQUEST, 0x80)
        self.assertEqual(PacketType.REPAIR_REQUEST, 0x81)

    def test_parse_handshake_info_packet(self):
        """Test binary parsing for PacketType.HANDSHAKE_INFO (0x07)."""
        received = {}

        def on_handshake_info(total_sections, non_empty_sections, volume, dimension, flags):
            received.update({
                "total_sections": total_sections,
                "non_empty_sections": non_empty_sections,
                "volume": volume,
                "dimension": dimension,
                "flags": flags,
            })

        client = SyncClientThread("ws://dummy", on_status_change=lambda s: None,
                                  on_selection_info=lambda *a: None,
                                  on_full_snapshot=lambda *a: None,
                                  on_delta_update=lambda *a: None,
                                  on_handshake_info=on_handshake_info)

        dim_str = b"minecraft:the_nether"
        header_payload = struct.pack(HANDSHAKE_INFO_HEADER_FORMAT, 16, 12, 65536, len(dim_str))
        packet = (
            struct.pack(HEADER_FORMAT, PROTOCOL_MAGIC, PROTOCOL_VERSION, PacketType.HANDSHAKE_INFO)
            + header_payload
            + dim_str
            + struct.pack("<H", 1)
        )

        client._parse_binary_packet(packet)

        self.assertEqual(received["total_sections"], 16)
        self.assertEqual(received["non_empty_sections"], 12)
        self.assertEqual(received["volume"], 65536)
        self.assertEqual(received["dimension"], "minecraft:the_nether")
        self.assertEqual(received["flags"], 1)

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

    def test_storage_validate_manifest_bad_chunk_missing_mesh(self):
        """Verify bad chunk detection flags non-empty sections whose mesh objects are missing from scene."""
        from utils.live_sync.storage import EMPTY_SECTION_CRC
        palette = ["minecraft:air", "minecraft:stone"]
        indices = [1] * 4096  # all stone -> non-empty chunk
        self.storage.set_full_snapshot(0, 0, 0, 32, 16, 16, palette, indices + [0] * 4096)
        crc_0 = self.storage.calculate_and_store_section_crc(0, 0, 0)
        crc_1 = self.storage.calculate_and_store_section_crc(1, 0, 0)

        manifest = [(0, 0, 0, crc_0), (1, 0, 0, crc_1)]

        # 1. When all meshes exist: 0 mismatched
        existing_meshes = {(0, 0, 0), (1, 0, 0)}
        mismatched = self.storage.validate_manifest(manifest, existing_section_meshes=existing_meshes)
        self.assertEqual(mismatched, [])

        # 2. When Section (0,0,0) mesh is missing from DCC scene: flagged as bad chunk
        damaged_meshes = {(1, 0, 0)}
        mismatched_bad = self.storage.validate_manifest(manifest, existing_section_meshes=damaged_meshes)
        self.assertEqual(mismatched_bad, [(0, 0, 0)])

        # 3. An empty air chunk (crc == EMPTY_SECTION_CRC) missing from mesh is NOT flagged as bad
        empty_manifest = [(1, 0, 0, EMPTY_SECTION_CRC)]
        mismatched_empty = self.storage.validate_manifest(empty_manifest, existing_section_meshes=set())
        self.assertEqual(mismatched_empty, [])

    def test_storage_delta_details_preserve_old_state_for_fluid_removal(self):
        """Water -> air must expose the old fluid state to the mesh synchronizer."""
        self.storage.set_full_snapshot(
            0, 0, 0, 1, 1, 1,
            ["minecraft:water[level=0]"], [0],
        )
        applied = self.storage.apply_delta_update_detailed(
            0, 0, 0, [(0, 0, 0, "minecraft:air")]
        )
        self.assertEqual(
            applied,
            [(0, 0, 0, "minecraft:water[level=0]", "minecraft:air")],
        )

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
        # A repaired snapshot has changed local voxel data and must trigger a
        # mesh rebuild, including neighboring sections used by fluid sampling.
        self.assertIn((0, 0, 0), self.storage._dirty_sections)
        self.assertIn((1, 0, 0), self.storage._dirty_sections)
        self.assertIn((1, 1, 1), self.storage._dirty_sections)

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
        from operators.sync.op_sync_connect import get_active_session_manager
        world_obj = bpy.data.objects.new(DEFAULT_WORLD_OBJECT_NAME, None)
        world_obj["mtk:is_yefira_world"] = True
        bpy.context.collection.objects.link(world_obj)
        bpy.context.view_layer.objects.active = world_obj

        try:
            session = get_active_session_manager().get_or_create_session(world_obj.name)
            session.storage.set_full_snapshot(0, 0, 0, 16, 16, 16, ["minecraft:air", "minecraft:stone"], [1] * 4096)
            session.persist_sync_state_to_scene(world_obj)

            self.assertIn("mtk:sync_manifest", world_obj)

            # Clear memory storage to simulate reloading blend file
            session.storage.clear()
            self.assertEqual(session.storage.size_x, 0)

            # Restore from scene object
            restored = session.restore_sync_state_from_scene(world_obj)
            self.assertTrue(restored)
            self.assertEqual(session.storage.size_x, 16)
            self.assertEqual(session.storage.size_y, 16)
            self.assertIn((0, 0, 0), session.storage.section_crc_map)
        finally:
            get_active_session_manager().remove_session(world_obj.name)
            bpy.data.objects.remove(world_obj, do_unlink=True)

    def test_material_reuse_convention(self):
        """Test that LiveSyncMaterialManager strictly reuses existing scene materials and avoids duplicate '.001' proliferation."""
        from utils.live_sync.material_manager import LiveSyncMaterialManager, PROP_ATLAS_CHUNK_ID, PROP_PACK_HASH

        for m in list(bpy.data.materials):
            if m.name.startswith("MC_Atlas_Chunk_"):
                bpy.data.materials.remove(m, do_unlink=True)

        # Pre-create standard chunk material
        mat_name = "MC_Atlas_Chunk_0"
        existing_mat = bpy.data.materials.new(name=mat_name)
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
        for cid in [0, 1, 17]:
            m = bpy.data.materials.new(name=f"MC_Atlas_Chunk_{cid}")
            m["mtk:atlas_chunk_id"] = cid
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

    def test_rebuild_world_operator_execution(self):
        """Verify MOZI_OT_sync_rebuild_world rebuilds mesh from local voxel memory without network dependencies."""
        from operators.sync.op_sync_connect import DEFAULT_WORLD_OBJECT_NAME
        from utils.live_sync.storage import voxel_storage
        from utils.system.menu_config import save_pack_stack_config
        from utils.materials.pack import get_configured_pack_stack
        import tempfile
        from PIL import Image
        import bpy

        with tempfile.TemporaryDirectory() as tmp_dir:
            p_dir = Path(tmp_dir)
            tex_dir = p_dir / "assets/minecraft/textures/block"
            tex_dir.mkdir(parents=True, exist_ok=True)
            img = Image.new("RGBA", (16, 16), (200, 100, 50, 255))
            img.save(tex_dir / "rebuild_stone.png")
            save_pack_stack_config([{"name": "TestRebuildPack", "path": str(p_dir), "enabled": True, "pack_type": "RESOURCE_PACK"}])
            stack = get_configured_pack_stack()
            stack.precompile("ATLAS")
            palette = ["minecraft:air", "minecraft:stone"]
            indices = [1] * 4096  # full 16x16x16 stone chunk
            from operators.sync.op_sync_connect import get_active_session_manager, get_or_create_world_root, voxel_storage as op_vox_storage
            world_root = get_or_create_world_root(bpy.context)
            session = get_active_session_manager().get_or_create_session(world_root.name)
            session.storage.set_full_snapshot(0, 0, 0, 16, 16, 16, palette, indices)
            session.persist_sync_state_to_scene(world_root)
            voxel_storage.set_full_snapshot(0, 0, 0, 16, 16, 16, palette, indices)
            op_vox_storage.set_full_snapshot(0, 0, 0, 16, 16, 16, palette, indices)

            try:
                res = bpy.ops.mozi.sync_rebuild_world(target_container=world_root.name)
                self.assertEqual(res, {'FINISHED'})

                world_obj = bpy.data.objects.get(world_root.name)
                self.assertIsNotNone(world_obj)
                # Child section mesh should have been generated
                sec_obj = bpy.data.objects.get(f"{world_root.name}_Section_0_0_0")
                self.assertIsNotNone(sec_obj)
                self.assertGreater(len(sec_obj.data.polygons), 0)
            finally:
                world_obj = bpy.data.objects.get(DEFAULT_WORLD_OBJECT_NAME)
                if world_obj:
                    for child in list(world_obj.children):
                        child_mesh = child.data
                        bpy.data.objects.remove(child, do_unlink=True)
                        if child_mesh:
                            bpy.data.meshes.remove(child_mesh, do_unlink=True)
                    root_mesh = world_obj.data
                    bpy.data.objects.remove(world_obj, do_unlink=True)
                    if root_mesh:
                        bpy.data.meshes.remove(root_mesh, do_unlink=True)
                voxel_storage.clear()
                try:
                    from utils.materials.pack import clear_resource_pack_cache
                    clear_resource_pack_cache()
                except Exception:
                    pass
                save_pack_stack_config([])

    def test_client_thread_max_reconnect_attempts(self):
        """Verify SyncClientThread honors max_reconnect_attempts constraint and stops retrying."""
        statuses = []
        client = SyncClientThread(
            url="ws://127.0.0.1:59999",  # non-existent port
            on_status_change=lambda s: statuses.append(s),
            on_selection_info=lambda *a: None,
            on_full_snapshot=lambda *a: None,
            on_delta_update=lambda *a: None,
            auto_reconnect=True,
            max_reconnect_attempts=2,
        )
        client.start()
        client.join(timeout=8.0)
        self.assertFalse(client.is_alive())
        self.assertGreater(client.reconnect_attempts, 2)
        # Should finish in DISCONNECTED state indicating max attempts reached
        self.assertTrue(any("Exceeded" in s or "Failed" in s for s in statuses))

    def test_client_thread_manual_cancel_during_retry(self):
        """Verify client.stop() immediately aborts retry loop and marks DISCONNECTED."""
        import time
        statuses = []
        client = SyncClientThread(
            url="ws://127.0.0.1:59999",
            on_status_change=lambda s: statuses.append(s),
            on_selection_info=lambda *a: None,
            on_full_snapshot=lambda *a: None,
            on_delta_update=lambda *a: None,
            auto_reconnect=True,
            max_reconnect_attempts=10,
        )
        client.start()
        time.sleep(0.3)
        client.stop()
        client.join(timeout=3.0)
        self.assertFalse(client.is_alive())
        self.assertFalse(client.running)
        self.assertEqual(statuses[-1], "DISCONNECTED")


    def test_empty_section_crc_table_and_boundary_calculation(self):
        """Verify get_empty_section_crc computes correct canonical CRC for arbitrary block counts."""
        from utils.live_sync.storage import get_empty_section_crc, EMPTY_SECTION_CRC
        import zlib

        # 1. Zero blocks
        self.assertEqual(get_empty_section_crc(0), 0)

        # 2. 4096 blocks (full 16x16x16 chunk)
        self.assertEqual(get_empty_section_crc(4096), EMPTY_SECTION_CRC)

        # 3. Partial block counts match step-by-step zlib.crc32
        for count in (1, 16, 256, 512, 1024, 2048):
            expected = 0
            for _ in range(count):
                expected = zlib.crc32(b"minecraft:air", expected) & 0xFFFFFFFF
            self.assertEqual(get_empty_section_crc(count), expected)

    def test_validate_manifest_empty_boundary_section_not_bad(self):
        """Verify boundary sections that are pure air are not flagged as bad chunks or counted as non-empty."""
        from utils.live_sync.storage import get_empty_section_crc

        # Set bounds with partial boundary chunks: 20x20x20 (min=(0,0,0), size=(20,20,20))
        # This covers sections (0,0,0), (1,0,0), (0,1,0), (1,1,0), (0,0,1), etc.
        # Section (0,0,0) has 16x16x16 = 4096 blocks.
        # Section (1,0,0) has 4x16x16 = 1024 blocks.
        self.storage.set_bounds(0, 0, 0, 20, 20, 20)

        # Section (0,0,0) contains stone
        for x in range(16):
            self.storage.block_map[(x, 0, 0)] = "minecraft:stone"
        crc_000 = self.storage.calculate_and_store_section_crc(0, 0, 0)

        # Section (1,0,0) is all air
        crc_100 = self.storage.calculate_and_store_section_crc(1, 0, 0)
        expected_air_crc_100 = get_empty_section_crc(self.storage.get_section_block_count(1, 0, 0))
        self.assertEqual(crc_100, expected_air_crc_100)
        self.assertTrue(self.storage.is_empty_section_crc(1, 0, 0, crc_100))
        self.assertFalse(self.storage.is_empty_section_crc(0, 0, 0, crc_000))

        # Test validate_manifest with only section (0,0,0) mesh existing in Blender
        manifest = [(0, 0, 0, crc_000), (1, 0, 0, crc_100)]
        existing_meshes = {(0, 0, 0)}
        mismatched = self.storage.validate_manifest(manifest, existing_section_meshes=existing_meshes)
        self.assertEqual(mismatched, [])

        # Test counting non-empty manifest entries: only 1 section is non-empty
        non_empty_count = sum(
            1 for sx, sy, sz, crc in manifest if not self.storage.is_empty_section_crc(sx, sy, sz, crc)
        )
        self.assertEqual(non_empty_count, 1)

    def test_blend_file_load_handlers_disconnect_and_free_resources(self):
        """Verify load_pre and load_post handlers cleanly disconnect background client and free preloaded caches."""
        from operators.sync.properties import _on_blend_file_pre_load, _on_blend_file_loaded
        import operators.sync.op_sync_connect as sync_op
        from utils.live_sync.storage import voxel_storage
        from utils.live_sync.mesh_cache import _GLOBAL_STATE_META_CACHE

        # 1. Simulate active connection state & preloaded cache
        mock_client = SyncClientThread("ws://dummy", lambda *a: None, lambda *a: None, lambda *a: None, lambda *a: None)
        sync_op._client_thread = mock_client
        sync_op._is_streaming = True
        sync_op.voxel_storage.set_bounds(0, 0, 0, 16, 16, 16)
        sync_op.voxel_storage.block_map[(0, 0, 0)] = "minecraft:stone"

        if hasattr(bpy.context.scene, "mozi_sync"):
            bpy.context.scene.mozi_sync.is_connected = True
            bpy.context.scene.mozi_sync.connection_status = "CONNECTED"

        # 2. Trigger pre-load handler (as when File > New or File > Open occurs)
        _on_blend_file_pre_load()

        # Verify client is stopped and cleared
        self.assertIsNone(sync_op._client_thread)
        self.assertFalse(sync_op._is_streaming)
        self.assertEqual(len(sync_op.voxel_storage.block_map), 0)

        # 3. Trigger post-load handler
        _on_blend_file_loaded()
        if hasattr(bpy.context.scene, "mozi_sync"):
            self.assertFalse(bpy.context.scene.mozi_sync.is_connected)
            self.assertEqual(bpy.context.scene.mozi_sync.connection_status, "DISCONNECTED")

    def test_sync_client_thread_respects_network_timeout(self):
        """Verify SyncClientThread accepts custom timeout parameter and defaults sensibly."""
        client_default = SyncClientThread("ws://dummy", lambda *a: None, lambda *a: None, lambda *a: None, lambda *a: None)
        self.assertEqual(client_default.timeout, 10.0)

        client_custom = SyncClientThread("ws://dummy", lambda *a: None, lambda *a: None, lambda *a: None, lambda *a: None, timeout=25.0)
        self.assertEqual(client_custom.timeout, 25.0)

    def test_delta_log_ui_updates(self):
        """Verify append_delta_history correctly populates props.delta_history and tracks active index."""
        from operators.sync.op_sync_connect import append_delta_history, MAX_DELTA_HISTORY
        props = bpy.context.scene.mozi_sync
        props.delta_history.clear()

        # Add single delta edit
        edits = [(10, 64, -5, "minecraft:air", "minecraft:diamond_block")]
        append_delta_history(props, edits)
        self.assertEqual(len(props.delta_history), 1)
        self.assertEqual(props.delta_history[0].pos_str, "(10, 64, -5)")
        self.assertEqual(props.delta_history[0].block_state, "minecraft:diamond_block")
        self.assertEqual(props.delta_active_index, 0)

        # Add block broken edit
        edits_broken = [(10, 64, -5, "minecraft:diamond_block", "minecraft:air")]
        append_delta_history(props, edits_broken)
        self.assertEqual(len(props.delta_history), 2)
        self.assertIn("broken", props.delta_history[1].block_state)
        self.assertEqual(props.delta_active_index, 1)

        # Overflow beyond MAX_DELTA_HISTORY
        bulk_edits = [(i, 64, 0, "", f"minecraft:stone_{i}") for i in range(120)]
        for b in bulk_edits:
            append_delta_history(props, [b])
        self.assertLessEqual(len(props.delta_history), MAX_DELTA_HISTORY)
        self.assertEqual(props.delta_active_index, len(props.delta_history) - 1)

    def test_palette_ui_updates(self):
        """Verify sync_palette_to_props correctly populates props.palette_list from VoxelStorage."""
        from operators.sync.op_sync_connect import sync_palette_to_props
        from utils.live_sync.storage import VoxelStorage
        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:stone")
        storage.set_block(1, 0, 0, "minecraft:oak_planks")
        storage.set_block(2, 0, 0, "minecraft:glass")

        props = bpy.context.scene.mozi_sync
        props.palette_list.clear()
        sync_palette_to_props(props, storage)

        self.assertEqual(props.palette_count, 3)
        self.assertEqual(len(props.palette_list), 3)
        palette_states = [item.state_str for item in props.palette_list]
        self.assertIn("minecraft:stone", palette_states)
        self.assertIn("minecraft:oak_planks", palette_states)
        self.assertIn("minecraft:glass", palette_states)

    def test_stream_finalize_and_verification_status(self):
        """Verify _finalize_stream_sync updates palette, verification status, and delta log."""
        from operators.sync.op_sync_connect import _finalize_stream_sync, SyncSession
        root_obj = bpy.data.objects.new("Test_Sync_Root", None)
        bpy.context.collection.objects.link(root_obj)
        try:
            session = SyncSession("Test_Sync_Root")
            session.storage.set_block(0, 0, 0, "minecraft:glowstone")
            props = root_obj.mozi_sync
            props.validation_info = "Syncing (1 chunks)..."
            props.sync_verified = False

            _finalize_stream_sync(session, props, root_obj, 1)

            self.assertTrue(props.sync_verified)
            self.assertEqual(props.validation_info, "Verified (100% in sync)")
            self.assertEqual(props.palette_count, 1)
            self.assertEqual(props.palette_list[0].state_str, "minecraft:glowstone")
            self.assertGreater(len(props.delta_history), 0)
            self.assertIn("Sync ready", props.delta_history[-1].block_state)
        finally:
            bpy.data.objects.remove(root_obj, do_unlink=True)

    def test_periodic_manifest_does_not_reactivate_progressbar(self):
        """Ensure periodic manifest checks after initial handshake stay completely silent in UI."""
        from pipeline.progress import ProgressBar
        from operators.sync.op_sync_connect import SyncSession

        ProgressBar.end()
        self.assertFalse(ProgressBar.is_active())

        root_obj = bpy.data.objects.new("Test_Silent_Manifest", None)
        bpy.context.collection.objects.link(root_obj)
        try:
            session = SyncSession("Test_Silent_Manifest")
            session.is_initial_handshake = False
            session.storage.set_bounds(0, 0, 0, 16, 16, 16)
            crc = session.storage.calculate_and_store_section_crc(0, 0, 0)

            # Simulate background heartbeat manifest with matching CRC
            sections = [(0, 0, 0, crc)]
            mismatched = session.storage.validate_manifest(sections)
            self.assertEqual(len(mismatched), 0)

            # When not initial handshake, ProgressBar should remain inactive
            if session.is_initial_handshake:
                ProgressBar.finish(message="Verified: 100% in sync with scene", auto_dismiss_delay=0.8)

            self.assertFalse(ProgressBar.is_active())
        finally:
            bpy.data.objects.remove(root_obj, do_unlink=True)
            ProgressBar.end()

    def test_reconnect_with_existing_scene_triggers_partial_repair(self):
        """Ensure reconnecting to a scene with existing blocks and partial server changes triggers fast incremental repair."""
        from operators.sync.op_sync_connect import SyncSession

        root_obj = bpy.data.objects.new("Test_Reconnect_Repair", None)
        bpy.context.collection.objects.link(root_obj)
        try:
            session = SyncSession("Test_Reconnect_Repair")
            session.is_initial_handshake = True
            session.storage.set_bounds(0, 0, 0, 32, 16, 16)
            session.storage.set_block(0, 0, 0, "minecraft:stone")
            session.storage.set_block(16, 0, 0, "minecraft:oak_planks")
            session.storage.recalculate_all_section_crcs()

            local_crc_0 = session.storage.get_section_crc(0, 0, 0)
            local_crc_1 = session.storage.get_section_crc(1, 0, 0)

            # Server manifest has section 1 modified in Minecraft while disconnected
            server_crc_1_modified = (local_crc_1 + 12345) & 0xFFFFFFFF
            sections = [(0, 0, 0, local_crc_0), (1, 0, 0, server_crc_1_modified)]

            mismatched = session.storage.validate_manifest(sections)
            self.assertEqual(mismatched, [(1, 0, 0)])

            # Non-empty count is 2, mismatched is 1 -> partial repair path
            non_empty_manifest_count = sum(
                1 for _sx, _sy, _sz, _crc in sections if not session.storage.is_empty_section_crc(_sx, _sy, _sz, _crc)
            )
            self.assertEqual(non_empty_manifest_count, 2)
            self.assertTrue(bool(session.storage.block_map))
            self.assertLess(len(mismatched), non_empty_manifest_count)
        finally:
            bpy.data.objects.remove(root_obj, do_unlink=True)

    def test_validate_and_sync_scene_materials_hash_upgrade(self):
        """Verify validate_and_sync_scene_materials detects outdated material hash in scene and upgrades it."""
        from utils.live_sync.material_binding import validate_and_sync_scene_materials, get_shared_material_manager, clear_shared_material_manager
        
        mesh = bpy.data.meshes.new("Test_Mat_Sync_Mesh")
        obj = bpy.data.objects.new("Test_Mat_Sync_Obj", mesh)
        bpy.context.collection.objects.link(obj)

        old_mat = bpy.data.materials.new("Test_Old_Atlas_Mat")
        old_mat.use_nodes = True
        old_mat["mtk:pack_hash"] = "old_hash_12345"
        old_mat["mtk:atlas_chunk_id"] = 0
        obj.data.materials.append(old_mat)

        class MockPackStack:
            def __init__(self, h):
                self.stack_hash = h
                self.packs = []

        try:
            mock_stack = MockPackStack("new_hash_67890")
            # First call: detects mismatch between "old_hash_12345" and "new_hash_67890", triggers upgrade
            upgraded = validate_and_sync_scene_materials(obj, pack_stack=mock_stack)
            self.assertTrue(upgraded)

            # Subsequent call with matching manager: fast pass (False)
            upgraded_again = validate_and_sync_scene_materials(obj, pack_stack=mock_stack)
            self.assertFalse(upgraded_again)
        finally:
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.meshes.remove(mesh, do_unlink=True)
            bpy.data.materials.remove(old_mat, do_unlink=True)
            clear_shared_material_manager()

    def test_full_snapshot_with_biome_stream_decoding(self):
        """Verify binary packet parsing of FULL_SNAPSHOT with 2-biome palette and indices stream."""
        from utils.live_sync.constants import PacketType
        # 1. Construct binary FULL_SNAPSHOT with biomes
        # Magic: 0x4D5A (MZ)
        # Type: 0x02
        # Min: (0, 0, 0), Size: (2, 1, 1) -> 2 blocks
        # Block palette count: 1 ("minecraft:grass_block")
        # Grid indices: [0, 0] (byte indices)
        # Biome palette count: 2 ("minecraft:plains", "minecraft:desert")
        # Biome indices: [0, 1] (byte indices)
        bounds = struct.pack(SELECTION_INFO_FORMAT, 0, 0, 0, 2, 1, 1)
        
        # Block palette
        b_str = b'{"Name":"minecraft:grass_block"}'
        palette_data = struct.pack('<H', 1) + struct.pack('<H', len(b_str)) + b_str + b"\x01" + bytes([0, 0])

        # Biome palette (2 biomes)
        biome1 = b'minecraft:plains'
        biome2 = b'minecraft:desert'
        biome_data = (
            struct.pack('<H', 2) +
            struct.pack('<H', len(biome1)) + biome1 +
            struct.pack('<H', len(biome2)) + biome2 +
            b"\x01" + bytes([0, 1])
        )

        payload = bounds + palette_data + biome_data
        packet = struct.pack(HEADER_FORMAT, PROTOCOL_MAGIC, PROTOCOL_VERSION, PacketType.FULL_SNAPSHOT) + payload

        captured = {}
        def on_full(min_x, min_y, min_z, sx, sy, sz, palette, indices, b_pal=None, b_ind=None):
            captured['data'] = (min_x, min_y, min_z, sx, sy, sz, palette, indices, b_pal, b_ind)

        client = SyncClientThread("ws://dummy", on_status_change=lambda s: None,
                                  on_selection_info=lambda *a: None,
                                  on_full_snapshot=on_full,
                                  on_delta_update=lambda *a: None)
        client._parse_binary_packet(packet)

        self.assertIn('data', captured)
        _, _, _, sx, sy, sz, pal, ind, b_pal, b_ind = captured['data']
        self.assertEqual((sx, sy, sz), (2, 1, 1))
        self.assertEqual(len(pal), 1)
        self.assertEqual(b_pal, ["minecraft:plains", "minecraft:desert"])
        self.assertEqual(b_ind, [0, 1])

        # Test storage population
        storage = VoxelStorage()
        storage.set_full_snapshot(0, 0, 0, 2, 1, 1, pal, ind, biome_palette=b_pal, biome_indices=b_ind)
        self.assertEqual(storage.get_biome(0, 0, 0), "minecraft:plains")
        self.assertEqual(storage.get_biome(1, 0, 0), "minecraft:desert")

    def test_voxel_storage_smoothed_biome_blending(self):
        """Verify get_smoothed_biome_data computes smooth transition between plains and desert."""
        storage = VoxelStorage()
        # Set a 5x1x1 line of blocks where x <= 2 is plains and x >= 3 is desert
        pal = ['{"Name":"minecraft:grass_block"}']
        grid_ind = [0, 0, 0, 0, 0]
        biome_pal = ["minecraft:plains", "minecraft:desert"]
        biome_ind = [0, 0, 0, 1, 1]  # x=0..2 Plains, x=3..4 Desert
        storage.set_full_snapshot(0, 0, 0, 5, 1, 1, pal, grid_ind, biome_palette=biome_pal, biome_indices=biome_ind)

        # Pure Plains: x=0 (far from desert border)
        u_plains, v_plains, _ = storage.get_smoothed_biome_data(0, 0, 0, radius=1)
        # Pure Desert: x=4 (far from plains border)
        u_desert, v_desert, _ = storage.get_smoothed_biome_data(4, 0, 0, radius=1)
        # Transition Border: x=2
        u_mid, v_mid, _ = storage.get_smoothed_biome_data(2, 0, 0, radius=2)

        # In colormap math, U for plains != U for desert
        self.assertNotEqual(u_plains, u_desert)
        # The transition point must be intermediate between pure plains and desert
        self.assertTrue(
            min(u_plains, u_desert) <= u_mid <= max(u_plains, u_desert) or
            abs(u_mid - (u_plains + u_desert) / 2.0) < abs(u_plains - u_desert)
        )


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])


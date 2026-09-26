"""
Unit test for mock_sync_server binary packet encoding and streaming logic.
"""

import struct
import unittest

from tools.mock_sync_server import (
    PROTOCOL_MAGIC,
    PROTOCOL_VERSION,
    PKT_SELECTION_INFO,
    PKT_FULL_SNAPSHOT,
    PKT_DELTA_UPDATE,
    PKT_HANDSHAKE_INFO,
    encode_selection_info,
    encode_handshake_info,
    encode_full_snapshot,
    encode_delta_update,
    decode_client_packet,
    generate_terrain,
)


class TestMockSyncServer(unittest.TestCase):
    def test_encode_selection_info(self):
        pkt = encode_selection_info((0, 64, 0), (16, 16, 16))
        self.assertEqual(pkt[0:2], PROTOCOL_MAGIC)
        self.assertEqual(pkt[2], PROTOCOL_VERSION)
        self.assertEqual(pkt[3], PKT_SELECTION_INFO)
        min_x, min_y, min_z, sx, sy, sz = struct.unpack("<6i", pkt[4:28])
        self.assertEqual((min_x, min_y, min_z), (0, 64, 0))
        self.assertEqual((sx, sy, sz), (16, 16, 16))

    def test_encode_handshake_info(self):
        pkt = encode_handshake_info(8, 4, 4096, "minecraft:overworld")
        self.assertEqual(pkt[0:2], PROTOCOL_MAGIC)
        self.assertEqual(pkt[3], PKT_HANDSHAKE_INFO)
        tot_sec, non_empty, vol, dim_len = struct.unpack("<3IH", pkt[4:18])
        self.assertEqual(tot_sec, 8)
        self.assertEqual(non_empty, 4)
        self.assertEqual(vol, 4096)
        dim = pkt[18:18 + dim_len].decode("utf-8")
        self.assertEqual(dim, "minecraft:overworld")

    def test_procedural_generation_presets(self):
        for preset in ["flat", "hills", "complex", "fluids", "benchmark"]:
            grid = generate_terrain(preset, (0, 64, 0), (16, 16, 16))
            self.assertGreater(len(grid.palette), 1)
            self.assertEqual(len(grid.indices), 16 * 16 * 16)

    def test_decode_client_packet(self):
        # 0x80 Full Sync
        pkt_full = PROTOCOL_MAGIC + bytes([PROTOCOL_VERSION, 0x80])
        decoded = decode_client_packet(pkt_full)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded["type"], "REQ_FULL_SYNC")

        # 0x82 Sync Config
        pkt_cfg = PROTOCOL_MAGIC + bytes([PROTOCOL_VERSION, 0x82, 0x01, 0x3C, 0x01])
        decoded_cfg = decode_client_packet(pkt_cfg)
        self.assertIsNotNone(decoded_cfg)
        self.assertEqual(decoded_cfg["throttle_mode"], 1)
        self.assertEqual(decoded_cfg["target_fps"], 60)
        self.assertTrue(decoded_cfg["is_active"])


if __name__ == "__main__":
    unittest.main()

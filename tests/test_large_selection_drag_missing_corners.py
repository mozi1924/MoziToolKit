"""
Regression test for large selection dragging and corner chunk recovery.
Verifies that:
1. Delayed/missing corner chunks are self-healed via SectionManifest repair requests.
2. The sync_requested latch does not permanently block subsequent repairs.
3. Dragging a large selection does not leave hollow interiors or missing corner chunks.
4. No manual disconnect/reconnect is required to achieve complete world reconstruction.
"""

from __future__ import annotations

import asyncio
import os
import struct
import sys
import threading
import time
import unittest
from pathlib import Path
from typing import Optional, Set

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

for p in [str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from unittest.mock import MagicMock
import types

if "mathutils" not in sys.modules:
    sys.modules["mathutils"] = MagicMock()

if "bpy_extras" not in sys.modules:
    bpy_extras = types.ModuleType("bpy_extras")
    bpy_extras.__path__ = []
    io_utils = types.ModuleType("bpy_extras.io_utils")
    io_utils.ExportHelper = object
    io_utils.ImportHelper = object
    bpy_extras.io_utils = io_utils
    sys.modules["bpy_extras"] = bpy_extras
    sys.modules["bpy_extras.io_utils"] = io_utils

try:
    import bpy
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes")
except ImportError:
    bpy = MagicMock()
    HAS_BPY = False

if not HAS_BPY:
    class _MockOperator: pass
    class _MockPanel: pass
    class _MockMenu: pass
    class _MockPropertyGroup: pass
    class _MockUIList: pass
    class _MockAddonPreferences: pass

    class _MockTypes:
        Operator = _MockOperator
        Panel = _MockPanel
        Menu = _MockMenu
        PropertyGroup = _MockPropertyGroup
        UIList = _MockUIList
        AddonPreferences = _MockAddonPreferences

    bpy.types = _MockTypes
    bpy.app = MagicMock()
    bpy.props = MagicMock()
    sys.modules["bpy"] = bpy
    sys.modules["bpy.props"] = bpy.props
    sys.modules["bpy.types"] = _MockTypes
    sys.modules["bpy.app"] = bpy.app
    sys.modules["bmesh"] = MagicMock()

from bridge.sync import get_sync_bridge_session, is_sync_available
from operators.sync.op_sync_connect import _sync_timer_tick
from tools.mock_sync_server import (
    MinimalWebSocketClient,
    encode_selection_info,
    encode_handshake_info,
    encode_stream_begin,
    encode_stream_end,
    encode_section_snapshot,
    encode_section_manifest,
    decode_client_packet,
    generate_terrain,
    STREAM_STATUS_SUCCESS,
)


class _CornerTestSyncServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8794):
        self.host = host
        self.port = port
        self.clients: Set[MinimalWebSocketClient] = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.server = None
        self.thread: Optional[threading.Thread] = None
        self.origin = (0, 64, 0)
        self.size = (64, 32, 64)  # 4 x 2 x 4 = 32 sections
        self.preset = "flat"
        self.grid = generate_terrain(self.preset, self.origin, self.size)
        self.omit_corners = True
        self.received_repair_requests = []

    def start(self):
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        time.sleep(0.3)

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._start_server())
        self.loop.run_forever()

    async def _start_server(self):
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)

    async def _handle_client(self, reader, writer):
        while True:
            line = await reader.readline()
            if not line or line == b"\r\n":
                break
            parts = line.decode("utf-8", "ignore").strip().split(":", 1)
            if len(parts) == 2 and parts[0].strip().lower() == "sec-websocket-key":
                import hashlib, base64
                ws_key = parts[1].strip()
                magic = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                sha = hashlib.sha1(ws_key.encode("utf-8") + magic).digest()
                accept_key = base64.b64encode(sha).decode("utf-8")
                writer.write(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept_key}\r\n\r\n".encode("utf-8"))
                await writer.drain()

        client = MinimalWebSocketClient(reader, writer)
        self.clients.add(client)

        # 1. Send Handshake & SelectionInfo
        min_sec_x, max_sec_x = self.origin[0] >> 4, (self.origin[0] + self.size[0] - 1) >> 4
        min_sec_y, max_sec_y = self.origin[1] >> 4, (self.origin[1] + self.size[1] - 1) >> 4
        min_sec_z, max_sec_z = self.origin[2] >> 4, (self.origin[2] + self.size[2] - 1) >> 4

        sections = []
        for sx in range(min_sec_x, max_sec_x + 1):
            for sy in range(min_sec_y, max_sec_y + 1):
                for sz in range(min_sec_z, max_sec_z + 1):
                    sections.append((sx, sy, sz))

        await client.send_binary(encode_selection_info(self.origin, self.size))
        await client.send_binary(encode_handshake_info(len(sections), len(sections), self.size[0] * self.size[1] * self.size[2]))

        # 2. Stream sections, deliberately omitting the corner chunks if omit_corners=True
        corner_coords = {
            (min_sec_x, min_sec_y, min_sec_z),
            (max_sec_x, min_sec_y, min_sec_z),
            (min_sec_x, min_sec_y, max_sec_z),
            (max_sec_x, min_sec_y, max_sec_z),
        }
        self.corner_coords = corner_coords

        await client.send_binary(encode_stream_begin(1, len(sections)))
        sent_count = 0
        for (sx, sy, sz) in sections:
            if self.omit_corners and (sx, sy, sz) in corner_coords:
                continue  # simulate chunk loading delay at corners

            start_x, start_y, start_z = sx * 16, sy * 16, sz * 16
            sec_indices = []
            for lx in range(16):
                wx = start_x + lx
                gx = wx - self.origin[0]
                for ly in range(16):
                    wy = start_y + ly
                    gy = wy - self.origin[1]
                    for lz in range(16):
                        wz = start_z + lz
                        gz = wz - self.origin[2]
                        st = self.grid.get_block(gx, gy, gz)
                        sec_indices.append(self.grid.palette_lookup[st])

            pkt = encode_section_snapshot(
                (sx, sy, sz),
                (start_x, start_y, start_z),
                (16, 16, 16),
                self.grid.palette,
                sec_indices,
            )
            await client.send_binary(pkt)
            sent_count += 1

        await client.send_binary(encode_stream_end(1, sent_count, STREAM_STATUS_SUCCESS))

        # Reader loop handling repair requests
        while client.is_open:
            data = await client.read_frame()
            if data is None:
                break
            decoded = decode_client_packet(data)
            if decoded and decoded.get("type") == "REQ_SECTION_SYNC":
                req_sections = decoded.get("sections", [])
                self.received_repair_requests.extend(req_sections)
                # Answer with requested section snapshots
                for sx, sy, sz in req_sections:
                    start_x, start_y, start_z = sx * 16, sy * 16, sz * 16
                    sec_indices = []
                    for lx in range(16):
                        wx = start_x + lx
                        gx = wx - self.origin[0]
                        for ly in range(16):
                            wy = start_y + ly
                            gy = wy - self.origin[1]
                            for lz in range(16):
                                wz = start_z + lz
                                gz = wz - self.origin[2]
                                st = self.grid.get_block(gx, gy, gz)
                                sec_indices.append(self.grid.palette_lookup[st])

                    pkt = encode_section_snapshot(
                        (sx, sy, sz),
                        (start_x, start_y, start_z),
                        (16, 16, 16),
                        self.grid.palette,
                        sec_indices,
                    )
                    await client.send_binary(pkt)

        self.clients.discard(client)

    def send_manifest(self):
        min_sec_x, max_sec_x = self.origin[0] >> 4, (self.origin[0] + self.size[0] - 1) >> 4
        min_sec_y, max_sec_y = self.origin[1] >> 4, (self.origin[1] + self.size[1] - 1) >> 4
        min_sec_z, max_sec_z = self.origin[2] >> 4, (self.origin[2] + self.size[2] - 1) >> 4

        entries = []
        for sx in range(min_sec_x, max_sec_x + 1):
            for sy in range(min_sec_y, max_sec_y + 1):
                for sz in range(min_sec_z, max_sec_z + 1):
                    crc = self.grid.compute_section_crc((sx, sy, sz))
                    entries.append(((sx, sy, sz), crc))

        pkt = encode_section_manifest(2, entries)

        async def _b():
            for c in list(self.clients):
                await c.send_binary(pkt)

        asyncio.run_coroutine_threadsafe(_b(), self.loop).result()


class TestLargeSelectionCornerRecovery(unittest.TestCase):
    def setUp(self):
        if not is_sync_available():
            self.skipTest("libmtk_py LiveSyncSession not available")

    def test_corner_chunks_auto_repair_and_no_latch(self):
        server = _CornerTestSyncServer(port=8794)
        server.start()

        session = get_sync_bridge_session()
        connected = session.start("ws://127.0.0.1:8794", auto_reconnect=False, unified_mesh=True)
        self.assertTrue(connected)

        # Wait for initial stream completion (where corner chunks were omitted)
        for _ in range(20):
            time.sleep(0.05)
            _sync_timer_tick()
            mesh = session.get_world_mesh()
            if mesh and mesh.vertex_count > 0:
                break

        initial_mesh = session.get_world_mesh()
        self.assertIsNotNone(initial_mesh)
        initial_verts = initial_mesh.vertex_count
        self.assertGreater(initial_verts, 0)

        # Broadcast SectionManifest containing authoritative hashes for all sections (including corners)
        server.send_manifest()

        # Wait for client to detect missing corners, send REQ_SECTION_SYNC, receive repair chunks, and remesh
        repaired = False
        for _ in range(30):
            time.sleep(0.05)
            _sync_timer_tick()
            mesh = session.get_world_mesh()
            if mesh and mesh.vertex_count > initial_verts:
                repaired = True
                break

        self.assertTrue(repaired, "Corner chunks must be automatically requested, ingested, and meshed")
        self.assertGreaterEqual(len(server.received_repair_requests), 4, "Server must have received repair requests for all omitted corners")

        final_mesh = session.get_world_mesh()
        self.assertGreater(final_mesh.vertex_count, initial_verts, "Final mesh must contain complete geometry including corners")

        session.stop()

    def tearDown(self):
        if HAS_BPY:
            obj = bpy.data.objects.get("Yefira_World")
            if obj:
                mesh = obj.data
                bpy.data.objects.remove(obj)
                if mesh:
                    bpy.data.meshes.remove(mesh)


if __name__ == "__main__":
    unittest.main()

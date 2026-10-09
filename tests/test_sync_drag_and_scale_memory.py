"""
Integration regression test for Live Sync selection dragging and scaling memory stability.
Verifies that dragging and scaling large selections maintains O(1) steady-state memory
without unbounded allocations, leaks, or OOM crashes.
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
from operators.sync.hierarchy import get_or_create_world_mesh_object
from operators.sync.op_sync_connect import _sync_timer_tick
from tools.mock_sync_server import (
    MinimalWebSocketClient,
    encode_selection_info,
    encode_handshake_info,
    encode_full_snapshot,
    encode_section_snapshot,
    generate_terrain,
)


def _get_rss_mb() -> float:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        pass

    import platform
    if platform.system() == "Darwin":
        try:
            import ctypes
            class _ProcTaskinfo(ctypes.Structure):
                _fields_ = [
                    ("pti_virtual_size", ctypes.c_uint64),
                    ("pti_resident_size", ctypes.c_uint64),
                ]
            info = _ProcTaskinfo()
            lib = ctypes.CDLL(None)
            if lib.proc_pidinfo(os.getpid(), 4, 0, ctypes.byref(info), ctypes.sizeof(info)) > 0:
                return float(info.pti_resident_size) / (1024.0 * 1024.0)
        except Exception:
            pass

    import resource
    max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports `ru_maxrss` in bytes; Linux reports it in kibibytes.
    if platform.system() == "Darwin":
        return max_rss / (1024.0 * 1024.0)
    return max_rss / 1024.0


class _TestControllableSyncServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8797):
        self.host = host
        self.port = port
        self.clients: Set[MinimalWebSocketClient] = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.server = None
        self.thread: Optional[threading.Thread] = None
        self.origin = (0, 64, 0)
        self.size = (32, 32, 32)
        self.preset = "flat"

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

        grid = generate_terrain(self.preset, self.origin, self.size)
        await client.send_binary(encode_selection_info(self.origin, self.size))
        await client.send_binary(encode_handshake_info(8, 4, self.size[0] * self.size[1] * self.size[2]))
        await client.send_binary(encode_full_snapshot(self.origin, self.size, grid.palette, grid.indices))

        while client.is_open:
            data = await client.read_frame()
            if data is None:
                break
        self.clients.discard(client)

    def send_move(self, new_origin):
        self.origin = new_origin
        grid = generate_terrain(self.preset, self.origin, self.size)
        pkt1 = encode_selection_info(self.origin, self.size)
        pkt2 = encode_full_snapshot(self.origin, self.size, grid.palette, grid.indices)

        async def _broadcast():
            for c in list(self.clients):
                await c.send_binary(pkt1)
                await c.send_binary(pkt2)

        asyncio.run_coroutine_threadsafe(_broadcast(), self.loop).result()

    def send_scale(self, new_size):
        self.size = new_size
        grid = generate_terrain(self.preset, self.origin, self.size)
        pkt1 = encode_selection_info(self.origin, self.size)
        pkt2 = encode_full_snapshot(self.origin, self.size, grid.palette, grid.indices)

        async def _broadcast():
            for c in list(self.clients):
                await c.send_binary(pkt1)
                await c.send_binary(pkt2)

        asyncio.run_coroutine_threadsafe(_broadcast(), self.loop).result()

    def send_section_burst(self, count=8):
        grid = generate_terrain(self.preset, self.origin, self.size)
        packets = []
        for i in range(count):
            sec_x = (self.origin[0] >> 4) + (i % 2)
            sec_y = (self.origin[1] >> 4) + ((i // 2) % 2)
            sec_z = (self.origin[2] >> 4) + (i // 4)
            start_pos = (sec_x * 16, sec_y * 16, sec_z * 16)
            sec_indices = [grid.indices[j % len(grid.indices)] for j in range(16 * 16 * 16)]
            pkt = encode_section_snapshot(
                (sec_x, sec_y, sec_z),
                start_pos,
                (16, 16, 16),
                grid.palette,
                sec_indices,
            )
            packets.append(pkt)

        async def _burst():
            for c in list(self.clients):
                for pkt in packets:
                    await c.send_binary(pkt)

        asyncio.run_coroutine_threadsafe(_burst(), self.loop).result()


class TestSyncDragAndScaleMemory(unittest.TestCase):
    def setUp(self):
        if not is_sync_available():
            self.skipTest("libmtk_py LiveSyncSession not available")

    def test_drag_and_scale_memory_stability(self):
        server = _TestControllableSyncServer(port=8797)
        server.start()

        session = get_sync_bridge_session()
        connected = session.start("ws://127.0.0.1:8797", auto_reconnect=False, unified_mesh=True)
        self.assertTrue(connected, "LiveSyncSession must successfully connect")

        time.sleep(0.3)
        _sync_timer_tick()
        time.sleep(0.1)
        _sync_timer_tick()

        init_rss = _get_rss_mb()

        # Phase 1: Drag selection 10 times
        move_rss = []
        for step in range(1, 11):
            server.send_move((step * 16, 64, 0))
            time.sleep(0.02)
            _sync_timer_tick()
            move_rss.append(_get_rss_mb())

        # Phase 2: Scale selection 4 times
        scale_rss = []
        for sz in [(16, 16, 16), (32, 16, 32), (32, 32, 32), (16, 16, 16)]:
            server.send_scale(sz)
            time.sleep(0.02)
            _sync_timer_tick()
            scale_rss.append(_get_rss_mb())

        # Phase 3: Section snapshot bursts
        burst_rss = []
        for _ in range(4):
            server.send_section_burst(count=8)
            time.sleep(0.02)
            _sync_timer_tick()
            burst_rss.append(_get_rss_mb())

        session.stop()

        # Growth verification
        # Memory growth between move #3 and move #10 should be near zero (O(1) steady state)
        import platform
        max_allowed_drag = 70.0 if platform.system() == "Darwin" else 35.0
        max_allowed_total = 150.0 if platform.system() == "Darwin" else 60.0
        drag_growth = move_rss[-1] - move_rss[2]
        self.assertLess(drag_growth, max_allowed_drag, f"Drag memory grew excessively by {drag_growth:.2f} MB")

        total_growth = burst_rss[-1] - init_rss
        self.assertLess(total_growth, max_allowed_total, f"Total sync memory grew excessively by {total_growth:.2f} MB")

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

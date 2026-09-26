"""
Integration test for the Live Sync operator, bridge, and unified mesh flow.
"""

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

for p in [str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

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
    HAS_BPY = False

from bridge.sync import get_sync_bridge_session, is_sync_available
from operators.sync.hierarchy import (
    DEFAULT_WORLD_OBJECT_NAME,
    is_yefira_world_object,
    get_or_create_world_mesh_object,
    update_world_mesh,
)
from operators.sync.op_sync_connect import _sync_timer_tick


class TestLiveSyncFlow(unittest.TestCase):
    def test_sync_available(self):
        self.assertTrue(is_sync_available(), "libmtk_py LiveSyncSession should be available in venv")

    def test_end_to_end_mock_server_and_bridge(self):
        if not is_sync_available():
            self.skipTest("libmtk_py not available")

        # Start mock server on dedicated port 8798
        server_script = PROJECT_DIR / "tools" / "mock_sync_server.py"
        server_proc = subprocess.Popen(
            [sys.executable, str(server_script), "--port", "8798", "--preset", "flat", "--size", "16", "16", "16", "--delta", "0.2"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        time.sleep(0.8)

        try:
            session = get_sync_bridge_session()
            connected = session.start(
                url="ws://127.0.0.1:8798",
                auto_reconnect=True,
                max_reconnect_attempts=3,
                unified_mesh=True,
            )
            self.assertTrue(connected)
            self.assertTrue(session.is_active)

            world_mesh_received = False
            delta_received = False

            # Poll events
            for _ in range(40):
                time.sleep(0.1)
                events = session.poll_events()
                for ev in events:
                    if ev.get("type") == "WORLD_MESH_READY":
                        mesh = ev.get("mesh")
                        self.assertIsNotNone(mesh)
                        self.assertGreater(mesh.vertex_count, 0)
                        world_mesh_received = True
                    elif ev.get("type") == "DELTA_APPLIED":
                        delta_received = True

                if world_mesh_received and delta_received:
                    break

            self.assertTrue(world_mesh_received, "Should receive unified WORLD_MESH_READY event")
            self.assertTrue(delta_received, "Should receive DELTA_APPLIED event")

            # Direct query test
            world_mesh = session.get_world_mesh()
            self.assertIsNotNone(world_mesh)
            self.assertGreater(world_mesh.vertex_count, 0)

            session.stop()
            self.assertFalse(session.is_active)

        finally:
            server_proc.terminate()
            if server_proc.stdout:
                server_proc.stdout.close()
            if server_proc.stderr:
                server_proc.stderr.close()
            server_proc.wait()


if __name__ == "__main__":
    unittest.main()

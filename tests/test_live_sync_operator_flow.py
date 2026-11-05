"""
Integration test for the Live Sync operator, bridge, and unified mesh flow.
"""

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
import bpy
import bmesh
import mathutils

PROJECT_DIR = Path(__file__).parent.parent.resolve()

from MoziToolKit.bridge.sync import get_sync_bridge_session, is_sync_available
from MoziToolKit.utils.world.sync_container import (
    DEFAULT_WORLD_OBJECT_NAME,
    is_yefira_world_object,
    get_or_create_world_mesh_object,
    update_world_mesh,
)
from MoziToolKit.operators.sync.op_sync_connect import _sync_timer_tick


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
            )
            self.assertTrue(connected)
            self.assertTrue(session.is_active)

            world_mesh_received = False
            delta_received = False

            # Poll events
            for _ in range(80):
                time.sleep(0.1)
                events = session.poll_events()
                for ev in events:
                    if ev.get("type") == "WORLD_MESH_READY":
                        mesh = ev.get("mesh")
                        self.assertIsNotNone(mesh)
                        self.assertGreater(mesh.vertex_count, 0)
                        # Provenance is palette-only: the per-face string layer is retired.
                        self.assertFalse(mesh.has_attribute("mtk_source_texture_key"))
                        self.assertTrue(mesh.has_attribute("mtk_source_texture_idx"))
                        self.assertTrue(mesh.has_attribute("mtk_source_textures"))
                        self.assertFalse(mesh.has_attribute("mtk_material_slot"))
                        self.assertTrue(mesh.has_attribute("mtk_uv_transform"))
                        self.assertTrue(mesh.has_attribute("mtk_biome_tint_data"))
                        self.assertFalse(mesh.has_attribute("mtk_face_dir"))
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
            try:
                session.reset()
            except Exception:
                pass
            server_proc.terminate()
            if server_proc.stdout:
                server_proc.stdout.close()
            if server_proc.stderr:
                server_proc.stderr.close()
            server_proc.wait()


if __name__ == "__main__":
    unittest.main()

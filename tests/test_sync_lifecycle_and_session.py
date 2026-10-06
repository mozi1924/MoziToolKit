"""
Tests for Live Sync session lifecycle, connection/disconnection state transitions,
timer safety, and cross-project load handlers.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
dev_lib = PROJECT_DIR / "dev" / "lib"

for p in [str(dev_lib), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import bpy
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes")
except ImportError:
    HAS_BPY = False

from bridge.sync import (
    SyncBridgeSession,
    get_sync_bridge_session,
    reset_sync_bridge_session,
    is_sync_available,
)
from operators.sync.op_sync_connect import (
    is_sync_timer_running,
    start_sync_timer,
    stop_sync_timer,
    _sync_timer_tick,
    MOZI_OT_sync_connect,
    MOZI_OT_sync_disconnect,
)
from operators.sync.properties import (
    _on_blend_file_pre_load,
    _on_blend_file_loaded,
)


class TestSyncSessionLifecycle(unittest.TestCase):
    def setUp(self):
        stop_sync_timer()
        reset_sync_bridge_session()

    def tearDown(self):
        stop_sync_timer()
        reset_sync_bridge_session()

    def test_session_initial_state(self):
        session = SyncBridgeSession()
        self.assertFalse(session.is_active)
        self.assertFalse(session.is_connected)
        self.assertEqual(session.connection_status, "DISCONNECTED")
        self.assertEqual(session.current_url, "")
        self.assertEqual(session.last_error, "")

    def test_session_start_stop_lifecycle(self):
        if not is_sync_available():
            self.skipTest("Native libmtk LiveSyncSession not available")

        session = SyncBridgeSession()
        # Connect to non-existent local port
        started = session.start(
            url="ws://127.0.0.1:59998",
            auto_reconnect=True,
            max_reconnect_attempts=3,
        )
        self.assertTrue(started)
        self.assertTrue(session.is_active)
        self.assertFalse(session.is_connected)
        self.assertIn("CONNECTING", session.connection_status)

        session.stop()
        self.assertFalse(session.is_active)
        self.assertFalse(session.is_connected)
        self.assertEqual(session.connection_status, "DISCONNECTED")

    def test_session_reset(self):
        if not is_sync_available():
            self.skipTest("Native libmtk LiveSyncSession not available")

        session = SyncBridgeSession()
        session.start(url="ws://127.0.0.1:59998", auto_reconnect=False)
        self.assertTrue(session.is_active)

        session.reset()
        self.assertFalse(session.is_active)
        self.assertFalse(session.is_connected)
        self.assertEqual(session.connection_status, "DISCONNECTED")
        self.assertEqual(session.current_url, "")
        self.assertIsNone(session._model_db)
        self.assertIsNone(session._atlas)

    def test_singleton_reset_helper(self):
        session = get_sync_bridge_session()
        reset_session = reset_sync_bridge_session()
        self.assertIs(session, reset_session)
        self.assertFalse(session.is_active)
        self.assertFalse(session.is_connected)

    def test_timer_idempotence(self):
        if not HAS_BPY:
            self.skipTest("Requires native Blender bpy")

        self.assertFalse(is_sync_timer_running())

        # Start timer twice - should not register duplicates
        start_sync_timer()
        self.assertTrue(is_sync_timer_running())
        start_sync_timer()
        self.assertTrue(is_sync_timer_running())

        # Stop timer twice - safe and clean
        stop_sync_timer()
        self.assertFalse(is_sync_timer_running())
        stop_sync_timer()
        self.assertFalse(is_sync_timer_running())

    def test_pre_load_handler_stops_timer_and_session(self):
        if not HAS_BPY:
            self.skipTest("Requires native Blender bpy")

        start_sync_timer()
        self.assertTrue(is_sync_timer_running())

        session = get_sync_bridge_session()
        if is_sync_available():
            session.start("ws://127.0.0.1:59998", auto_reconnect=False)
            self.assertTrue(session.is_active)

        # Trigger pre-load hook
        _on_blend_file_pre_load(None)

        self.assertFalse(is_sync_timer_running(), "Timer must be canceled on blend file pre-load")
        self.assertFalse(session.is_active, "Session must be stopped on blend file pre-load")

    def test_load_post_handler_resets_properties(self):
        if not HAS_BPY:
            self.skipTest("Requires native Blender bpy")

        scene = bpy.context.scene
        if hasattr(scene, "mozi_sync"):
            scene.mozi_sync.is_connected = True
            scene.mozi_sync.connection_status = "CONNECTED"
            scene.mozi_sync.is_streaming = True

            # Trigger post-load hook
            _on_blend_file_loaded(None)

            self.assertFalse(scene.mozi_sync.is_connected)
            self.assertEqual(scene.mozi_sync.connection_status, "DISCONNECTED")
            self.assertFalse(scene.mozi_sync.is_streaming)


if __name__ == "__main__":
    unittest.main()

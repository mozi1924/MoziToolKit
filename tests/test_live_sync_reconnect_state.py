"""
Regression tests for Live Sync connection-state reporting and refresh recovery.

Covers:
1. A terminal DISCONNECTED event is still applied after the native worker stops,
   so the panel cannot stay stuck on "CONNECTED" (which previously made the
   Refresh button report "Live Sync is not connected" while the UI looked online).
2. Intermediate transport status messages / warnings never downgrade the
   connection state by themselves.
3. SyncBridgeSession.poll_events still drains the event queue when inactive.
4. Refresh guards stale UI state and reports a precise status.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import bpy

from MoziToolKit.bridge.sync import SyncBridgeSession
from MoziToolKit.operators.sync import op_sync_connect


class DummySyncSession:
    def __init__(self, *, active: bool, connected: bool, status: str, events=None):
        self.is_active = active
        self.is_connected = connected
        self.connection_status = status
        self.last_error = ""
        self._events = list(events or [])
        self.resync_call_count = 0

    def poll_events(self):
        return list(self._events)

    def request_resync(self):
        self.resync_call_count += 1
        return True


def _make_session(*, active: bool, connected: bool, status: str, events=None):
    return DummySyncSession(active=active, connected=connected, status=status, events=events)


def _run_tick(mock_session):
    container = bpy.data.objects.new("test_sync_container", None)
    bpy.context.collection.objects.link(container)
    props = container.mozi_sync
    stop_calls = []
    with patch.object(op_sync_connect, "get_sync_bridge_session", return_value=mock_session), \
         patch.object(op_sync_connect, "get_active_sync_container", return_value=container), \
         patch.object(op_sync_connect, "get_or_create_world_container", return_value=container), \
         patch.object(op_sync_connect, "set_active_sync_container"), \
         patch.object(op_sync_connect, "stop_sync_timer", side_effect=lambda: stop_calls.append(True)), \
         patch.object(op_sync_connect, "_close_progress_reporter"):
        result = op_sync_connect._sync_timer_tick()
    return props, stop_calls, result


class TestLiveSyncConnectionState(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from MoziToolKit.operators.sync.properties import register as register_sync_props
        try:
            register_sync_props()
        except Exception:
            pass

    def tearDown(self):
        for obj in list(bpy.data.objects):
            if obj.name.startswith("test_"):
                bpy.data.objects.remove(obj, do_unlink=True)
    def test_terminal_disconnect_is_applied_when_worker_already_stopped(self):
        session = _make_session(
            active=False,
            connected=False,
            status="DISCONNECTED",
            events=[
                {
                    "type": "STATUS_CHANGE",
                    "status": "DISCONNECTED (Connection failed: refused)",
                }
            ],
        )
        props, stop_calls, result = _run_tick(session)

        self.assertIs(result, None)
        self.assertFalse(props.is_connected)
        self.assertEqual(props.connection_status, "DISCONNECTED")
        self.assertFalse(props.is_streaming)
        self.assertEqual(len(stop_calls), 1)

    def test_intermediate_status_does_not_downgrade_live_connection(self):
        # Native session is still connected (e.g. a recoverable frame/decode warning).
        session = _make_session(
            active=True,
            connected=True,
            status="CONNECTED",
            events=[{"type": "STATUS_CHANGE", "status": "Send error: transient"}],
        )
        props, stop_calls, result = _run_tick(session)

        self.assertEqual(result, 0.016)
        self.assertTrue(props.is_connected)
        self.assertEqual(props.connection_status, "CONNECTED")
        self.assertEqual(len(stop_calls), 0)

    def test_warning_keeps_connection_alive(self):
        session = _make_session(
            active=True,
            connected=True,
            status="CONNECTED",
            events=[{"type": "WARNING", "message": "Packet decode error: x"}],
        )
        props, stop_calls, result = _run_tick(session)

        self.assertEqual(result, 0.016)
        self.assertTrue(props.is_connected)
        self.assertEqual(len(stop_calls), 0)

    def test_bridge_poll_events_drains_after_inactive(self):
        session = SyncBridgeSession()
        poll_called = []
        def fake_poll():
            poll_called.append(True)
            return [{"type": "STATUS_CHANGE", "status": "DISCONNECTED (Connection failed: x)"}]

        native = SimpleNamespace(poll_events=fake_poll)
        session._session = native
        session._is_active = False

        events = session.poll_events()

        self.assertEqual(len(events), 1)
        self.assertFalse(session._is_connected)
        self.assertEqual(len(poll_called), 1)

    def test_refresh_reports_not_connected_after_stale_ui(self):
        session = _make_session(active=False, connected=False, status="DISCONNECTED")

        class DummyOp:
            target_container = ""
            def report(self, type_set, msg):
                pass

            def execute(self, ctx):
                return op_sync_connect.MOZI_OT_sync_refresh.execute(self, ctx)

        op = DummyOp()
        with patch.object(op_sync_connect, "get_sync_bridge_session", return_value=session), \
             patch.object(op_sync_connect, "get_active_sync_container", return_value=None):
            result = op.execute(bpy.context)

        self.assertIn("CANCELLED", result)
        self.assertEqual(session.resync_call_count, 0)

    def test_refresh_works_while_connected(self):
        session = _make_session(active=True, connected=True, status="CONNECTED")

        class DummyOp:
            target_container = ""
            def report(self, type_set, msg):
                pass

            def execute(self, ctx):
                return op_sync_connect.MOZI_OT_sync_refresh.execute(self, ctx)

        op = DummyOp()
        container = bpy.data.objects.new("test_refresh_container", None)
        bpy.context.collection.objects.link(container)
        try:
            with patch.object(op_sync_connect, "get_sync_bridge_session", return_value=session), \
                 patch.object(op_sync_connect, "get_active_sync_container", return_value=container), \
                 patch.object(op_sync_connect, "_get_progress_reporter") as mock_reporter:
                mock_reporter.return_value = SimpleNamespace(update=lambda *a, **k: None, close=lambda: None)
                result = op.execute(bpy.context)

            self.assertIn("FINISHED", result)
            self.assertEqual(session.resync_call_count, 1)
        finally:
            bpy.data.objects.remove(container)


if __name__ == "__main__":
    unittest.main()

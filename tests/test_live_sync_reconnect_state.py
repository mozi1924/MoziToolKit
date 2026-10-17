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
from unittest.mock import MagicMock, patch

from MoziToolKit.bridge.sync import SyncBridgeSession
from MoziToolKit.operators.sync import op_sync_connect


def _make_session(*, active: bool, connected: bool, status: str, events=None):
    mock_session = MagicMock(spec=SyncBridgeSession)
    mock_session.is_active = active
    mock_session.is_connected = connected
    mock_session.connection_status = status
    mock_session.last_error = ""
    mock_session.poll_events.return_value = list(events or [])
    return mock_session


def _run_tick(mock_session):
    props = MagicMock()
    container = MagicMock()
    container.mozi_sync = props
    with patch.object(op_sync_connect, "get_sync_bridge_session", return_value=mock_session), \
         patch.object(op_sync_connect, "get_active_sync_container", return_value=container), \
         patch.object(op_sync_connect, "get_or_create_world_container", return_value=container), \
         patch.object(op_sync_connect, "set_active_sync_container"), \
         patch.object(op_sync_connect, "stop_sync_timer") as mock_stop, \
         patch.object(op_sync_connect, "_close_progress_reporter"):
        result = op_sync_connect._sync_timer_tick()
    return props, mock_stop, result


class TestLiveSyncPersistedIdentity(unittest.TestCase):
    def test_native_session_exports_persisted_state_json(self):
        try:
            from bridge.engine import get_libmtk
        except Exception:
            self.skipTest("libmtk_py unavailable")

        mtk = get_libmtk()
        if mtk is None or not hasattr(mtk, "LiveSyncSession"):
            self.skipTest("LiveSyncSession unavailable")

        import json

        session = mtk.LiveSyncSession()
        raw = session.export_persisted_state_json(False)
        state = json.loads(raw)
        self.assertEqual(state["server_uuid"], "0" * 32)
        self.assertEqual(state["state_hash"], 0)
        self.assertEqual(state["size"], [0, 0, 0])
        self.assertFalse(state["user_modified"])

    def test_bridge_exposes_persisted_state_json(self):
        session = SyncBridgeSession()
        self.assertIsNone(session.export_persisted_state_json())


class TestLiveSyncConnectionState(unittest.TestCase):
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
        props, mock_stop, result = _run_tick(session)

        self.assertIs(result, None)
        self.assertFalse(props.is_connected)
        self.assertEqual(props.connection_status, "DISCONNECTED")
        self.assertFalse(props.is_streaming)
        mock_stop.assert_called_once()

    def test_intermediate_status_does_not_downgrade_live_connection(self):
        # Native session is still connected (e.g. a recoverable frame/decode warning).
        session = _make_session(
            active=True,
            connected=True,
            status="CONNECTED",
            events=[{"type": "STATUS_CHANGE", "status": "Send error: transient"}],
        )
        props, mock_stop, result = _run_tick(session)

        self.assertEqual(result, 0.016)
        self.assertTrue(props.is_connected)
        self.assertEqual(props.connection_status, "CONNECTED")
        mock_stop.assert_not_called()

    def test_warning_keeps_connection_alive(self):
        session = _make_session(
            active=True,
            connected=True,
            status="CONNECTED",
            events=[{"type": "WARNING", "message": "Packet decode error: x"}],
        )
        props, mock_stop, result = _run_tick(session)

        self.assertEqual(result, 0.016)
        self.assertTrue(props.is_connected)
        mock_stop.assert_not_called()

    def test_bridge_poll_events_drains_after_inactive(self):
        session = SyncBridgeSession()
        native = MagicMock()
        native.poll_events.return_value = [
            {"type": "STATUS_CHANGE", "status": "DISCONNECTED (Connection failed: x)"}
        ]
        session._session = native
        session._is_active = False

        events = session.poll_events()

        self.assertEqual(len(events), 1)
        self.assertFalse(session._is_connected)
        native.poll_events.assert_called_once()

    def test_refresh_reports_not_connected_after_stale_ui(self):
        session = _make_session(active=False, connected=False, status="DISCONNECTED")
        props = MagicMock()
        props.is_connected = True  # stale UI state from before the silent drop

        class DummyOp:
            target_container = ""
            report = MagicMock()

            def execute(self, ctx):
                return op_sync_connect.MOZI_OT_sync_refresh.execute(self, ctx)

        ctx = MagicMock()
        ctx.scene = None
        ctx.active_object = None

        op = DummyOp()
        with patch.object(op_sync_connect, "get_sync_bridge_session", return_value=session), \
             patch.object(op_sync_connect, "get_active_sync_container", return_value=None):
            result = op.execute(ctx)

        self.assertIn("CANCELLED", result)
        session.request_resync.assert_not_called()

    def test_refresh_works_while_connected(self):
        session = _make_session(active=True, connected=True, status="CONNECTED")
        session.request_resync.return_value = True

        class DummyOp:
            target_container = ""
            report = MagicMock()

            def execute(self, ctx):
                return op_sync_connect.MOZI_OT_sync_refresh.execute(self, ctx)

        op = DummyOp()
        container = MagicMock()
        with patch.object(op_sync_connect, "get_sync_bridge_session", return_value=session), \
             patch.object(op_sync_connect, "get_active_sync_container", return_value=container), \
             patch.object(op_sync_connect, "_get_progress_reporter") as mock_reporter:
            mock_reporter.return_value = MagicMock()
            ctx = MagicMock()
            ctx.scene = None
            ctx.active_object = None
            result = op.execute(ctx)

        self.assertIn("FINISHED", result)
        session.request_resync.assert_called_once()


if __name__ == "__main__":
    unittest.main()

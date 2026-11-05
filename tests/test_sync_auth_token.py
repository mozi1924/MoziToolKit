"""Regression tests for Live Sync auth-token forwarding (RFC v3.1 §4.1).

The native session only sends the token that `SyncBridgeSession.start` hands to
`LiveSyncSession.start`; a whitespace-only difference used to be enough for the
Yefira server to answer `REJECTED("Authentication failed")`.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from MoziToolKit.bridge.sync import SyncBridgeSession


def _start_with_token(token):
    session = SyncBridgeSession()
    calls = []

    class DummyNative:
        def start(self, *args, **kwargs):
            calls.append(kwargs)
            return True

    dummy_native = DummyNative()
    from MoziToolKit.bridge.engine import get_libmtk
    real_mtk = get_libmtk()
    mock_mtk = SimpleNamespace(**{k: getattr(real_mtk, k) for k in dir(real_mtk)})
    mock_mtk.LiveSyncSession = lambda *args, **kwargs: dummy_native

    with patch("MoziToolKit.bridge.sync.get_libmtk", return_value=mock_mtk), \
         patch("MoziToolKit.bridge.sync.get_cache_fingerprint", return_value="fp"), \
         patch("MoziToolKit.bridge.sync.get_cache_timestamp", return_value=0.0), \
         patch("MoziToolKit.bridge.sync.get_configured_ctm_solver", return_value=None), \
         patch("MoziToolKit.utils.system.get_prefs", return_value=None):
        started = session.start(url="ws://127.0.0.1:8765", auth_token=token, num_threads=1)

    return started, calls[0] if calls else {}


class TestSyncAuthToken(unittest.TestCase):
    def test_token_is_stripped_before_reaching_native(self):
        started, kwargs = _start_with_token("  secret-token \n")
        self.assertTrue(started)
        self.assertEqual(kwargs.get("auth_token"), "secret-token")

    def test_blank_token_is_not_forwarded(self):
        started, kwargs = _start_with_token("   ")
        self.assertTrue(started)
        self.assertNotIn("auth_token", kwargs)


if __name__ == "__main__":
    unittest.main()

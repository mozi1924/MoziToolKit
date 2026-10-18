"""Regression tests for Live Sync auth-token forwarding (RFC v3.1 §4.1).

The native session only sends the token that `SyncBridgeSession.start` hands to
`LiveSyncSession.start`; a whitespace-only difference used to be enough for the
Yefira server to answer `REJECTED("Authentication failed")`.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from MoziToolKit.bridge.sync import SyncBridgeSession


def _start_with_token(token):
    session = SyncBridgeSession()
    native = MagicMock()
    mock_mtk = MagicMock()
    mock_mtk.LiveSyncSession.return_value = native

    with patch("MoziToolKit.bridge.sync.get_libmtk", return_value=mock_mtk), \
         patch("MoziToolKit.bridge.sync.get_cache_fingerprint", return_value="fp"), \
         patch("MoziToolKit.bridge.sync.get_cache_timestamp", return_value=0.0), \
         patch("MoziToolKit.bridge.sync.get_configured_ctm_solver", return_value=None), \
         patch("MoziToolKit.utils.system.get_prefs", return_value=None):
        started = session.start(url="ws://127.0.0.1:8765", auth_token=token, num_threads=1)

    return started, native


class TestSyncAuthToken(unittest.TestCase):
    def test_token_is_stripped_before_reaching_native(self):
        started, native = _start_with_token("  secret-token \n")
        self.assertTrue(started)
        _, kwargs = native.start.call_args
        self.assertEqual(kwargs.get("auth_token"), "secret-token")

    def test_blank_token_is_not_forwarded(self):
        started, native = _start_with_token("   ")
        self.assertTrue(started)
        _, kwargs = native.start.call_args
        self.assertNotIn("auth_token", kwargs)


if __name__ == "__main__":
    unittest.main()

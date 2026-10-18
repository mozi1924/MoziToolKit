"""Tests for the host-agnostic Rust `.mtkcache` resolver."""

import tempfile
import unittest
from pathlib import Path

from bridge.engine import get_libmtk


class TestCacheResolver(unittest.TestCase):
    def test_resolves_matching_fingerprint_and_newest_fallback(self):
        mtk = get_libmtk()
        if mtk is None or not hasattr(mtk, "resolve_active_cache_package"):
            self.skipTest("Native cache resolver unavailable")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "fp1.mtkcache"
            second = root / "fp2.mtkcache"
            mtk.create_test_cache_package(str(first), "fp1", 0)
            mtk.create_test_cache_package(str(second), "fp2", 0)

            self.assertEqual(
                mtk.resolve_active_cache_package(str(root), "fp1"), str(first)
            )
            self.assertEqual(
                mtk.resolve_active_cache_package(str(root), "fp2"), str(second)
            )
            self.assertIsNone(mtk.resolve_active_cache_package(str(root), "missing"))
            self.assertIn(
                mtk.resolve_active_cache_package(str(root), None),
                {str(first), str(second)},
            )

    def test_missing_directory_returns_none(self):
        mtk = get_libmtk()
        if mtk is None or not hasattr(mtk, "resolve_active_cache_package"):
            self.skipTest("Native cache resolver unavailable")
        self.assertIsNone(
            mtk.resolve_active_cache_package("/path/that/does/not/exist", "fp")
        )


if __name__ == "__main__":
    unittest.main()

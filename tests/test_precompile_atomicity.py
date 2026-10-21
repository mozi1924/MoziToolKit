"""Regression tests for atomic asset-cache publication.

The Rust writer stages packages in a sibling temp file and renames them into
place, so a rebuild never truncates a package that is still mapped. On Windows
the destination must nevertheless be closed first (an open mapped view blocks
the rename), so the Python bridge must drop its cached reader before compiling.
"""

import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from MoziToolKit.bridge.assets import precompile as precompile_mod


class TestPrecompileReleasesMappedCache(unittest.TestCase):
    def test_invalidate_precedes_precompile(self):
        events = []

        def fake_precompile(*_args, **_kwargs):
            events.append("precompile")
            return SimpleNamespace(
                success=True,
                pack_count=1,
                atlas_chunks=1,
                baked_models=2,
                fingerprint="fp",
                package_path="unused.mtkcache",
                cache_dir="unused",
            )

        fake_mtk = SimpleNamespace(precompile_all_assets=fake_precompile)
        stack = SimpleNamespace(get_pack_count=lambda: 1)

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            precompile_mod, "get_libmtk", return_value=fake_mtk
        ), mock.patch.object(
            precompile_mod,
            "invalidate_asset_cache_memory",
            side_effect=lambda: events.append("invalidate"),
        ):
            result = precompile_mod.precompile_stack(
                stack=stack,
                cache_dir=tmp,
                reload_images=False,
            )

        self.assertTrue(result["success"])
        self.assertIn("invalidate", events)
        self.assertIn("precompile", events)
        self.assertLess(
            events.index("invalidate"),
            events.index("precompile"),
            "the mapped cache must be released before the writer publishes",
        )


if __name__ == "__main__":
    unittest.main()

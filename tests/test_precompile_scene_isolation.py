# -*- coding: utf-8 -*-
"""
Tests that cache precompilation is purely an offline data-baking process
and NEVER mutates active Blender scene images or scrambles mesh materials.
"""

import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from MoziToolKit.bridge.assets import precompile_stack
from MoziToolKit.operators.op_precompile import MOZI_OT_precompile_cache


class TestPrecompileSceneIsolation(unittest.TestCase):
    def test_precompile_does_not_mutate_scene_images(self):
        """Verifies that precompiling the resource pack stack leaves existing loaded scene images untouched."""
        is_real_bpy = (
            HAS_BPY
            and hasattr(bpy, "app")
            and isinstance(getattr(bpy.app, "version", None), tuple)
            and bpy.app.version[0] >= 4
        )

        img = None
        if is_real_bpy:
            img_name = "test_blocks_chunk_001.png"
            img = bpy.data.images.new(img_name, width=4, height=4, alpha=True)
            original_pixels = [0.2, 0.4, 0.6, 1.0] * 16
            img.pixels.foreach_set(original_pixels)
            img.update()
            self.addCleanup(lambda: bpy.data.images.remove(img) if img.name in bpy.data.images else None)

        # Mock the underlying native precompiler
        mock_res = MagicMock()
        mock_res.success = True
        mock_res.pack_count = 1
        mock_res.atlas_chunks = 1
        mock_res.baked_models = 10

        with patch("MoziToolKit.bridge.assets.precompile.get_libmtk") as mock_get_mtk, \
             patch("MoziToolKit.bridge.assets.precompile.reload_atlas_images") as mock_reload:
            mock_mtk = MagicMock()
            mock_mtk.precompile_resource_stack.return_value = mock_res
            mock_get_mtk.return_value = mock_mtk

            mock_stack = MagicMock()
            mock_stack.get_pack_count.return_value = 1
            mock_stack.compute_stack_fingerprint.return_value = "new_fingerprint_abc"

            res = precompile_stack(stack=mock_stack, cache_dir="/tmp/dummy_cache", reload_images=False)
            self.assertTrue(res.get("success"))

            # reload_atlas_images must NOT have been called
            mock_reload.assert_not_called()

        if is_real_bpy and img is not None:
            current_pixels = list(img.pixels)
            for i in range(len(original_pixels)):
                self.assertAlmostEqual(current_pixels[i], original_pixels[i], places=4)

    def test_operator_on_success_does_not_reload_scene_images(self):
        """Verifies MOZI_OT_precompile_cache does not import or reload scene images on precompile completion."""
        import MoziToolKit.operators.op_precompile as op_mod
        self.assertFalse(hasattr(op_mod, "reload_atlas_images"), "op_precompile should not import or call reload_atlas_images")


if __name__ == "__main__":
    unittest.main()

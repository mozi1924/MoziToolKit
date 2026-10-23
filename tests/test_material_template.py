"""
Unit tests for the template material cloning engine (utils/materials/builder/template.py).
"""

from __future__ import annotations

import array
import unittest
from unittest.mock import MagicMock

from MoziToolKit.utils.materials.builder.template import (
    get_template_key,
    find_archetype_material,
    register_archetype_material,
    clone_atlas_chunk_material,
)


class TestMaterialTemplate(unittest.TestCase):
    """Test suite for template material keying, registration, and cloning."""

    def test_get_template_key_deterministic(self):
        k1 = get_template_key("blocks", False, True, False, True, True, True, "CYCLES", False, "UVMap")
        k2 = get_template_key("blocks", False, True, False, True, True, True, "CYCLES", False, "UVMap")
        self.assertEqual(k1, k2)

        # Varying channels changes key
        k_anim = get_template_key("blocks", True, True, False, True, True, True, "CYCLES", False, "UVMap")
        self.assertNotEqual(k1, k_anim)

        k_no_pbr = get_template_key("blocks", False, True, False, False, False, False, "CYCLES", False, "UVMap")
        self.assertNotEqual(k1, k_no_pbr)

        k_overlay = get_template_key("blocks", False, True, True, True, True, True, "CYCLES", False, "UVMap")
        self.assertNotEqual(k1, k_overlay)

    def test_register_and_find_archetype_mock(self):
        mock_mat = {}
        register_archetype_material(mock_mat, "blocks_pbr_v1")
        self.assertEqual(mock_mat.get("mtk_template_key"), "blocks_pbr_v1")

    def test_clone_atlas_chunk_material_blender(self):
        try:
            import bpy
            if isinstance(bpy, MagicMock) or isinstance(getattr(bpy, "data", None), MagicMock):
                self.skipTest("Requires real Blender host environment")
        except ImportError:
            self.skipTest("bpy not available")

        from MoziToolKit.utils.materials.builder.atlas_builder import build_atlas_chunk_material

        albedo1 = (2, 2, array.array("f", [1.0, 0.0, 0.0, 1.0] * 4))
        normal1 = (2, 2, array.array("f", [0.5, 0.5, 1.0, 1.0] * 4))
        orm1 = (2, 2, array.array("f", [1.0, 1.0, 0.0, 1.0] * 4))

        mat1 = build_atlas_chunk_material(
            chunk_id=0,
            albedo_path=albedo1,
            normal_path=normal1,
            orm_path=orm1,
            category="blocks",
            category_chunk_index=1,
            force_rebuild=True,
        )
        self.assertIsNotNone(mat1)
        self.assertIn("mtk_template_key", mat1)

        albedo2 = (2, 2, array.array("f", [0.0, 1.0, 0.0, 1.0] * 4))
        mat2 = build_atlas_chunk_material(
            chunk_id=1,
            albedo_path=albedo2,
            normal_path=normal1,
            orm_path=orm1,
            category="blocks",
            category_chunk_index=2,
            force_rebuild=True,
        )
        self.assertIsNotNone(mat2)
        self.assertEqual(mat2.name, "MTK:Atlas:blocks:002")
        self.assertEqual(len(mat1.node_tree.nodes), len(mat2.node_tree.nodes))

        # Check that image pointers are distinct
        img1 = mat1.node_tree.nodes["Atlas Albedo Texture"].image
        img2 = mat2.node_tree.nodes["Atlas Albedo Texture"].image
        self.assertIsNotNone(img1)
        self.assertIsNotNone(img2)
        self.assertNotEqual(img1.name, img2.name)

        # Clean up
        bpy.data.materials.remove(mat1)
        bpy.data.materials.remove(mat2)

    def test_clone_atlas_chunk_material_with_overlay(self):
        try:
            import bpy
            if isinstance(bpy, MagicMock) or isinstance(getattr(bpy, "data", None), MagicMock):
                self.skipTest("Requires real Blender host environment")
        except ImportError:
            self.skipTest("bpy not available")

        from MoziToolKit.utils.materials.builder.atlas_builder import build_atlas_chunk_material

        albedo1 = (2, 2, array.array("f", [1.0, 0.0, 0.0, 1.0] * 4))
        overlay1 = (2, 2, array.array("f", [0.0, 1.0, 0.0, 0.5] * 4))

        mat1 = build_atlas_chunk_material(
            chunk_id=0,
            albedo_path=albedo1,
            overlay_path=overlay1,
            category="blocks",
            category_chunk_index=1,
            force_rebuild=True,
        )
        self.assertIsNotNone(mat1)
        self.assertTrue(mat1.get("mtk_has_overlay"))
        self.assertIn("Atlas Overlay Texture", mat1.node_tree.nodes)

        tint_node = mat1.node_tree.nodes.get("MC Biome Tint")
        self.assertIsNotNone(tint_node)
        self.assertTrue(tint_node.inputs["Overlay Color"].is_linked)
        self.assertTrue(tint_node.inputs["Overlay Alpha"].is_linked)

        # Build second chunk material with overlay -> should clone from archetype
        albedo2 = (2, 2, array.array("f", [0.0, 0.0, 1.0, 1.0] * 4))
        overlay2 = (2, 2, array.array("f", [1.0, 1.0, 0.0, 0.8] * 4))
        mat2 = build_atlas_chunk_material(
            chunk_id=1,
            albedo_path=albedo2,
            overlay_path=overlay2,
            category="blocks",
            category_chunk_index=2,
            force_rebuild=True,
        )
        self.assertIsNotNone(mat2)
        self.assertTrue(mat2.get("mtk_has_overlay"))
        self.assertIn("Atlas Overlay Texture", mat2.node_tree.nodes)
        self.assertEqual(len(mat1.node_tree.nodes), len(mat2.node_tree.nodes))

        # Check that image pointers are distinct
        img1 = mat1.node_tree.nodes["Atlas Overlay Texture"].image
        img2 = mat2.node_tree.nodes["Atlas Overlay Texture"].image
        self.assertIsNotNone(img1)
        self.assertIsNotNone(img2)
        self.assertNotEqual(img1.name, img2.name)

        # Clean up
        bpy.data.materials.remove(mat1)
        bpy.data.materials.remove(mat2)

    def test_atlas_chunk_material_overlay_virtual_path(self):
        try:
            import bpy
            from pathlib import Path
            if isinstance(bpy, MagicMock) or isinstance(getattr(bpy, "data", None), MagicMock):
                self.skipTest("Requires real Blender host environment")
        except ImportError:
            self.skipTest("bpy not available")

        from MoziToolKit.utils.materials.builder.atlas_builder import build_atlas_chunk_material

        # Simulate .mtkcache behavior: create an image in bpy.data.images named
        # blocks_chunk_003_overlay.png, but pass a Path object pointing to a
        # non-existent file on disk.
        ovr_img_name = "blocks_chunk_003_overlay.png"
        ovr_img = bpy.data.images.get(ovr_img_name)
        if ovr_img is None:
            ovr_img = bpy.data.images.new(ovr_img_name, width=2, height=2, alpha=True)

        albedo = (2, 2, array.array("f", [1.0, 0.0, 0.0, 1.0] * 4))
        virtual_overlay_path = Path("/nonexistent/cache/dir/blocks_chunk_003_overlay.png")
        self.assertFalse(virtual_overlay_path.exists())

        mat = build_atlas_chunk_material(
            chunk_id=2,
            albedo_path=albedo,
            overlay_path=virtual_overlay_path,
            category="blocks",
            category_chunk_index=3,
            force_rebuild=True,
            chunk_stem="blocks_chunk_003",
        )
        self.assertIsNotNone(mat)
        self.assertTrue(mat.get("mtk_has_overlay"))
        self.assertIn("Atlas Overlay Texture", mat.node_tree.nodes)
        self.assertEqual(mat.node_tree.nodes["Atlas Overlay Texture"].image, ovr_img)

        tint_node = mat.node_tree.nodes.get("MC Biome Tint")
        self.assertIsNotNone(tint_node)
        self.assertTrue(tint_node.inputs["Overlay Color"].is_linked)
        self.assertTrue(tint_node.inputs["Overlay Alpha"].is_linked)

        # Clean up
        bpy.data.materials.remove(mat)
        bpy.data.images.remove(ovr_img)


if __name__ == "__main__":
    unittest.main()

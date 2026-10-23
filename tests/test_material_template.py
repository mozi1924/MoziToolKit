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


if __name__ == "__main__":
    unittest.main()

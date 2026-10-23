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

        # Varying biome tint changes key
        k_tint = get_template_key("blocks", False, True, False, True, True, True, "CYCLES", False, "UVMap", enable_biome_tint=True)
        k_no_tint = get_template_key("blocks", False, True, False, True, True, True, "CYCLES", False, "UVMap", enable_biome_tint=False)
        self.assertNotEqual(k_tint, k_no_tint)

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

    def test_non_blocks_category_skips_biome_tint(self):
        try:
            import bpy
            if isinstance(bpy, MagicMock) or isinstance(getattr(bpy, "data", None), MagicMock):
                self.skipTest("Requires real Blender host environment")
        except ImportError:
            self.skipTest("bpy not available")

        from MoziToolKit.utils.materials.builder.atlas_builder import build_atlas_chunk_material

        albedo = (2, 2, array.array("f", [0.8, 0.2, 0.2, 1.0] * 4))

        # 1. Non-blocks category (items) -> automatically skips biome tint
        mat_items = build_atlas_chunk_material(
            chunk_id=10,
            albedo_path=albedo,
            category="items",
            category_chunk_index=1,
            force_rebuild=True,
        )
        self.assertIsNotNone(mat_items)
        self.assertFalse(mat_items.get("mtk_has_biome_tint"))

        item_nodes = [n.name for n in mat_items.node_tree.nodes]
        self.assertNotIn("MC Biome Tint", item_nodes)
        self.assertNotIn("Attr Biome Tint Data", item_nodes)
        self.assertNotIn("Attr Biome Tint Color", item_nodes)
        self.assertNotIn("Frame_Biome", item_nodes)

        # BSDF Base Color should be wired from Atlas Albedo Texture (either directly or via Vertex AO)
        bsdf = mat_items.node_tree.nodes["Principled BSDF"]
        self.assertTrue(bsdf.inputs["Base Color"].is_linked)
        from_node = bsdf.inputs["Base Color"].links[0].from_node
        if from_node.name == "Base Color × Vertex AO":
            # Input A of the multiplier mix node should come directly from Atlas Albedo Texture
            a_input = from_node.inputs.get("A") or from_node.inputs.get("Color1") or from_node.inputs[6]
            self.assertEqual(a_input.links[0].from_node.name, "Atlas Albedo Texture")
        else:
            self.assertEqual(from_node.name, "Atlas Albedo Texture")

        # BSDF Alpha should be wired directly from Atlas Albedo Texture
        self.assertTrue(bsdf.inputs["Alpha"].is_linked)
        alpha_source = bsdf.inputs["Alpha"].links[0].from_node
        self.assertEqual(alpha_source.name, "Atlas Albedo Texture")

        # 2. Blocks category with explicit enable_biome_tint=False -> skips biome tint
        mat_block_no_tint = build_atlas_chunk_material(
            chunk_id=11,
            albedo_path=albedo,
            category="blocks",
            category_chunk_index=99,
            enable_biome_tint=False,
            force_rebuild=True,
        )
        self.assertIsNotNone(mat_block_no_tint)
        self.assertFalse(mat_block_no_tint.get("mtk_has_biome_tint"))
        block_no_tint_nodes = [n.name for n in mat_block_no_tint.node_tree.nodes]
        self.assertNotIn("MC Biome Tint", block_no_tint_nodes)
        self.assertNotIn("Attr Biome Tint Data", block_no_tint_nodes)
        self.assertNotIn("Attr Biome Tint Color", block_no_tint_nodes)

        # 3. Blocks category default -> includes biome tint
        mat_block_tint = build_atlas_chunk_material(
            chunk_id=12,
            albedo_path=albedo,
            category="blocks",
            category_chunk_index=98,
            force_rebuild=True,
        )
        self.assertIsNotNone(mat_block_tint)
        self.assertTrue(mat_block_tint.get("mtk_has_biome_tint"))
        block_tint_nodes = [n.name for n in mat_block_tint.node_tree.nodes]
        self.assertIn("MC Biome Tint", block_tint_nodes)
        self.assertIn("Attr Biome Tint Data", block_tint_nodes)
        self.assertIn("Attr Biome Tint Color", block_tint_nodes)

        # Clean up
        for m in (mat_items, mat_block_no_tint, mat_block_tint):
            if m.name in bpy.data.materials:
                bpy.data.materials.remove(m)


if __name__ == "__main__":
    unittest.main()

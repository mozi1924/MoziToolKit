"""
Unit tests for the NodeLayoutEngine subsystem (utils/materials/builder/layout.py).
"""

from __future__ import annotations

import unittest
import bpy

from MoziToolKit.utils.materials.builder.image_utils import ensure_material_node_tree
from MoziToolKit.utils.materials.builder.layout import (
    NodeLayoutEngine,
    auto_layout_material,
    get_node_size,
)


class TestMaterialLayout(unittest.TestCase):
    """Test suite for NodeLayoutEngine positioning and spacing logic."""

    def test_get_node_size_fallbacks(self):
        mat = bpy.data.materials.new("LayoutTestNodeSize")
        try:
            ensure_material_node_tree(mat)
            tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
            w, h = get_node_size(tex_node)
            self.assertEqual(w, 240.0)
            self.assertEqual(h, 260.0)

            bsdf_node = mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
            w, h = get_node_size(bsdf_node)
            self.assertEqual(w, 240.0)
            self.assertEqual(h, 560.0)
        finally:
            bpy.data.materials.remove(mat)

    def test_stack_vertical_spacing(self):
        mat = bpy.data.materials.new("LayoutTestStack")
        try:
            ensure_material_node_tree(mat)
            n1 = mat.node_tree.nodes.new("ShaderNodeTexImage")
            n2 = mat.node_tree.nodes.new("ShaderNodeTexImage")

            final_y = NodeLayoutEngine.stack_vertical([n1, n2], x=-1000.0, start_y=500.0, gap_y=40.0)

            # n1 should be placed at start_y
            self.assertEqual(n1.location.x, -1000.0)
            self.assertEqual(n1.location.y, 500.0)
            # n2 should be placed at start_y - (260 + 40) = 200.0
            self.assertEqual(n2.location.x, -1000.0)
            self.assertEqual(n2.location.y, 200.0)
            # final_y after n2: 200 - 300 = -100.0
            self.assertEqual(final_y, -100.0)
        finally:
            bpy.data.materials.remove(mat)

    def test_auto_layout_material_none_safe(self):
        # Should not raise exception on None or empty material
        auto_layout_material(None)
        mat = bpy.data.materials.new("EmptyMat")
        try:
            # Material without nodes
            auto_layout_material(mat)
        finally:
            bpy.data.materials.remove(mat)

    def test_layout_atlas_material_in_blender(self):
        # Create a material and populate with dummy nodes matching MTK names
        mat = bpy.data.materials.new("LayoutTestMat")
        try:
            ensure_material_node_tree(mat)
            nodes = mat.node_tree.nodes
            nodes.clear()
            uv_node = nodes.new("ShaderNodeUVMap")
            uv_node.name = "UV Map"

            albedo_node = nodes.new("ShaderNodeTexImage")
            albedo_node.name = "Atlas Albedo Texture"

            normal_node = nodes.new("ShaderNodeTexImage")
            normal_node.name = "Atlas Normal Texture"

            orm_node = nodes.new("ShaderNodeTexImage")
            orm_node.name = "Atlas ORM Texture"

            bsdf_node = nodes.new("ShaderNodeBsdfPrincipled")
            bsdf_node.name = "Principled BSDF"

            output_node = nodes.new("ShaderNodeOutputMaterial")
            output_node.name = "Material Output"

            # Apply layout with Normal and ORM active
            auto_layout_material(
                mat,
                is_animated=False,
                has_overlay=False,
                has_normal=True,
                has_orm=True,
                has_aux=False,
                use_attribute_node=False,
            )

            # Assert horizontal left-to-right flow: UV < Textures < Shading < Output
            self.assertLess(uv_node.location.x, albedo_node.location.x)
            self.assertLess(albedo_node.location.x, bsdf_node.location.x)
            self.assertLess(bsdf_node.location.x, output_node.location.x)

            # Assert vertical ordering of textures without overlap: Albedo > Normal > ORM
            self.assertGreater(albedo_node.location.y, normal_node.location.y)
            self.assertGreater(normal_node.location.y, orm_node.location.y)

            # Verify gap is at least node height + padding
            self.assertGreaterEqual(albedo_node.location.y - normal_node.location.y, 280.0)
            self.assertGreaterEqual(normal_node.location.y - orm_node.location.y, 280.0)

            # When Biome Tint is absent, BSDF shifts left to close the empty void
            bsdf_no_tint_x = bsdf_node.location.x

            # Now test with has_biome_tint=True
            auto_layout_material(
                mat,
                is_animated=False,
                has_overlay=False,
                has_normal=True,
                has_orm=True,
                has_aux=False,
                use_attribute_node=False,
                has_biome_tint=True,
            )
            self.assertGreater(bsdf_node.location.x, bsdf_no_tint_x)
            # The leftward shift to eliminate the biome tint gap should be exactly 980 px
            self.assertAlmostEqual(bsdf_node.location.x - bsdf_no_tint_x, 980.0, delta=1.0)
        finally:
            bpy.data.materials.remove(mat)


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for restored lightweight utility operators:
- Clear Custom Normals
- Set Texture Interpolation Closest
- Select Hard Edges
- Scale UV
"""

import math
import unittest
from unittest.mock import MagicMock

try:
    import bpy
    import bmesh
    HAS_BPY = True
except ImportError:
    bpy = None
    bmesh = None
    HAS_BPY = False

import operators
import ui
from utils.system.menu_registry import (
    draw_dynamic_menu,
    get_all_operators,
    get_default_presets,
)


class TestRestoredOperators(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if HAS_BPY:
            operators.register()
            ui.register()

    @classmethod
    def tearDownClass(cls):
        if HAS_BPY:
            try:
                ui.unregister()
            except Exception:
                pass
            try:
                operators.unregister()
            except Exception:
                pass

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_operators_registered_in_menu_registry(self):
        all_ops = get_all_operators()
        self.assertIn("mozi.clear_custom_normals", all_ops)
        self.assertIn("mozi.set_texture_interpolation_closest", all_ops)
        self.assertIn("mozi.select_hard_edges", all_ops)
        self.assertIn("mozi.scale_uv", all_ops)

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_clear_custom_normals(self):
        mesh = bpy.data.meshes.new("TestNormalMesh")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=2.0)
        bm.to_mesh(mesh)
        bm.free()

        # Add a custom normal attribute
        mesh.attributes.new(name="custom_normal", type="FLOAT_VECTOR", domain="CORNER")
        self.assertIn("custom_normal", mesh.attributes)

        obj = bpy.data.objects.new("TestNormalObj", mesh)
        bpy.context.collection.objects.link(obj)

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        res = bpy.ops.mozi.clear_custom_normals()
        self.assertEqual(res, {"FINISHED"})
        self.assertNotIn("custom_normal", mesh.attributes)

        # Cleanup
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_texture_interpolation_closest(self):
        mesh = bpy.data.meshes.new("TestTexMesh")
        obj = bpy.data.objects.new("TestTexObj", mesh)
        bpy.context.collection.objects.link(obj)

        mat = bpy.data.materials.new("TestTexMat")
        mat.use_nodes = True
        tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex_node.interpolation = "Linear"
        obj.data.materials.append(mat)

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        res = bpy.ops.mozi.set_texture_interpolation_closest(interpolation="Closest")
        self.assertEqual(res, {"FINISHED"})
        self.assertEqual(tex_node.interpolation, "Closest")

        # Cleanup
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)
        bpy.data.materials.remove(mat)

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_select_hard_edges(self):
        mesh = bpy.data.meshes.new("TestEdgeMesh")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=2.0)
        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new("TestEdgeObj", mesh)
        bpy.context.collection.objects.link(obj)

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        # Enter edit mode
        bpy.ops.object.mode_set(mode="EDIT")
        res = bpy.ops.mozi.select_hard_edges(sharp_angle=30.0, selection_mode="SET")
        self.assertEqual(res, {"FINISHED"})

        bpy.ops.object.mode_set(mode="OBJECT")

        # Cleanup
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_scale_uv(self):
        mesh = bpy.data.meshes.new("TestUVMesh")
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=2, y_segments=2, size=2.0)
        uv_layer = bm.loops.layers.uv.verify()
        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new("TestUVObj", mesh)
        bpy.context.collection.objects.link(obj)

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        # Enter edit mode
        bpy.ops.object.mode_set(mode="EDIT")
        res = bpy.ops.mozi.scale_uv(scale_factor=0.5, selection_scope="ALL")
        self.assertEqual(res, {"FINISHED"})

        bpy.ops.object.mode_set(mode="OBJECT")

        # Cleanup
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)


if __name__ == "__main__":
    unittest.main()

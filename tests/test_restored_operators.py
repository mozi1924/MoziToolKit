"""
Unit tests for restored lightweight utility operators:
- Clear Custom Normals
- Set Texture Interpolation Closest
- Select Hard Edges
- Scale UV
"""

import math
import sys
import unittest
from pathlib import Path
import unittest

import bmesh
import bpy
import bpy_extras

from MoziToolKit.utils.materials.builder import ensure_material_node_tree
import MoziToolKit.operators as operators
import MoziToolKit.ui as ui

from MoziToolKit.utils.system.menu_registry import (
    draw_dynamic_menu,
    get_all_operators,
    get_default_presets,
)


class TestRestoredOperators(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            operators.register()
        except Exception:
            pass
        try:
            ui.register()
        except Exception:
            pass

    @classmethod
    def tearDownClass(cls):
        try:
            ui.unregister()
        except Exception:
            pass
        try:
            operators.unregister()
        except Exception:
            pass

    def test_operators_registered_in_menu_registry(self):
        all_ops = get_all_operators()
        self.assertIn("mozi.clear_custom_normals", all_ops)
        self.assertIn("mozi.set_texture_interpolation_closest", all_ops)
        self.assertIn("mozi.select_hard_edges", all_ops)
        self.assertIn("mozi.scale_uv", all_ops)

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

    def test_texture_interpolation_closest(self):
        mesh = bpy.data.meshes.new("TestTexMesh")
        obj = bpy.data.objects.new("TestTexObj", mesh)
        bpy.context.collection.objects.link(obj)

        mat = bpy.data.materials.new("TestTexMat")
        ensure_material_node_tree(mat)
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

    def test_repair_fluid_uv(self):
        mesh = bpy.data.meshes.new("TestFluidMesh")
        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.verify()

        v0 = bm.verts.new((0.0, 0.0, 1.0))
        v1 = bm.verts.new((0.0, 0.0, 0.0))
        v2 = bm.verts.new((0.0, 0.2, 0.0))
        v3 = bm.verts.new((0.0, 0.8, 1.0))
        face = bm.faces.new([v0, v1, v2, v3])
        face.select = True

        loops = list(face.loops)
        loops[0][uv_layer].uv = (1.0, 0.0)
        loops[1][uv_layer].uv = (0.0, 0.0)
        loops[2][uv_layer].uv = (0.0, 0.8)  # Inverted
        loops[3][uv_layer].uv = (1.0, 0.2)  # Inverted

        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new("TestFluidObj", mesh)
        bpy.context.collection.objects.link(obj)

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        bpy.ops.object.mode_set(mode="EDIT")
        res = bpy.ops.mozi.repair_fluid_uv(selection_scope="ALL")
        self.assertEqual(res, {"FINISHED"})
        bpy.ops.object.mode_set(mode="OBJECT")

        # Read back UVs
        bm_check = bmesh.new()
        bm_check.from_mesh(mesh)
        bm_check.faces.ensure_lookup_table()
        uv_check = bm_check.loops.layers.uv.verify()
        f = bm_check.faces[0]
        self.assertAlmostEqual(f.loops[2][uv_check].uv.y, 0.2, places=4)
        self.assertAlmostEqual(f.loops[3][uv_check].uv.y, 0.8, places=4)
        bm_check.free()


        # Cleanup
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)

    def test_adaptive_pixel_split_operator(self):
        mesh = bpy.data.meshes.new("TestSplitMesh")
        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.verify()

        v0 = bm.verts.new((-0.5, -0.5, 0.0))
        v1 = bm.verts.new((0.5, -0.5, 0.0))
        v2 = bm.verts.new((0.5, 0.5, 0.0))
        v3 = bm.verts.new((-0.5, 0.5, 0.0))
        face = bm.faces.new([v0, v1, v2, v3])
        face.select = True

        loops = list(face.loops)
        loops[0][uv_layer].uv = (0.0, 0.0)
        loops[1][uv_layer].uv = (1.0, 0.0)
        loops[2][uv_layer].uv = (1.0, 1.0)
        loops[3][uv_layer].uv = (0.0, 1.0)

        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new("TestSplitObj", mesh)
        bpy.context.collection.objects.link(obj)

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        bpy.ops.object.mode_set(mode="EDIT")
        res = bpy.ops.mozi.adaptive_pixel_split(
            manual_resolution=(2, 2),
            pixels_per_face=1.0,
            auto_resolution=False,
            selection_scope="ALL",
        )
        self.assertEqual(res, {"FINISHED"})
        bpy.ops.object.mode_set(mode="OBJECT")

        # 2x2 subdivision on 1 quad should result in 4 quads
        self.assertEqual(len(mesh.polygons), 4)

        # Cleanup
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)

    def _make_diamond_object(self, name: str):
        mesh = bpy.data.meshes.new(name)
        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.verify()
        verts = [
            bm.verts.new((-0.5, -0.5, 0.0)),
            bm.verts.new((0.5, -0.5, 0.0)),
            bm.verts.new((0.5, 0.5, 0.0)),
            bm.verts.new((-0.5, 0.5, 0.0)),
        ]
        face = bm.faces.new(verts)
        face.select = True
        for loop, uv in zip(face.loops, [(0.5, 0.0), (1.0, 0.5), (0.5, 1.0), (0.0, 0.5)]):
            loop[uv_layer].uv = uv
        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        return obj, mesh

    def test_adaptive_pixel_split_quadifies_rotated_uvs(self):
        """Rotated UV slicing must be recoverable to quads for extrusion workflows."""
        obj, mesh = self._make_diamond_object("TestSplitDiamond")
        bpy.ops.object.mode_set(mode="EDIT")
        res = bpy.ops.mozi.adaptive_pixel_split(
            manual_resolution=(8, 8),
            pixels_per_face=1.0,
            auto_resolution=False,
            selection_scope="ALL",
            quadify=True,
        )
        self.assertEqual(res, {"FINISHED"})
        bpy.ops.object.mode_set(mode="OBJECT")

        sizes = [len(p.vertices) for p in mesh.polygons]
        self.assertGreater(sizes.count(4), 0, "expected recovered quads")
        self.assertLess(sizes.count(3), len(sizes), "expected most triangles to be paired")
        self.assertEqual(sizes.count(5), 0)

        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)

    def test_adaptive_pixel_split_can_keep_triangles(self):
        """Disabling quadify must leave the raw triangulated slicing output."""
        obj, mesh = self._make_diamond_object("TestSplitDiamondRaw")
        bpy.ops.object.mode_set(mode="EDIT")
        res = bpy.ops.mozi.adaptive_pixel_split(
            manual_resolution=(4, 4),
            pixels_per_face=1.0,
            auto_resolution=False,
            selection_scope="ALL",
            quadify=False,
        )
        self.assertEqual(res, {"FINISHED"})
        bpy.ops.object.mode_set(mode="OBJECT")

        self.assertTrue(all(len(p.vertices) == 3 for p in mesh.polygons))

        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)


if __name__ == "__main__":
    import sys
    if "--" in sys.argv:
        argv = [sys.argv[0]] + sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = [sys.argv[0]]
    unittest.main(argv=argv)



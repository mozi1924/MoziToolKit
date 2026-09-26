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
from unittest.mock import MagicMock

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

for p in [str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import bpy
    import bmesh
    import bpy_extras
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes") and not isinstance(bpy.data, MagicMock)
except ImportError:
    bpy = MagicMock()
    bmesh = MagicMock()
    import types
    bpy_extras = types.ModuleType("bpy_extras")
    bpy_extras.__path__ = []
    
    class _MockOperator: pass
    class _MockPanel: pass
    class _MockMenu: pass
    class _MockPropertyGroup: pass
    class _MockUIList: pass
    class _MockAddonPreferences: pass
    class _MockExportHelper: pass
    class _MockImportHelper: pass

    class _MockTypes:
        Operator = _MockOperator
        Panel = _MockPanel
        Menu = _MockMenu
        PropertyGroup = _MockPropertyGroup
        UIList = _MockUIList
        AddonPreferences = _MockAddonPreferences

    class _MockIoUtils:
        ExportHelper = _MockExportHelper
        ImportHelper = _MockImportHelper

    io_utils_mod = types.ModuleType("bpy_extras.io_utils")
    io_utils_mod.ExportHelper = _MockExportHelper
    io_utils_mod.ImportHelper = _MockImportHelper

    bpy.types = _MockTypes
    bpy.app = MagicMock()
    bpy.props = MagicMock()
    bpy_extras.io_utils = io_utils_mod

    sys.modules["bpy"] = bpy
    sys.modules["bpy.props"] = bpy.props
    sys.modules["bpy.types"] = _MockTypes
    sys.modules["bpy.app"] = bpy.app
    sys.modules["bmesh"] = bmesh
    sys.modules["bpy_extras"] = bpy_extras
    sys.modules["bpy_extras.io_utils"] = io_utils_mod
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

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
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


if __name__ == "__main__":
    import sys
    if "--" in sys.argv:
        argv = [sys.argv[0]] + sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = [sys.argv[0]]
    unittest.main(argv=argv)



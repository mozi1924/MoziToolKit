"""
Unit tests covering code review fixes and security improvements in MoziToolKit.
"""

import os
import sys
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_ROOT.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import bpy
    import bmesh
    from mathutils import Vector
    HAS_BPY = True
except ImportError:
    HAS_BPY = False


class TestCodeReviewFixes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not HAS_BPY:
            return
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "MoziToolKit",
                str(PROJECT_ROOT / "__init__.py"),
                submodule_search_locations=[str(PROJECT_ROOT)]
            )
            pkg = importlib.util.module_from_spec(spec)
            sys.modules["MoziToolKit"] = pkg
            spec.loader.exec_module(pkg)
            if hasattr(pkg, "register"):
                pkg.register()
        except Exception as e:
            print(f"[Test Init] Registration note: {e}")

    def setUp(self):
        if not HAS_BPY:
            return
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action='DESELECT')
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in list(bpy.data.meshes):
            bpy.data.meshes.remove(mesh, do_unlink=True)
        for mat in list(bpy.data.materials):
            bpy.data.materials.remove(mat, do_unlink=True)

    def test_zip_slip_security_prevention(self):
        """ZipResourcePack must reject malicious archives containing path traversal entries."""
        from utils.materials.resource_pack import ZipResourcePack

        with tempfile.TemporaryDirectory() as tmp_dir:
            malicious_zip = Path(tmp_dir) / "malicious.zip"
            with zipfile.ZipFile(malicious_zip, "w") as zf:
                zf.writestr("pack.mcmeta", '{"pack":{"pack_format":15,"description":"Test"}}')
                zf.writestr("../evil.txt", "malicious payload")
                zf.writestr("assets/minecraft/textures/block/stone.png", b"dummy_bytes")

            with self.assertRaises(ValueError) as ctx:
                ZipResourcePack(malicious_zip, use_cache=False)
            self.assertIn("zip-slip", str(ctx.exception).lower())

    def test_unmerge_block_faces_edit_mode_safe(self):
        """Unmerge block faces operator must not crash when executed in EDIT mode."""
        if not HAS_BPY:
            self.skipTest("bpy not available")

        bpy.ops.mesh.primitive_cube_add()
        cube = bpy.context.active_object
        bpy.ops.object.mode_set(mode="EDIT")
        self.assertEqual(bpy.context.mode, "EDIT_MESH")

        # Execute unmerge block faces operator while in EDIT mode
        res = bpy.ops.mozi.unmerge_block_faces()
        self.assertEqual(res, {'FINISHED'})
        # Must safely remain in EDIT mode after completion
        self.assertEqual(bpy.context.mode, "EDIT_MESH")

        bpy.ops.object.mode_set(mode="OBJECT")

    def test_scale_uv_respects_face_selection(self):
        """ScaleUVStep must scale only selected faces when faces are explicitly selected."""
        if not HAS_BPY:
            self.skipTest("bpy not available")

        from pipeline.presets import run_preset_pipeline

        bpy.ops.mesh.primitive_cube_add()
        cube = bpy.context.active_object
        bpy.ops.object.mode_set(mode="EDIT")

        bm = bmesh.from_edit_mesh(cube.data)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.verify()

        # Select only face 0
        for f in bm.faces:
            f.select = False
        bm.faces[0].select = True
        bmesh.update_edit_mesh(cube.data)

        orig_face0_uvs = [loop[uv_layer].uv.copy() for loop in bm.faces[0].loops]
        orig_face1_uvs = [loop[uv_layer].uv.copy() for loop in bm.faces[1].loops]

        # Execute scale_uv
        res, ctx = run_preset_pipeline("scale_uv", bpy.context, params={"scale_factor": 0.5})
        self.assertTrue(res.is_success)

        bm = bmesh.from_edit_mesh(cube.data)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.verify()

        # Face 0 (selected) must be scaled
        new_face0_uvs = [loop[uv_layer].uv for loop in bm.faces[0].loops]
        self.assertTrue(any((n - o).length > 1e-4 for n, o in zip(new_face0_uvs, orig_face0_uvs)))

        # Face 1 (unselected) must NOT be scaled
        new_face1_uvs = [loop[uv_layer].uv for loop in bm.faces[1].loops]
        for n, o in zip(new_face1_uvs, orig_face1_uvs):
            self.assertAlmostEqual((n - o).length, 0.0, places=5)

        bpy.ops.object.mode_set(mode="OBJECT")

    def test_adaptive_pixel_split_restores_active_and_mode(self):
        """AdaptivePixelSplitStep must restore initial active object and initial mode."""
        if not HAS_BPY:
            self.skipTest("bpy not available")

        from pipeline.steps.step_adaptive_pixel_split import AdaptivePixelSplitStep
        from pipeline.context import PipelineContext

        bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
        cube1 = bpy.context.active_object
        cube1.name = "Cube1"

        bpy.ops.mesh.primitive_cube_add(location=(5, 0, 0))
        cube2 = bpy.context.active_object
        cube2.name = "Cube2"

        # Set active to cube2, in OBJECT mode
        bpy.context.view_layer.objects.active = cube2
        self.assertEqual(bpy.context.view_layer.objects.active, cube2)

        step = AdaptivePixelSplitStep()
        ctx = PipelineContext(
            context=bpy.context,
            target_objects=[cube1],
            params={"auto_resolution": False, "resolution_width": 16, "resolution_height": 16}
        )
        res = step.execute(ctx)
        self.assertTrue(res.is_success)

        # Active object must be restored to cube2
        self.assertEqual(bpy.context.view_layer.objects.active, cube2)
        # Mode must be OBJECT
        self.assertEqual(bpy.context.mode, "OBJECT")

    def test_uninstall_dependency_operators_have_confirm_dialog(self):
        """Uninstall operators must provide invoke confirmation methods."""
        from operators.misc.op_dependencies import (
            MOZI_OT_uninstall_dependency,
            MOZI_OT_uninstall_all_dependencies,
        )

        self.assertTrue(hasattr(MOZI_OT_uninstall_dependency, "invoke"))
        self.assertTrue(hasattr(MOZI_OT_uninstall_dependency, "draw"))
        self.assertTrue(hasattr(MOZI_OT_uninstall_all_dependencies, "invoke"))
        self.assertTrue(hasattr(MOZI_OT_uninstall_all_dependencies, "draw"))


if __name__ == "__main__":
    import sys
    unittest.main(argv=[sys.argv[0]])

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

    def test_misc_operators_registered(self):
        """Misc operators for preferences navigation and cache cleanup must be valid."""
        from operators.misc.op_dependencies import (
            MOZI_OT_open_preferences,
            MOZI_OT_check_dependencies,
            MOZI_OT_clear_cache,
        )

        self.assertTrue(hasattr(MOZI_OT_open_preferences, "bl_idname"))
        self.assertTrue(hasattr(MOZI_OT_check_dependencies, "bl_idname"))
        self.assertTrue(hasattr(MOZI_OT_clear_cache, "bl_idname"))

    def test_subdivide_quad_inherits_rotated_uv_orientation(self):
        """When unmerging a rotated quad face (normalize_uvs=True), sub-faces must inherit the rotation."""
        if not HAS_BPY:
            self.skipTest("bpy not available")

        from utils.mesh.subdivide import subdivide_quad_face

        bm = bmesh.new()
        uv_lay = bm.loops.layers.uv.new("UVMap")

        # Create a 2x1 quad face spanning (0,0) to (2,1)
        v0 = bm.verts.new((0, 0, 0))
        v1 = bm.verts.new((2, 0, 0))
        v2 = bm.verts.new((2, 1, 0))
        v3 = bm.verts.new((0, 1, 0))
        face = bm.faces.new([v0, v1, v2, v3])

        # Assign 90-degree rotated UV coordinates spanning 2x1 blocks
        # Normal 0-deg unrotated: v0=(0,0), v1=(2,0), v2=(2,1), v3=(0,1)
        # 90-deg rotated: v0=(0,1), v1=(0,0), v2=(2,0), v3=(2,1)
        face.loops[0][uv_lay].uv = Vector((0.0, 1.0))
        face.loops[1][uv_lay].uv = Vector((0.0, 0.0))
        face.loops[2][uv_lay].uv = Vector((2.0, 0.0))
        face.loops[3][uv_lay].uv = Vector((2.0, 1.0))

        sub_faces = subdivide_quad_face(bm, face, cols=2, rows=1, normalize_uvs=True, uv_layer=uv_lay)
        self.assertEqual(len(sub_faces), 2)

        # Both sub-faces must preserve the 90-degree rotation orientation in their [0, 1] normalized UVs
        for sf in sub_faces:
            uvs = [l[uv_lay].uv for l in sf.loops]
            self.assertAlmostEqual(uvs[0].x, 0.0)
            self.assertAlmostEqual(uvs[0].y, 1.0)
            self.assertAlmostEqual(uvs[1].x, 0.0)
            self.assertAlmostEqual(uvs[1].y, 0.0)
            self.assertAlmostEqual(uvs[2].x, 1.0)
            self.assertAlmostEqual(uvs[2].y, 0.0)
            self.assertAlmostEqual(uvs[3].x, 1.0)
            self.assertAlmostEqual(uvs[3].y, 1.0)

        bm.free()

    def test_zip_bomb_member_count_limit(self):
        """ZipResourcePack._safe_extract must reject archives exceeding MAX_ZIP_MEMBER_COUNT."""
        from utils.materials.resource_pack import ZipResourcePack, MAX_ZIP_MEMBER_COUNT
        import unittest.mock as mock

        with tempfile.TemporaryDirectory() as tmp_dir:
            test_zip = Path(tmp_dir) / "too_many_members.zip"
            with zipfile.ZipFile(test_zip, "w") as zf:
                zf.writestr("pack.mcmeta", '{"pack":{"pack_format":15,"description":"Test"}}')
                zf.writestr("assets/minecraft/textures/block/stone.png", b"dummy")

            # Mock infolist to simulate exceeding file count
            with zipfile.ZipFile(test_zip, "r") as zf:
                fake_infos = [zipfile.ZipInfo(f"file_{i}.txt") for i in range(MAX_ZIP_MEMBER_COUNT + 10)]
                for fi in fake_infos:
                    fi.file_size = 10
                with mock.patch.object(zf, "infolist", return_value=fake_infos):
                    with self.assertRaises(ValueError) as ctx:
                        ZipResourcePack._safe_extract(zf, Path(tmp_dir) / "extracted")
                    self.assertIn("too many entries", str(ctx.exception).lower())

    def test_zip_bomb_uncompressed_size_limit(self):
        """ZipResourcePack._safe_extract must reject archives exceeding MAX_ZIP_TOTAL_UNCOMPRESSED."""
        from utils.materials.resource_pack import ZipResourcePack, MAX_ZIP_TOTAL_UNCOMPRESSED
        import unittest.mock as mock

        with tempfile.TemporaryDirectory() as tmp_dir:
            test_zip = Path(tmp_dir) / "bomb.zip"
            with zipfile.ZipFile(test_zip, "w") as zf:
                zf.writestr("pack.mcmeta", '{"pack":{"pack_format":15,"description":"Test"}}')

            with zipfile.ZipFile(test_zip, "r") as zf:
                fake_info = zipfile.ZipInfo("huge_file.dat")
                fake_info.file_size = MAX_ZIP_TOTAL_UNCOMPRESSED + 1024 * 1024
                with mock.patch.object(zf, "infolist", return_value=[fake_info]):
                    with self.assertRaises(ValueError) as ctx:
                        ZipResourcePack._safe_extract(zf, Path(tmp_dir) / "extracted")
                    self.assertIn("zip bomb", str(ctx.exception).lower())

    def test_auto_load_toposort_deadlock_prevention(self):
        """auto_load.toposort must break circular dependency deadlock instead of infinite looping."""
        from auto_load import toposort

        class ClassA:
            pass

        class ClassB:
            pass

        # Mutual circular dependency
        deps_dict = {
            ClassA: {ClassB},
            ClassB: {ClassA},
        }

        # Must terminate promptly and return classes
        result = toposort(deps_dict)
        self.assertEqual(len(result), 2)
        self.assertIn(ClassA, result)
        self.assertIn(ClassB, result)

    def test_menu_config_untrusted_operator_filter(self):
        """menu_config._normalize_views_data must filter out arbitrary/unregistered operators."""
        from utils.system.menu_config import _normalize_views_data

        untrusted_views = {
            "mesh": [
                {"operator": "wm.quit_blender", "label": "Quit Blender", "enabled": True},
                {"operator": "mozi.select_hard_edges", "label": "Select Hard Edges", "enabled": True},
            ]
        }
        normalized = _normalize_views_data(untrusted_views)
        mesh_items = normalized.get("mesh", [])
        operators = [item.get("operator") for item in mesh_items]
        self.assertNotIn("wm.quit_blender", operators)
        self.assertIn("mozi.select_hard_edges", operators)


if __name__ == "__main__":
    import sys
    unittest.main(argv=[sys.argv[0]])


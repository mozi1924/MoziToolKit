"""
Unit tests for Dependency Manager and Preference UI integration in MoziToolKit.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from MoziToolKit.utils.system import (
    DEPENDENCIES,
    ensure_sys_paths,
    get_all_dependency_statuses,
    get_dependency_status,
    get_python_executable,
    has_all_dependencies,
    has_pillow,
    is_module_installed,
    get_prefs,
)
from MoziToolKit.pipeline.modal import MOZI_OT_modal_pipeline_runner, run_pipeline_modal
from MoziToolKit.pipeline.pipeline import Pipeline


class TestDependencyManager(unittest.TestCase):
    """Test suite for utils.dependencies and dependency management operators."""

    def test_ensure_sys_paths(self):
        """ensure_sys_paths should return a list of added paths without throwing exceptions."""
        added = ensure_sys_paths()
        self.assertIsInstance(added, list)

    def test_get_python_executable(self):
        """get_python_executable should resolve a valid string path."""
        exe = get_python_executable()
        self.assertTrue(isinstance(exe, str) and len(exe) > 0)

    def test_dependencies_registry(self):
        """Pillow should be registered in DEPENDENCIES."""
        self.assertIn("Pillow", DEPENDENCIES)
        pillow_dep = DEPENDENCIES["Pillow"]
        self.assertEqual(pillow_dep.module_name, "PIL")
        self.assertEqual(pillow_dep.name, "Pillow")

    def test_is_module_installed(self):
        """Built-in modules like 'sys' and 'os' must be detected as installed."""
        self.assertTrue(is_module_installed("sys"))
        self.assertTrue(is_module_installed("os"))
        self.assertFalse(is_module_installed("non_existent_fake_package_xyz123"))

    def test_get_dependency_status(self):
        """get_dependency_status should return structured dict with expected keys."""
        status = get_dependency_status(DEPENDENCIES["Pillow"])
        for key in ["name", "module_name", "display_name", "installed", "version", "is_satisfied", "required_by"]:
            self.assertIn(key, status)

    def test_get_all_dependency_statuses(self):
        """get_all_dependency_statuses should return non-empty list of statuses."""
        statuses = get_all_dependency_statuses()
        self.assertGreaterEqual(len(statuses), 1)
        self.assertEqual(statuses[0]["name"], "Pillow")

    def test_has_pillow_helper(self):
        """has_pillow should return bool corresponding to is_module_installed('PIL')."""
        self.assertEqual(has_pillow(), is_module_installed("PIL"))

    def test_get_prefs_safe_access(self):
        """get_prefs should safely query preferences without raising exceptions."""
        try:
            import bpy
            prefs = get_prefs(bpy.context)
            # prefs may be None if addon not enabled in vanilla test run, or an AddonPreferences instance
            self.assertTrue(prefs is None or hasattr(prefs, "bl_idname"))
        except ImportError:
            prefs = get_prefs()
            self.assertIsNone(prefs)

    def test_modal_pipeline_concurrency_mutex(self):
        """When a modal runner is active, secondary run_pipeline_modal calls must be rejected."""
        try:
            import bpy
        except ImportError:
            self.skipTest("bpy not available")

        # Ensure active runners is initially empty
        initial_runners = dict(MOZI_OT_modal_pipeline_runner._active_runners)
        try:
            MOZI_OT_modal_pipeline_runner._active_runners.clear()
            self.assertFalse(MOZI_OT_modal_pipeline_runner.is_running())

            # Simulate an active runner
            MOZI_OT_modal_pipeline_runner._active_runners["test-runner-lock"] = {
                "title": "Running Task",
            }
            self.assertTrue(MOZI_OT_modal_pipeline_runner.is_running())

            pipeline = Pipeline(name="TestMutexPipeline", steps=[])
            res, ctx = run_pipeline_modal(pipeline, bpy.context)
            self.assertFalse(res.is_success)
            self.assertIn("in progress", res.message)

        finally:
            MOZI_OT_modal_pipeline_runner._active_runners.clear()
            MOZI_OT_modal_pipeline_runner._active_runners.update(initial_runners)

    def test_atlas_mode_guards_missing_pillow(self):
        """When Pillow is not installed, running replace_material with ATLAS mode must fail gracefully."""
        try:
            import bpy
        except ImportError:
            self.skipTest("bpy not available in pure python environment")

        import tempfile
        import zipfile
        from MoziToolKit.pipeline.presets import run_preset_pipeline

        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = Path(tmp_dir) / "dummy_pack.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("pack.mcmeta", '{"pack":{"pack_format":15,"description":"Test"}}')
                zf.writestr("assets/minecraft/textures/block/stone.png", b"dummy_png_bytes")

            with patch("MoziToolKit.utils.system.dependencies.has_pillow", return_value=False), \
                 patch("MoziToolKit.pipeline.steps.step_replace_material.has_pillow", return_value=False):
                # Create a test mesh object
                if bpy.context.mode != "OBJECT":
                    bpy.ops.object.mode_set(mode="OBJECT")
                bpy.ops.mesh.primitive_cube_add()
                cube = bpy.context.active_object
                mat = bpy.data.materials.new(name="stone")
                cube.data.materials.append(mat)

                params = {
                    "zip_path": str(zip_path),
                    "material_mode": "ATLAS",
                    "use_cache": False,
                }
                res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[cube])
                self.assertFalse(res.is_success)
                self.assertIn("Pillow", res.message)

                # Clean up cube and material
                bpy.data.objects.remove(cube, do_unlink=True)
                bpy.data.materials.remove(mat, do_unlink=True)

    def test_standalone_mode_guards_missing_pillow(self):
        """When Pillow is not installed, running replace_material with STANDALONE mode must fail gracefully."""
        try:
            import bpy
        except ImportError:
            self.skipTest("bpy not available in pure python environment")

        import tempfile
        import zipfile
        from MoziToolKit.pipeline.presets import run_preset_pipeline

        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = Path(tmp_dir) / "dummy_pack.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("pack.mcmeta", '{"pack":{"pack_format":15,"description":"Test"}}')
                zf.writestr("assets/minecraft/textures/block/stone.png", b"dummy_png_bytes")

            with patch("MoziToolKit.utils.system.dependencies.has_pillow", return_value=False), \
                 patch("MoziToolKit.pipeline.steps.step_replace_material.has_pillow", return_value=False):
                if bpy.context.mode != "OBJECT":
                    bpy.ops.object.mode_set(mode="OBJECT")
                bpy.ops.mesh.primitive_cube_add()
                cube = bpy.context.active_object
                mat = bpy.data.materials.new(name="stone")
                cube.data.materials.append(mat)

                params = {
                    "zip_path": str(zip_path),
                    "material_mode": "STANDALONE",
                    "use_cache": False,
                }
                res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[cube])
                self.assertFalse(res.is_success)
                self.assertIn("Pillow", res.message)

                bpy.data.objects.remove(cube, do_unlink=True)
                bpy.data.materials.remove(mat, do_unlink=True)

    def test_zip_slip_security_prevention(self):
        """ZipResourcePack must reject malicious archives containing path traversal entries."""
        from utils.materials.resource_pack import ZipResourcePack
        import tempfile
        import zipfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            malicious_zip = Path(tmp_dir) / "malicious.zip"
            with zipfile.ZipFile(malicious_zip, "w") as zf:
                zf.writestr("pack.mcmeta", '{"pack":{"pack_format":15,"description":"Test"}}')
                zf.writestr("../evil.txt", "malicious payload")
                zf.writestr("assets/minecraft/textures/block/stone.png", b"dummy_bytes")

            with self.assertRaises(ValueError) as ctx:
                ZipResourcePack(malicious_zip, use_cache=False)
            self.assertIn("zip-slip", str(ctx.exception).lower())

    def test_zip_bomb_member_count_limit(self):
        """ZipResourcePack._safe_extract must reject archives exceeding MAX_ZIP_MEMBER_COUNT."""
        from utils.materials.resource_pack import ZipResourcePack, MAX_ZIP_MEMBER_COUNT
        import tempfile
        import zipfile
        import unittest.mock as mock

        with tempfile.TemporaryDirectory() as tmp_dir:
            test_zip = Path(tmp_dir) / "too_many_members.zip"
            with zipfile.ZipFile(test_zip, "w") as zf:
                zf.writestr("pack.mcmeta", '{"pack":{"pack_format":15,"description":"Test"}}')
                zf.writestr("assets/minecraft/textures/block/stone.png", b"dummy")

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
        import tempfile
        import zipfile
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
        from MoziToolKit.auto_load import toposort

        class ClassA:
            pass

        class ClassB:
            pass

        deps_dict = {
            ClassA: {ClassB},
            ClassB: {ClassA},
        }

        result = toposort(deps_dict)
        self.assertEqual(len(result), 2)
        self.assertIn(ClassA, result)
        self.assertIn(ClassB, result)

    def test_menu_config_untrusted_operator_filter(self):
        """menu_config._normalize_views_data must filter out arbitrary/unregistered operators."""
        from MoziToolKit.utils.system.menu_config import _normalize_views_data

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

    def test_misc_operators_registered(self):
        """Misc operators for preferences navigation and cache cleanup must be valid."""
        from MoziToolKit.operators.misc.op_dependencies import (
            MOZI_OT_open_preferences,
            MOZI_OT_check_dependencies,
            MOZI_OT_clear_cache,
        )

        self.assertTrue(hasattr(MOZI_OT_open_preferences, "bl_idname"))
        self.assertTrue(hasattr(MOZI_OT_check_dependencies, "bl_idname"))
        self.assertTrue(hasattr(MOZI_OT_clear_cache, "bl_idname"))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])


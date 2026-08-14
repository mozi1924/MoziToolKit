"""
Unit tests for Dependency Manager and Preference UI integration in MoziToolKit.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from utils.dependencies import (
    DEPENDENCIES,
    ensure_sys_paths,
    get_all_dependency_statuses,
    get_dependency_status,
    get_python_executable,
    has_all_dependencies,
    has_pillow,
    is_module_installed,
)


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

    def test_atlas_mode_guards_missing_pillow(self):
        """When Pillow is not installed, running replace_material with ATLAS mode must fail gracefully."""
        try:
            import bpy
        except ImportError:
            self.skipTest("bpy not available in pure python environment")

        import tempfile
        import zipfile
        from pipeline.presets import run_preset_pipeline

        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = Path(tmp_dir) / "dummy_pack.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("pack.mcmeta", '{"pack":{"pack_format":15,"description":"Test"}}')
                zf.writestr("assets/minecraft/textures/block/stone.png", b"dummy_png_bytes")

            with patch("utils.dependencies.has_pillow", return_value=False), \
                 patch("pipeline.steps.step_replace_material.has_pillow", return_value=False):
                # Create a test mesh object
                bpy.ops.wm.read_factory_settings(use_empty=True)
                bpy.ops.mesh.primitive_cube_add()
                cube = bpy.context.active_object

                params = {
                    "zip_path": str(zip_path),
                    "material_mode": "ATLAS",
                    "use_cache": False,
                }
                res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[cube])
                self.assertFalse(res.is_success)
                self.assertIn("Pillow", res.message)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

"""
Tests for unified JSON configuration backend and legacy migration (context_menus.json -> config.json).
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from MoziToolKit.utils.config.backends.json_backend import JsonConfigBackend
from MoziToolKit.utils.config.manager import ConfigManager
from MoziToolKit.utils.config.models import ConfigData, PackEntry


class TestConfigPersistenceAndMigration(unittest.TestCase):
    """Verify single JSON backend persistence and legacy context_menus.json migration."""

    def test_default_config_filename_is_config_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            old_env = os.environ.get("MOZI_CONFIG_DIR")
            try:
                os.environ["MOZI_CONFIG_DIR"] = tmp_dir
                backend = JsonConfigBackend()
                path = backend.get_config_path()
                self.assertEqual(path.name, "config.json")
                self.assertEqual(path.parent, Path(tmp_dir))
            finally:
                if old_env is not None:
                    os.environ["MOZI_CONFIG_DIR"] = old_env
                else:
                    os.environ.pop("MOZI_CONFIG_DIR", None)

    def test_migration_from_context_menus_to_config_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            legacy_file = tmp_path / "context_menus.json"
            legacy_bak = tmp_path / "context_menus.json.bak"
            target_file = tmp_path / "config.json"

            sample_data = {
                "version": 1,
                "backend_type": "JSON",
                "resource_packs": [
                    {
                        "name": "CustomPack.zip",
                        "path": "/path/to/CustomPack.zip",
                        "enabled": True,
                        "pack_type": "RESOURCE_PACK",
                        "pack_type_source": "AUTO",
                        "detected_kind": "",
                    }
                ],
                "views": {"mesh": [], "object": [], "uv": []},
            }

            with open(legacy_file, "w", encoding="utf-8") as f:
                json.dump(sample_data, f)
            with open(legacy_bak, "w", encoding="utf-8") as f:
                json.dump(sample_data, f)

            self.assertTrue(legacy_file.exists())
            self.assertTrue(legacy_bak.exists())
            self.assertFalse(target_file.exists())

            old_env = os.environ.get("MOZI_CONFIG_DIR")
            try:
                os.environ["MOZI_CONFIG_DIR"] = tmp_dir
                backend = JsonConfigBackend()
                cfg_path = backend.get_config_path()

                self.assertEqual(cfg_path, target_file)
                self.assertTrue(target_file.exists())
                # Verify legacy files were cleaned up
                self.assertFalse(legacy_file.exists())
                self.assertFalse(legacy_bak.exists())

                # Verify loaded data matches original content
                loaded = backend.load()
                self.assertEqual(len(loaded.resource_packs), 1)
                self.assertEqual(loaded.resource_packs[0].name, "CustomPack.zip")
            finally:
                if old_env is not None:
                    os.environ["MOZI_CONFIG_DIR"] = old_env
                else:
                    os.environ.pop("MOZI_CONFIG_DIR", None)

    def test_no_migration_when_only_config_json_exists(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            target_file = tmp_path / "config.json"
            legacy_file = tmp_path / "context_menus.json"

            target_data = {
                "version": 1,
                "backend_type": "JSON",
                "resource_packs": [
                    {
                        "name": "TargetPack.zip",
                        "path": "/path/to/TargetPack.zip",
                        "enabled": True,
                        "pack_type": "RESOURCE_PACK",
                        "pack_type_source": "AUTO",
                        "detected_kind": "",
                    }
                ],
            }
            with open(target_file, "w", encoding="utf-8") as f:
                json.dump(target_data, f)

            old_env = os.environ.get("MOZI_CONFIG_DIR")
            try:
                os.environ["MOZI_CONFIG_DIR"] = tmp_dir
                backend = JsonConfigBackend()
                cfg_path = backend.get_config_path()

                self.assertEqual(cfg_path, target_file)
                self.assertFalse(legacy_file.exists())
                loaded = backend.load()
                self.assertEqual(loaded.resource_packs[0].name, "TargetPack.zip")
            finally:
                if old_env is not None:
                    os.environ["MOZI_CONFIG_DIR"] = old_env
                else:
                    os.environ.pop("MOZI_CONFIG_DIR", None)

    def test_blender_preferences_backend_completely_removed(self):
        import MoziToolKit.utils.config as cfg_pkg

        self.assertFalse(hasattr(cfg_pkg, "BlenderPreferencesConfigBackend"))
        self.assertNotIn("BlenderPreferencesConfigBackend", cfg_pkg.__all__)

        # Verify manager defaults to JsonConfigBackend
        mgr = ConfigManager()
        self.assertIsInstance(mgr.get_backend(), JsonConfigBackend)
        self.assertEqual(mgr.get_backend().backend_name, "JSON")

        # Switching to BLENDER_PREFS safely returns JsonConfigBackend
        fallback_backend = mgr.switch_backend_by_name("BLENDER_PREFS")
        self.assertIsInstance(fallback_backend, JsonConfigBackend)

    def test_preferences_ui_has_no_backend_type_property(self):
        try:
            from MoziToolKit.ui.preferences import MOZI_AddonPreferences
            self.assertFalse(hasattr(MOZI_AddonPreferences, "backend_type"))
            annotations = getattr(MOZI_AddonPreferences, "__annotations__", {})
            self.assertNotIn("backend_type", annotations)
        except ImportError:
            # bpy not available in pure python headless without bpy mock
            pass


if __name__ == "__main__":
    unittest.main()

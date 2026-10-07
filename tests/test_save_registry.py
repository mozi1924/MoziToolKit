"""
Unit tests for SaveRegistryManager local privacy registry.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from utils.system.save_registry import SaveRegistryManager


class TestSaveRegistryManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry_file = Path(self.temp_dir.name) / "test_registry.json"
        self.manager = SaveRegistryManager(registry_file=self.registry_file)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_register_and_get_save(self):
        world_dir = Path(self.temp_dir.name) / "MyWorld"
        world_dir.mkdir(parents=True, exist_ok=True)

        # 1. Register save
        uuid1 = self.manager.register_save(
            world_dir=world_dir,
            dimension="overworld",
            level_name="MyWorld",
        )
        self.assertTrue(bool(uuid1))
        self.assertTrue(self.registry_file.exists())

        # 2. Query info
        info = self.manager.get_save_info(uuid1)
        self.assertIsNotNone(info)
        self.assertEqual(info["level_name"], "MyWorld")
        self.assertEqual(info["dimension"], "overworld")
        self.assertEqual(Path(info["world_dir"]), world_dir.resolve())

        # 3. Path validity
        self.assertTrue(self.manager.is_path_valid(uuid1))

        # 4. Same path + dimension returns same uuid
        uuid2 = self.manager.register_save(
            world_dir=world_dir,
            dimension="overworld",
            level_name="MyWorld Updated",
        )
        self.assertEqual(uuid1, uuid2)

    def test_relink_save(self):
        old_dir = Path(self.temp_dir.name) / "OldWorld"
        old_dir.mkdir()
        new_dir = Path(self.temp_dir.name) / "NewWorld"
        new_dir.mkdir()

        uid = self.manager.register_save(world_dir=old_dir, dimension="the_nether", level_name="OldWorld")
        self.assertEqual(self.manager.get_world_dir(uid), old_dir.resolve())

        # Relink to new directory
        res = self.manager.relink_save(uid, new_dir)
        self.assertTrue(res)
        self.assertEqual(self.manager.get_world_dir(uid), new_dir.resolve())
        self.assertTrue(self.manager.is_path_valid(uid))

    def test_persistence_across_instances(self):
        world_dir = Path(self.temp_dir.name) / "PersistWorld"
        world_dir.mkdir()

        uid = self.manager.register_save(world_dir=world_dir, dimension="the_end", level_name="EndWorld")

        # New instance reading same file
        manager2 = SaveRegistryManager(registry_file=self.registry_file)
        info = manager2.get_save_info(uid)
        self.assertIsNotNone(info)
        self.assertEqual(info["dimension"], "the_end")
        self.assertEqual(info["level_name"], "EndWorld")

    def test_aligned_with_context_menus_dir(self):
        """Verifies default registry path resides in same directory as context_menus.json."""
        import os
        from utils.config.backends.json_backend import JsonConfigBackend
        with tempfile.TemporaryDirectory() as env_tmp:
            old_env = os.environ.get("MOZI_CONFIG_DIR")
            try:
                os.environ["MOZI_CONFIG_DIR"] = env_tmp
                json_backend = JsonConfigBackend()
                menu_path = json_backend.get_config_path()

                default_manager = SaveRegistryManager()
                registry_path = default_manager.get_registry_path()

                # Both files must reside in the exact same directory!
                self.assertEqual(menu_path.parent, registry_path.parent)
                self.assertEqual(registry_path.name, "save_registry.json")
                self.assertEqual(menu_path.name, "context_menus.json")
            finally:
                if old_env is not None:
                    os.environ["MOZI_CONFIG_DIR"] = old_env
                else:
                    os.environ.pop("MOZI_CONFIG_DIR", None)

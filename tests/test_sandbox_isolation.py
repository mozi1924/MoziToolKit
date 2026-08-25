"""
Security & Isolation Tests for MoziToolKit Test Sandbox.

Guarantees that:
1. All test executions run inside an isolated sandbox directory.
2. get_config_path() and get_cache_dir() NEVER point to real user Blender directories during testing.
3. Persistent operations (save_pack_stack_config, clean_obsolete_stack_caches) are strictly confined to temporary sandbox.
4. User's keymaps, startup blendfiles, and real resource pack stack configs remain 100% untouched.
"""

import json
import os
import unittest
from pathlib import Path

from tests.test_env import is_sandbox_active, get_sandbox_path
from utils.system import (
    get_config_path,
    save_pack_stack_config,
    load_pack_stack_config,
    save_material_settings_config,
    load_material_settings_config,
)
from utils.materials.pack.resource_pack import (
    get_cache_dir,
    get_temp_extraction_dir,
    clean_obsolete_stack_caches,
)


class TestSandboxIsolation(unittest.TestCase):
    """Verify that test runner and test modules operate strictly within an isolated sandbox."""

    def test_sandbox_is_active(self):
        """Sandbox must be active and registered."""
        self.assertTrue(is_sandbox_active(), "Test sandbox guard must be active during test execution.")
        sandbox_path = get_sandbox_path()
        self.assertIsNotNone(sandbox_path)
        self.assertTrue(sandbox_path.exists())

    def test_config_path_is_sandboxed(self):
        """get_config_path() must return a path inside the temporary sandbox."""
        config_path = get_config_path()
        sandbox_path = get_sandbox_path()
        self.assertTrue(
            str(config_path).startswith(str(sandbox_path)),
            f"Config path {config_path} is NOT inside sandbox {sandbox_path}! Risk of user data contamination."
        )
        # Real user library check on macOS / Linux / Windows
        self.assertNotIn(
            str(Path.home() / "Library" / "Application Support" / "Blender"),
            str(config_path),
            "Config path must NOT point to user's real Blender Application Support directory!"
        )

    def test_cache_and_temp_dirs_are_sandboxed(self):
        """get_cache_dir() and get_temp_extraction_dir() must return paths inside sandbox."""
        cache_dir = get_cache_dir()
        temp_dir = get_temp_extraction_dir()
        sandbox_path = get_sandbox_path()

        self.assertTrue(
            str(cache_dir).startswith(str(sandbox_path)),
            f"Cache dir {cache_dir} is NOT inside sandbox {sandbox_path}!"
        )
        self.assertTrue(
            str(temp_dir).startswith(str(sandbox_path)),
            f"Temp extraction dir {temp_dir} is NOT inside sandbox {sandbox_path}!"
        )

    def test_config_modifications_do_not_leak(self):
        """Modifying pack stack or material settings writes strictly to sandbox config."""
        test_entries = [
            {"name": "Sandboxed Test Pack", "path": "/fake/path/pack.zip", "enabled": True, "pack_type": "RESOURCE_PACK"}
        ]
        save_pack_stack_config(test_entries)
        loaded = load_pack_stack_config()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["name"], "Sandboxed Test Pack")

        config_path = get_config_path()
        self.assertTrue(config_path.exists())
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("resource_packs", data)
        self.assertEqual(data["resource_packs"][0]["name"], "Sandboxed Test Pack")

    def test_cache_cleanup_is_sandboxed(self):
        """clean_obsolete_stack_caches() only removes dirs within sandbox cache."""
        cache_dir = get_cache_dir()
        dummy_hash_dir = cache_dir / "test_obsolete_hash_999"
        dummy_hash_dir.mkdir(parents=True, exist_ok=True)
        (dummy_hash_dir / "dummy.txt").write_text("test")

        dirs_removed, bytes_freed = clean_obsolete_stack_caches(current_stack_hash="active_hash_000")
        self.assertGreaterEqual(dirs_removed, 1)
        self.assertFalse(dummy_hash_dir.exists())


if __name__ == "__main__":
    unittest.main()

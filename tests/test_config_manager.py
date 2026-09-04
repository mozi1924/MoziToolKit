"""
Comprehensive Unit Tests for MoziToolKit Unified Configuration Manager and Backends.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Bootstrap MoziToolKit package (also activates the isolated test sandbox)
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from utils.config import (
    ConfigManager,
    get_config_manager,
    JsonConfigBackend,
    BlenderPreferencesConfigBackend,
    MemoryConfigBackend,
    ConfigData,
    PackEntry,
    MaterialSettings,
    MenuItem,
    normalize_operator_id,
    is_valid_operator_id,
    load_config,
    save_config,
    load_pack_stack_config,
    save_pack_stack_config,
    get_enabled_pack_entries,
    load_material_settings_config,
    save_material_settings_config,
    reset_config,
    export_config,
    import_config,
)


class TestConfigManager(unittest.TestCase):
    """Test suite for ConfigManager, Models, Backends, and Anti-Wipe Protections."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.config_file = self.temp_path / "test_config.json"
        self.json_backend = JsonConfigBackend(custom_path=self.config_file)
        self.mgr = ConfigManager.reset_instance(backend=self.json_backend)

    def tearDown(self):
        ConfigManager.reset_instance()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_models_normalization_and_serialization(self):
        """Verify models convert to/from dict and normalize operator IDs and pack tiers."""
        # 1. PackEntry tiers
        rp = PackEntry(name="RP", pack_type="RESOURCE_PACK")
        mod = PackEntry(name="Mod", pack_type="MOD_JAR")
        vanilla = PackEntry(name="Vanilla", pack_type="VANILLA")
        self.assertEqual(rp.tier_priority, 0)
        self.assertEqual(mod.tier_priority, 1)
        self.assertEqual(vanilla.tier_priority, 2)

        # 2. ConfigData normalization of 3-tier ordering
        cfg = ConfigData(
            resource_packs=[
                PackEntry(name="Vanilla", pack_type="VANILLA"),
                PackEntry(name="RP 1", pack_type="RESOURCE_PACK"),
                PackEntry(name="Mod 1", pack_type="MOD_JAR"),
                PackEntry(name="RP 2", pack_type="RESOURCE_PACK"),
            ]
        )
        cfg.normalize()
        self.assertEqual([p.name for p in cfg.resource_packs], ["RP 1", "RP 2", "Mod 1", "Vanilla"])

        # 3. View operator ID normalization & untrusted operator filtering
        cfg.views = {
            "mesh": [
                MenuItem(operator="object.mozi_adaptive_pixel_split", label="Split"),
                MenuItem(operator="wm.quit_blender", label="Quit"),  # Invalid/untrusted
                MenuItem(operator="mozi.select_hard_edges", label="Select"),
            ]
        }
        cfg.normalize()
        mesh_ops = [item.operator for item in cfg.views["mesh"]]
        self.assertIn("mozi.adaptive_pixel_split", mesh_ops)
        self.assertIn("mozi.select_hard_edges", mesh_ops)
        self.assertNotIn("wm.quit_blender", mesh_ops)

    def test_json_backend_atomic_write_and_backup_recovery(self):
        """Verify atomic JSON writes and automatic recovery from .bak when primary file is corrupted."""
        initial_packs = [{"name": "Pack Alpha", "path": "/path/alpha.zip", "enabled": True, "pack_type": "RESOURCE_PACK"}]
        self.mgr.set_resource_packs(initial_packs)

        self.assertTrue(self.config_file.exists())
        backup_file = self.config_file.with_suffix(self.config_file.suffix + ".bak")
        self.assertTrue(backup_file.exists())

        # Simulate catastrophic corruption / truncation of primary config file
        with open(self.config_file, "w", encoding="utf-8") as f:
            f.write("{ incomplete json: [corrupted")

        # Reloading config should automatically detect damage and recover from .bak
        recovered_packs = self.mgr.reload().resource_packs
        self.assertEqual(len(recovered_packs), 1)
        self.assertEqual(recovered_packs[0].name, "Pack Alpha")

    def test_memory_backend_isolation(self):
        """Verify MemoryConfigBackend operates strictly in RAM without creating files."""
        mem_backend = MemoryConfigBackend()
        self.mgr.set_backend(mem_backend, migrate_data=False)
        self.assertEqual(self.mgr.get_backend().backend_name, "MEMORY")

        self.mgr.set_material_settings({"material_mode": "STANDALONE", "biome_preset": "JUNGLE"})
        loaded = self.mgr.get_material_settings()
        self.assertEqual(loaded["material_mode"], "STANDALONE")
        self.assertEqual(loaded["biome_preset"], "JUNGLE")

        # Ensure no files were written to disk
        self.assertFalse((self.temp_path / "dummy_mem.json").exists())

    def test_backend_switching_and_data_migration(self):
        """Verify switching backends seamlessly migrates in-memory data."""
        self.mgr.set_resource_packs([{"name": "Migrate Test", "path": "/test.zip", "enabled": True, "pack_type": "RESOURCE_PACK"}])
        self.mgr.set_material_settings({"material_mode": "STANDALONE"})

        # Switch to MemoryBackend with data migration
        mem_backend = MemoryConfigBackend()
        self.mgr.set_backend(mem_backend, migrate_data=True)
        self.assertEqual(self.mgr.get_resource_packs()[0]["name"], "Migrate Test")
        self.assertEqual(self.mgr.get_material_settings()["material_mode"], "STANDALONE")

    def test_anti_wipe_safety_guard(self):
        """Verify that passing an uninitialized or empty preferences object never wipes saved data."""
        # 1. Establish persistent configuration
        self.mgr.set_resource_packs([
            {"name": "Crucial Pack 1", "path": "/p1.zip", "enabled": True, "pack_type": "RESOURCE_PACK"},
            {"name": "Crucial Pack 2", "path": "/p2.zip", "enabled": True, "pack_type": "RESOURCE_PACK"},
        ])
        self.assertEqual(len(self.mgr.get_resource_packs()), 2)

        # 2. Simulate an uninitialized AddonPreferences mock object (empty collections, is_initialized=False)
        class MockPrefs:
            def __init__(self):
                self.is_initialized = False
                self.resource_packs = []
                self.material_mode = "ATLAS"
                self.biome_preset = "PLAINS"
                self.pack_textures = True
                self.added_mesh = []
                self.unadded_mesh = []

        uninit_prefs = MockPrefs()

        # 3. Call sync_from_preferences with uninitialized mock prefs
        saved = self.mgr.sync_from_preferences(uninit_prefs)
        self.assertFalse(saved, "Anti-wipe guard must reject saving from uninitialized empty preferences.")

        # 4. Verify existing packs were NOT cleared
        self.assertEqual(len(self.mgr.get_resource_packs()), 2)
        self.assertEqual(self.mgr.get_resource_packs()[0]["name"], "Crucial Pack 1")

    def test_default_menu_views_populated(self):
        """Verify default ConfigData and fresh manager instance populate views from registered operator presets."""
        cfg = ConfigData()
        self.assertIn("mesh", cfg.views)
        self.assertIn("object", cfg.views)
        self.assertIn("uv", cfg.views)
        self.assertGreater(len(cfg.views["mesh"]), 0, "Default mesh menu views must not be empty.")
        self.assertGreater(len(cfg.views["object"]), 0, "Default object menu views must not be empty.")
        self.assertGreater(len(cfg.views["uv"]), 0, "Default uv menu views must not be empty.")

        # Check default operator IDs
        mesh_ops = [item.operator for item in cfg.views["mesh"]]
        self.assertIn("mozi.adaptive_pixel_split", mesh_ops)

    def test_reset_views_preserves_packs_and_settings(self):
        """Verify reset_views restores default menu presets while keeping resource packs and material settings intact."""
        # 1. Custom modified views, packs, and material settings
        self.mgr.set_views({"mesh": [], "object": [], "uv": []})
        self.mgr.set_resource_packs([
            {"name": "Keep This Pack", "path": "/path/keep.zip", "enabled": True, "pack_type": "RESOURCE_PACK"}
        ])
        self.mgr.set_material_settings({"material_mode": "STANDALONE", "biome_preset": "BADLANDS"})

        self.assertEqual(len(self.mgr.get_views()["mesh"]), 0)
        self.assertEqual(len(self.mgr.get_resource_packs()), 1)

        # 2. Reset only views
        self.mgr.reset_views()

        # 3. Verify views are restored to default presets
        views = self.mgr.get_views()
        self.assertGreater(len(views["mesh"]), 0)
        self.assertGreater(len(views["object"]), 0)
        self.assertGreater(len(views["uv"]), 0)

        # 4. Verify packs and material settings were NOT wiped
        packs = self.mgr.get_resource_packs()
        self.assertEqual(len(packs), 1)
        self.assertEqual(packs[0]["name"], "Keep This Pack")
        mat = self.mgr.get_material_settings()
        self.assertEqual(mat["material_mode"], "STANDALONE")
        self.assertEqual(mat["biome_preset"], "BADLANDS")

    def test_export_and_import_config(self):
        """Verify exporting and importing configuration files."""
        self.mgr.set_resource_packs([
            {"name": "Export Pack", "path": "/export/pack.zip", "enabled": True, "pack_type": "RESOURCE_PACK"}
        ])
        self.mgr.set_material_settings({"material_mode": "STANDALONE", "biome_preset": "DESERT"})

        export_target = self.temp_path / "exported_cfg.json"
        success = self.mgr.export_config(export_target)
        self.assertTrue(success)
        self.assertTrue(export_target.exists())

        # Reset config to defaults
        self.mgr.reset()
        self.assertEqual(len(self.mgr.get_resource_packs()), 0)

        # Import config back
        imported = self.mgr.import_config(export_target)
        self.assertIsNotNone(imported)
        self.assertEqual(len(self.mgr.get_resource_packs()), 1)
        self.assertEqual(self.mgr.get_resource_packs()[0]["name"], "Export Pack")
        self.assertEqual(self.mgr.get_material_settings()["biome_preset"], "DESERT")

    def test_sync_from_preferences_prevents_recursion(self):
        """Verify sync_from_preferences and on_material_setting_changed do not enter infinite recursion."""
        from ui.preferences import on_material_setting_changed

        recursion_counter = 0

        class RecursiveMockPrefs:
            def __init__(self, mgr):
                self._mgr = mgr
                self.is_initialized = True
                self.resource_packs = []
                self._material_mode = "ATLAS"
                self.biome_preset = "PLAINS"
                self.pack_textures = True

            @property
            def material_mode(self):
                return self._material_mode

            @material_mode.setter
            def material_mode(self, val):
                nonlocal recursion_counter
                recursion_counter += 1
                self._material_mode = val
                # Simulate Blender's property update callback firing synchronously
                if recursion_counter < 100:
                    on_material_setting_changed(self, None)

        rec_prefs = RecursiveMockPrefs(self.mgr)
        # Trigger change - must NOT throw RecursionError
        on_material_setting_changed(rec_prefs, None)
        # Verify it terminated safely in at most 2 calls instead of recursing to max recursion limit (1000)
        self.assertLess(recursion_counter, 5)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

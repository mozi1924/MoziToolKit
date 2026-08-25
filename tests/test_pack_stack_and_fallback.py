"""
Tests for Multi-layer Resource Pack Stack, Fallback Resolution, and Preferences UI/Config.
"""

import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image

import bpy
from utils.materials import (
    ZipResourcePack,
    ResourcePackStack,
    get_configured_pack_stack,
    AtlasGenerator,
)
from utils.system import (
    load_pack_stack_config,
    save_pack_stack_config,
    load_material_settings_config,
    save_material_settings_config,
    get_enabled_pack_entries,
    get_prefs,
)


class TestPackStackAndFallback(unittest.TestCase):
    def setUp(self):
        self.temp_dirs = []

    def tearDown(self):
        for td in self.temp_dirs:
            try:
                td.cleanup()
            except Exception:
                pass

    def _create_temp_pack(self, name: str, textures: dict[tuple[str, str], tuple[int, int, tuple[int, int, int, int]]]) -> Path:
        """
        Helper to create a temporary resource pack structure with textures.
        textures: {(namespace, texture_name): (width, height, (r, g, b, a))}
        """
        td = tempfile.TemporaryDirectory()
        self.temp_dirs.append(td)
        base = Path(td.name)

        # pack.mcmeta
        mcmeta = {"pack": {"pack_format": 15, "description": f"Test Pack {name}"}}
        (base / "pack.mcmeta").write_text(json.dumps(mcmeta), encoding="utf-8")

        for (ns, tex_name), (w, h, rgba) in textures.items():
            tex_dir = base / "assets" / ns / "textures" / "block"
            tex_dir.mkdir(parents=True, exist_ok=True)
            img = Image.new("RGBA", (w, h), rgba)
            img.save(tex_dir / f"{tex_name}.png")

        return base

    def test_pack_stack_priority_and_cascading_lookup(self):
        """Test that lookups cascade through packs from top to bottom."""
        # Base Pack: contains dirt (greenish) and stone (grey)
        base_path = self._create_temp_pack("Base", {
            ("minecraft", "dirt"): (16, 16, (100, 70, 30, 255)),
            ("minecraft", "stone"): (16, 16, (128, 128, 128, 255)),
        })
        # Custom PBR / Overlay Pack: contains custom stone (blueish), but no dirt
        custom_path = self._create_temp_pack("Custom", {
            ("minecraft", "stone"): (32, 32, (0, 0, 255, 255)),
        })

        stack = ResourcePackStack([custom_path, base_path])
        self.assertEqual(len(stack.packs), 2)

        # 1. 'stone' is in both custom and base -> must return custom pack's 32x32 texture
        stone_info = stack.get_texture_info("stone", "minecraft")
        self.assertIsNotNone(stone_info)
        stone_img = Image.open(stone_info["albedo"])
        self.assertEqual(stone_img.size, (32, 32))

        # 2. 'dirt' is missing from custom pack -> must fallback to base pack's 16x16 texture
        dirt_info = stack.get_texture_info("dirt", "minecraft")
        self.assertIsNotNone(dirt_info)
        dirt_img = Image.open(dirt_info["albedo"])
        self.assertEqual(dirt_img.size, (16, 16))

        # 3. 'bedrock' is in neither -> returns None
        bedrock_info = stack.get_texture_info("bedrock", "minecraft")
        self.assertIsNone(bedrock_info)

    def test_pack_stack_mod_namespace_support(self):
        """Test that mod JARs/packs with custom namespaces (e.g. 'create:') are indexed and isolated."""
        mod_path = self._create_temp_pack("CreateMod", {
            ("create", "cogwheel"): (16, 16, (200, 150, 50, 255)),
            ("create", "shaft"): (16, 16, (150, 150, 150, 255)),
        })
        vanilla_path = self._create_temp_pack("Vanilla", {
            ("minecraft", "dirt"): (16, 16, (100, 70, 30, 255)),
        })

        stack = ResourcePackStack([mod_path, vanilla_path])
        namespaces = stack.list_all_namespaces()

        self.assertIn("minecraft", namespaces)
        self.assertIn("create", namespaces)
        self.assertEqual(namespaces[0], "minecraft")  # 'minecraft' is canonical first

        cog_info = stack.get_texture_info("cogwheel", "create")
        self.assertIsNotNone(cog_info)
        self.assertEqual(cog_info["namespace"], "create")

    def test_atlas_generator_with_fallback_stack(self):
        """Test that AtlasGenerator seamlessly fills missing textures from fallback packs in stack and ignores items."""
        base_path = self._create_temp_pack("BaseVanilla", {
            ("minecraft", "dirt"): (16, 16, (100, 70, 30, 255)),
            ("minecraft", "oak_planks"): (16, 16, (180, 140, 90, 255)),
        })
        # Add item and entity textures to base pack to verify they are NEVER loaded into block atlas
        item_dir = base_path / "assets" / "minecraft" / "textures" / "item"
        item_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (16, 16), (0, 255, 255, 255)).save(item_dir / "diamond_sword.png")

        entity_dir = base_path / "assets" / "minecraft" / "textures" / "entity"
        entity_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (64, 64), (0, 200, 0, 255)).save(entity_dir / "creeper.png")

        custom_path = self._create_temp_pack("PartialPack", {
            ("minecraft", "dirt"): (32, 32, (120, 80, 40, 255)),
            # oak_planks missing in partial pack!
        })

        stack = ResourcePackStack([custom_path, base_path])
        gen = AtlasGenerator(custom_path, fallback_stack=stack)
        gen.load_resources()

        # Both dirt and oak_planks should be loaded into static textures
        self.assertIn("dirt", gen.static_textures)
        self.assertIn("oak_planks", gen.static_textures)

        # Item and entity textures must NEVER be in block atlas
        self.assertNotIn("diamond_sword", gen.static_textures)
        self.assertNotIn("creeper", gen.static_textures)

        # Dirt should come from PartialPack (32x32)
        self.assertEqual(gen.static_textures["dirt"].size, (32, 32))
        # Oak Planks should come from BaseVanilla fallback (16x16)
        self.assertEqual(gen.static_textures["oak_planks"].size, (16, 16))

    def test_pack_stack_config_persistence_and_operators(self):
        """Test saving, loading, and preference UI operators for resource pack stack."""
        # 1. Config save and load
        test_entries = [
            {"name": "HighRes Pack", "path": "/path/to/highres.zip", "enabled": True, "pack_type": "RESOURCE_PACK"},
            {"name": "Create Mod", "path": "/path/to/create.jar", "enabled": True, "pack_type": "MOD_JAR"},
            {"name": "Vanilla 1.21", "path": "/path/to/vanilla.jar", "enabled": False, "pack_type": "VANILLA"},
        ]
        save_pack_stack_config(test_entries)
        loaded = load_pack_stack_config()
        self.assertEqual(len(loaded), 3)
        self.assertEqual(loaded[0]["name"], "HighRes Pack")

        enabled = get_enabled_pack_entries()
        self.assertEqual(len(enabled), 2)  # 2 enabled entries

        # 2. Preferences UI operators
        prefs = get_prefs(bpy.context)
        if prefs is not None:
            prefs.resource_packs.clear()

            # Add pack
            res = bpy.ops.mozi.pack_add()
            self.assertIn("FINISHED", res)
            self.assertEqual(len(prefs.resource_packs), 1)

            # Add second pack
            bpy.ops.mozi.pack_add()
            self.assertEqual(len(prefs.resource_packs), 2)

            # Move second pack UP
            prefs.resource_packs_index = 1
            bpy.ops.mozi.pack_move(direction="UP")
            self.assertEqual(prefs.resource_packs_index, 0)

            # Remove pack
            bpy.ops.mozi.pack_remove()
            self.assertEqual(len(prefs.resource_packs), 1)

    def test_pack_stack_three_tier_hierarchy_and_operators(self):
        """Test strict 3-tier partitioning (RESOURCE_PACK -> MOD_JAR -> VANILLA) and move restrictions."""
        # 1. Test tier sorting when saving/loading config
        unsorted_entries = [
            {"name": "Vanilla 1.21", "path": "/path/vanilla.jar", "enabled": True, "pack_type": "VANILLA"},
            {"name": "Faithful 32x", "path": "/path/faithful.zip", "enabled": True, "pack_type": "RESOURCE_PACK"},
            {"name": "Create Mod", "path": "/path/create.jar", "enabled": True, "pack_type": "MOD_JAR"},
            {"name": "Glow Ores", "path": "/path/glow.zip", "enabled": True, "pack_type": "RESOURCE_PACK"},
        ]
        save_pack_stack_config(unsorted_entries)
        loaded = load_pack_stack_config()
        # Must be sorted into: [Faithful 32x, Glow Ores, Create Mod, Vanilla 1.21]
        self.assertEqual(loaded[0]["name"], "Faithful 32x")
        self.assertEqual(loaded[1]["name"], "Glow Ores")
        self.assertEqual(loaded[2]["name"], "Create Mod")
        self.assertEqual(loaded[3]["name"], "Vanilla 1.21")

        # 2. Test Preferences UI tier movement restrictions
        from ui.preferences import populate_resource_packs
        prefs = get_prefs(bpy.context)
        if prefs is not None:
            populate_resource_packs(prefs, loaded)

            # Try to move Vanilla (index 3) UP into MOD_JAR tier -> must be cancelled/prevented
            prefs.resource_packs_index = 3
            res = bpy.ops.mozi.pack_move(direction="UP")
            self.assertEqual(res, {"CANCELLED"})
            self.assertEqual(prefs.resource_packs_index, 3)

            # Try to move Create Mod (index 2) UP into RESOURCE_PACK tier -> must be cancelled/prevented
            prefs.resource_packs_index = 2
            res = bpy.ops.mozi.pack_move(direction="UP")
            self.assertEqual(res, {"CANCELLED"})
            self.assertEqual(prefs.resource_packs_index, 2)

            # Move Glow Ores (index 1) UP within RESOURCE_PACK tier -> succeeds!
            prefs.resource_packs_index = 1
            res = bpy.ops.mozi.pack_move(direction="UP")
            self.assertIn("FINISHED", res)
            self.assertEqual(prefs.resource_packs_index, 0)
            self.assertEqual(prefs.resource_packs[0].name, "Glow Ores")
            self.assertEqual(prefs.resource_packs[1].name, "Faithful 32x")

    def test_multi_layer_full_stack_cascading_simulation(self):
        """Simulate user scenario: Glow Ores (RP1) -> World PBR (RP2) -> Mod (MOD1) -> Vanilla Base (JAR)."""
        # Tier 0: Glow Ores overlay (only diamond ore)
        glow_path = self._create_temp_pack("GlowOres", {
            ("minecraft", "diamond_ore"): (16, 16, (0, 255, 255, 255)),
        })
        # Tier 1: World PBR / Faithful (stone & dirt)
        world_path = self._create_temp_pack("WorldPBR", {
            ("minecraft", "stone"): (32, 32, (128, 128, 128, 255)),
            ("minecraft", "dirt"): (32, 32, (100, 70, 30, 255)),
            ("minecraft", "diamond_ore"): (32, 32, (50, 50, 50, 255)),  # Overridden by Glow Ores
        })
        # Tier 2: Create Mod (create:cogwheel)
        mod_path = self._create_temp_pack("CreateMod", {
            ("create", "cogwheel"): (16, 16, (200, 150, 50, 255)),
        })
        # Tier 3: Vanilla Base (bedrock, oak_planks, etc.)
        vanilla_path = self._create_temp_pack("VanillaBase", {
            ("minecraft", "bedrock"): (16, 16, (20, 20, 20, 255)),
            ("minecraft", "oak_planks"): (16, 16, (180, 140, 90, 255)),
            ("minecraft", "stone"): (16, 16, (60, 60, 60, 255)),  # Overridden by World PBR
        })

        stack = ResourcePackStack([glow_path, world_path, mod_path, vanilla_path])

        # 1. Diamond Ore hits Glow Ores (16x16 cyan)
        dia_info = stack.get_texture_info("diamond_ore", "minecraft")
        self.assertIsNotNone(dia_info)
        dia_img = Image.open(dia_info["albedo"])
        self.assertEqual(dia_img.size, (16, 16))
        self.assertEqual(dia_img.getpixel((0, 0)), (0, 255, 255, 255))

        # 2. Stone hits World PBR (32x32)
        stone_info = stack.get_texture_info("stone", "minecraft")
        self.assertIsNotNone(stone_info)
        stone_img = Image.open(stone_info["albedo"])
        self.assertEqual(stone_img.size, (32, 32))

        # 3. Create Cogwheel hits Mod
        cog_info = stack.get_texture_info("cogwheel", "create")
        self.assertIsNotNone(cog_info)
        cog_img = Image.open(cog_info["albedo"])
        self.assertEqual(cog_img.size, (16, 16))

        # 4. Bedrock hits Vanilla Base
        bedrock_info = stack.get_texture_info("bedrock", "minecraft")
        self.assertIsNotNone(bedrock_info)
        bedrock_img = Image.open(bedrock_info["albedo"])
        self.assertEqual(bedrock_img.size, (16, 16))
        self.assertEqual(bedrock_img.getpixel((0, 0)), (20, 20, 20, 255))

    def test_material_settings_config_persistence(self):
        """Test saving and loading material replacement settings in config and preferences."""
        from utils.system import load_material_settings_config, save_material_settings_config

        settings = {
            "material_mode": "STANDALONE",
            "biome_preset": "TAIGA",
            "pack_textures": False,
        }
        save_material_settings_config(settings)
        loaded = load_material_settings_config()
        self.assertEqual(loaded["material_mode"], "STANDALONE")
        self.assertEqual(loaded["biome_preset"], "TAIGA")
        self.assertFalse(loaded["pack_textures"])

    def test_replace_material_operator_with_configured_stack(self):
        """Test that MOZI_OT_replace_material executes immediately with the configured preferences stack."""
        from utils.system import has_pillow
        if not has_pillow():
            self.skipTest("Pillow not installed")

        # Create a sample pack
        pack_path = self._create_temp_pack("TestPack", {
            ("minecraft", "stone"): (16, 16, (128, 128, 128, 255)),
        })

        # Configure in preferences stack
        pack_entries = [
            {"name": "Test Pack", "path": str(pack_path), "enabled": True, "pack_type": "RESOURCE_PACK"}
        ]
        save_pack_stack_config(pack_entries)
        save_material_settings_config({"material_mode": "ATLAS"})

        prefs = get_prefs(bpy.context)
        if prefs is not None:
            from ui.preferences import populate_resource_packs
            populate_resource_packs(prefs, pack_entries)
            prefs.material_mode = "ATLAS"

        # Create test object
        bpy.ops.mesh.primitive_cube_add()
        cube = bpy.context.active_object
        mat = bpy.data.materials.new(name="stone")
        cube.data.materials.append(mat)

        # Execute operator directly (no file dialog)
        res = bpy.ops.mozi.replace_material()
        self.assertEqual(res, {'FINISHED'})
        self.assertTrue(cube.material_slots[0].material.name.startswith("mtk:minecraft:blocks_chunk_"))

        # Clean up
        bpy.data.objects.remove(cube, do_unlink=True)

    def test_precompile_cache_operator_atlas_mode(self):
        """Test that MOZI_OT_precompile_cache in ATLAS mode compiles Atlas cache only."""
        from utils.system import has_pillow
        from utils.materials.pack.pack_stack import get_configured_pack_stack
        from ui.preferences import populate_resource_packs
        if not has_pillow():
            self.skipTest("Pillow not installed")

        pack_path = self._create_temp_pack("PrecompileAtlasTest", {
            ("minecraft", "dirt"): (16, 16, (100, 70, 30, 255)),
            ("minecraft", "stone"): (16, 16, (128, 128, 128, 255)),
        })

        pack_entries = [
            {"name": "Precompile Atlas Pack", "path": str(pack_path), "enabled": True, "pack_type": "RESOURCE_PACK"}
        ]
        save_pack_stack_config(pack_entries)
        save_material_settings_config({"material_mode": "ATLAS"})

        prefs = get_prefs(bpy.context)
        if prefs:
            populate_resource_packs(prefs, pack_entries)
            prefs.material_mode = "ATLAS"

        res = bpy.ops.mozi.precompile_cache()
        self.assertEqual(res, {'FINISHED'})

        stack = get_configured_pack_stack()
        self.assertTrue(stack.is_stack_baked(yefira_only=False))
        self.assertFalse(stack.is_standalone_baked())

    def test_precompile_cache_operator_standalone_mode(self):
        """Test that MOZI_OT_precompile_cache in STANDALONE mode compiles BOTH Atlas and Standalone caches."""
        from utils.system import has_pillow
        from utils.materials.pack.pack_stack import get_configured_pack_stack
        from ui.preferences import populate_resource_packs
        if not has_pillow():
            self.skipTest("Pillow not installed")

        pack_path = self._create_temp_pack("PrecompileStandaloneTest", {
            ("minecraft", "oak_planks"): (16, 16, (160, 120, 70, 255)),
            ("minecraft", "birch_planks"): (16, 16, (200, 190, 140, 255)),
        })

        pack_entries = [
            {"name": "Precompile Standalone Pack", "path": str(pack_path), "enabled": True, "pack_type": "RESOURCE_PACK"}
        ]
        save_pack_stack_config(pack_entries)
        save_material_settings_config({"material_mode": "STANDALONE"})

        prefs = get_prefs(bpy.context)
        if prefs:
            populate_resource_packs(prefs, pack_entries)
            prefs.material_mode = "STANDALONE"

        res = bpy.ops.mozi.precompile_cache()
        self.assertEqual(res, {'FINISHED'})

        stack = get_configured_pack_stack()
        self.assertTrue(stack.is_stack_baked(yefira_only=False))
        self.assertTrue(stack.is_standalone_baked())

    def test_persistent_cache_directory_and_stats(self):
        """Test that get_cache_dir is persistent, temp extraction is in OS temp, and obsolete stack caches are pruned."""
        from utils.materials.pack.resource_pack import (
            get_cache_dir,
            get_temp_extraction_dir,
            get_cache_stats,
            clean_obsolete_stack_caches,
        )

        cache_dir = get_cache_dir()
        self.assertTrue(cache_dir.exists())
        self.assertIn("baked_stack", str(cache_dir).lower())

        temp_ext_dir = get_temp_extraction_dir()
        self.assertTrue(temp_ext_dir.exists())

        # Test obsolete stack caches cleanup: only current stack hash remains
        dummy_old = cache_dir / "old_stack_hash_12345"
        dummy_old.mkdir(parents=True, exist_ok=True)
        (dummy_old / "dummy.png").write_bytes(b"123")

        dummy_current = cache_dir / "current_stack_hash_67890"
        dummy_current.mkdir(parents=True, exist_ok=True)
        (dummy_current / "atlas_mapping.json").write_text("{}", encoding="utf-8")

        dirs_removed, bytes_freed = clean_obsolete_stack_caches(current_stack_hash="current_stack_hash_67890")
        self.assertGreaterEqual(dirs_removed, 1)
        self.assertFalse(dummy_old.exists())
        self.assertTrue(dummy_current.exists())

        stats = get_cache_stats()
        self.assertIn("path", stats)
        self.assertIn("files_count", stats)
        self.assertIn("total_size_bytes", stats)
        self.assertIn("size_formatted", stats)
        self.assertEqual(stats["path"], cache_dir)


if __name__ == "__main__":
    unittest.main()



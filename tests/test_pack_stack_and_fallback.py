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
        """Test that AtlasGenerator seamlessly fills missing textures from fallback packs in stack."""
        base_path = self._create_temp_pack("BaseVanilla", {
            ("minecraft", "dirt"): (16, 16, (100, 70, 30, 255)),
            ("minecraft", "oak_planks"): (16, 16, (180, 140, 90, 255)),
        })
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


if __name__ == "__main__":
    unittest.main()

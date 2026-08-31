"""
Unit tests for unified resource pack model abstraction.
Verifies ZipResourcePack.get_all_models(), ResourcePackStack.get_all_models(),
and BiomeResolver.load_from_pack_stack() across directory, zip, and stack hierarchies.
"""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from utils.materials.pack import ZipResourcePack, ResourcePackStack
from utils.materials.biome import BiomeResolver


class TestPackModelAbstraction(unittest.TestCase):

    def test_directory_model_loading(self):
        """Test ZipResourcePack.get_all_models() on an unpacked directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pack_dir = Path(tmpdir) / "custom_pack"
            models_dir = pack_dir / "assets" / "minecraft" / "models" / "block"
            models_dir.mkdir(parents=True, exist_ok=True)

            model_data = {
                "parent": "minecraft:block/cube_all",
                "textures": {"all": "minecraft:block/stone"}
            }
            with open(models_dir / "stone.json", "w", encoding="utf-8") as f:
                json.dump(model_data, f)

            pack = ZipResourcePack(str(pack_dir))
            models = pack.get_all_models()

            self.assertIn("stone", models)
            self.assertEqual(models["stone"]["parent"], "minecraft:block/cube_all")

    def test_zip_model_loading_unextracted(self):
        """Test ZipResourcePack.get_all_models() directly on a .zip archive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "custom_pack.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                model_data = {
                    "parent": "minecraft:block/cube",
                    "textures": {"down": "minecraft:block/grass_block_bottom"}
                }
                zf.writestr("assets/minecraft/models/block/grass_block.json", json.dumps(model_data))
                item_data = {
                    "parent": "minecraft:item/generated",
                    "textures": {"layer0": "minecraft:item/stick"}
                }
                zf.writestr("assets/minecraft/models/item/stick.json", json.dumps(item_data))

            pack = ZipResourcePack(str(zip_path), use_cache=True, lazy=True)
            models = pack.get_all_models()

            self.assertIn("grass_block", models)
            self.assertIn("item/stick", models)
            self.assertEqual(models["grass_block"]["textures"]["down"], "minecraft:block/grass_block_bottom")

    def test_pack_stack_model_cascade_priority(self):
        """Test ResourcePackStack.get_all_models() cascade priority (top overrides bottom)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "base_pack"
            base_models = base_dir / "assets" / "minecraft" / "models" / "block"
            base_models.mkdir(parents=True, exist_ok=True)
            with open(base_models / "stone.json", "w", encoding="utf-8") as f:
                json.dump({"parent": "base_stone"}, f)
            with open(base_models / "dirt.json", "w", encoding="utf-8") as f:
                json.dump({"parent": "base_dirt"}, f)

            top_dir = Path(tmpdir) / "top_pack"
            top_models = top_dir / "assets" / "minecraft" / "models" / "block"
            top_models.mkdir(parents=True, exist_ok=True)
            with open(top_models / "stone.json", "w", encoding="utf-8") as f:
                json.dump({"parent": "top_stone_override"}, f)

            base_pack = ZipResourcePack(str(base_dir))
            top_pack = ZipResourcePack(str(top_dir))

            # Stack: top_pack (priority 0), base_pack (priority 1)
            stack = ResourcePackStack([top_pack, base_pack])
            merged_models = stack.get_all_models()

            self.assertEqual(merged_models["stone"]["parent"], "top_stone_override")
            self.assertEqual(merged_models["dirt"]["parent"], "base_dirt")

    def test_biome_resolver_integration(self):
        """Test BiomeResolver.load_from_pack_stack() loads models across stack."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pack_dir = Path(tmpdir) / "tint_pack"
            models_dir = pack_dir / "assets" / "minecraft" / "models" / "block"
            models_dir.mkdir(parents=True, exist_ok=True)
            model_data = {
                "parent": "minecraft:block/tinted_cross",
                "textures": {"cross": "minecraft:block/custom_foliage"}
            }
            with open(models_dir / "custom_foliage.json", "w", encoding="utf-8") as f:
                json.dump(model_data, f)

            pack = ZipResourcePack(str(pack_dir))
            stack = ResourcePackStack([pack])

            resolver = BiomeResolver()
            resolver.load_from_pack_stack(stack)

            self.assertIn("custom_foliage", resolver.models)
            self.assertEqual(resolver.models["custom_foliage"]["parent"], "minecraft:block/tinted_cross")


if __name__ == "__main__":
    unittest.main()

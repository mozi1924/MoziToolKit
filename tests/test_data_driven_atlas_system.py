"""
Comprehensive Unit Tests for Data-Driven Atlas System, Fallback Registry, and Palette Permutations.
"""

import io
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from utils.materials.atlas.definition import (
    AtlasDefinition,
    AtlasDefinitionParser,
    BuiltinAtlasRegistry,
    DirectoryAtlasSource,
    SingleAtlasSource,
    FilterAtlasSource,
    PalettedPermutationsAtlasSource,
)
from utils.materials.atlas.palette_baker import (
    PalettePermutationEngine,
    bake_paletted_permutation,
    _extract_palette_colors,
)
from utils.materials.atlas.generator import AtlasGenerator
from utils.materials.atlas.addressing import AtlasAddressResolver
from utils.materials.pack.pack_stack import ResourcePackStack


class TestDataDrivenAtlasSystem(unittest.TestCase):
    """Test data-driven atlas definitions, builtin fallback registry, and paletted permutations."""

    def test_builtin_fallback_registry_coverage(self):
        """Verify BuiltinAtlasRegistry contains all 14 standard Minecraft atlases."""
        atlases = BuiltinAtlasRegistry.get_default_atlases()
        self.assertGreaterEqual(len(atlases), 14)
        expected_keys = [
            "minecraft:blocks",
            "minecraft:items",
            "minecraft:armor_trims",
            "minecraft:chests",
            "minecraft:shulker_boxes",
            "minecraft:banner_patterns",
            "minecraft:shield_patterns",
            "minecraft:decorated_pot",
            "minecraft:paintings",
            "minecraft:particles",
            "minecraft:celestials",
            "minecraft:gui",
            "minecraft:map_decorations",
            "minecraft:entities",
        ]
        for k in expected_keys:
            self.assertIn(k, atlases, f"Expected default atlas '{k}' in BuiltinAtlasRegistry")

        # Check blocks atlas matching rules
        blocks = atlases["minecraft:blocks"]
        self.assertEqual(blocks.match_texture("block/stone.png", "minecraft"), "block/stone")
        self.assertEqual(blocks.match_texture("textures/block/oak_planks.png", "minecraft"), "block/oak_planks")
        self.assertEqual(blocks.match_texture("entity/conduit/conduit.png", "minecraft"), "entity/conduit/conduit")
        self.assertEqual(blocks.match_texture("entity/bell/bell_body.png", "minecraft"), "entity/bell/bell_body")

    def test_palette_baker_color_replacement(self):
        """Verify bake_paletted_permutation correctly swaps key palette colors for permutation colors."""
        # 1. Create a 2-color key palette (1x2): Black (0,0,0) and White (255,255,255)
        key_pal = Image.new("RGBA", (2, 1), (0, 0, 0, 0))
        key_pal.putpixel((0, 0), (255, 255, 255, 255))
        key_pal.putpixel((1, 0), (128, 128, 128, 255))

        # 2. Create diamond permutation palette (Cyan and Dark Cyan)
        perm_pal = Image.new("RGBA", (2, 1), (0, 0, 0, 0))
        perm_pal.putpixel((0, 0), (0, 255, 255, 255))
        perm_pal.putpixel((1, 0), (0, 128, 128, 255))

        # 3. Create a template texture with White and Gray pixels
        template = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
        template.putpixel((0, 0), (255, 255, 255, 255)) # should become (0, 255, 255)
        template.putpixel((1, 1), (128, 128, 128, 255)) # should become (0, 128, 128)

        baked = bake_paletted_permutation(template, key_pal, perm_pal)
        self.assertIsNotNone(baked)
        self.assertEqual(baked.getpixel((0, 0)), (0, 255, 255, 255))
        self.assertEqual(baked.getpixel((1, 1)), (0, 128, 128, 255))
        self.assertEqual(baked.getpixel((1, 0)), (0, 0, 0, 0))

    def test_atlas_definition_parser_with_custom_and_fallback(self):
        """Verify AtlasDefinitionParser parses atlas JSONs and merges with builtin defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pack_dir = Path(tmpdir) / "custom_pack"
            atlases_dir = pack_dir / "assets" / "minecraft" / "atlases"
            atlases_dir.mkdir(parents=True, exist_ok=True)

            # Custom blocks.json
            custom_blocks = {
                "sources": [
                    {"type": "minecraft:directory", "source": "custom_blocks", "prefix": "cblock/"}
                ]
            }
            (atlases_dir / "blocks.json").write_text(json.dumps(custom_blocks), encoding="utf-8")

            stack = ResourcePackStack([pack_dir])
            parsed = AtlasDefinitionParser.load_from_pack_stack(stack)

            self.assertIn("minecraft:blocks", parsed)
            blocks_def = parsed["minecraft:blocks"]
            self.assertEqual(blocks_def.match_texture("custom_blocks/ruby_ore.png"), "cblock/ruby_ore")

            # Non-overridden atlases should still fall back to built-ins
            self.assertIn("minecraft:chests", parsed)
            self.assertEqual(parsed["minecraft:chests"].match_texture("entity/chest/normal.png"), "entity/chest/normal")

    def test_atlas_generator_modern_metadata_and_backward_compatibility(self):
        """Verify AtlasGenerator outputs both modern atlas fields and backward compatible fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pack_dir = Path(tmpdir) / "dummy_pack"
            tex_dir = pack_dir / "assets" / "minecraft" / "textures" / "block"
            tex_dir.mkdir(parents=True, exist_ok=True)

            # Create dummy 16x16 stone texture
            stone_img = Image.new("RGBA", (16, 16), (128, 128, 128, 255))
            stone_img.save(tex_dir / "stone.png")

            # Create dummy chest texture
            chest_dir = pack_dir / "assets" / "minecraft" / "textures" / "entity" / "chest"
            chest_dir.mkdir(parents=True, exist_ok=True)
            chest_img = Image.new("RGBA", (64, 64), (180, 100, 40, 255))
            chest_img.save(chest_dir / "normal.png")

            out_dir = Path(tmpdir) / "atlas_out"
            generator = AtlasGenerator(resource_path=pack_dir)
            result = generator.build(out_dir)

            mapping_path = out_dir / "atlas_mapping.json"
            self.assertTrue(mapping_path.exists())

            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            self.assertIn("chunks", mapping)
            self.assertIn("textures", mapping)

            # Check modern & legacy metadata on chunks
            for chunk in mapping["chunks"]:
                self.assertIn("chunk_id", chunk)
                self.assertIn("atlas_id", chunk)
                self.assertIn("page_index", chunk)
                self.assertIn("page_kind", chunk)

            # Check modern & legacy metadata on locations
            stone_loc = mapping["textures"].get("minecraft:block/stone") or mapping["textures"].get("stone")
            self.assertIsNotNone(stone_loc)
            self.assertEqual(stone_loc["atlas_id"], "minecraft:blocks")
            self.assertEqual(stone_loc["page_kind"], "static")
            self.assertIn("chunk_id", stone_loc)
            self.assertIn("tile_column", stone_loc)

            # Verify AtlasAddressResolver can resolve stone location effortlessly
            resolver = AtlasAddressResolver(mapping)
            loc = resolver.lookup_texture("stone")
            self.assertIsNotNone(loc)
            self.assertEqual(loc["texture_key"], "minecraft:block/stone")
            self.assertEqual(loc["atlas_id"], "minecraft:blocks")
            self.assertEqual(loc["page_kind"], "static")

    def test_vanilla_fabric_jar_atlas_and_trims(self):
        """Test parsing and atlas classification against real Minecraft Fabric JAR if present."""
        jar_path = Path("/Users/jaxlocke/26.2-Fabric.jar")
        if not jar_path.exists():
            self.skipTest(f"Vanilla JAR not present at {jar_path}")

        stack = ResourcePackStack([jar_path])
        atlases = AtlasDefinitionParser.load_from_pack_stack(stack)
        self.assertIn("minecraft:blocks", atlases)
        self.assertIn("minecraft:items", atlases)
        self.assertIn("minecraft:armor_trims", atlases)

        # Check armor trims paletted permutation source
        trims_atlas = atlases["minecraft:armor_trims"]
        perm_sources = [s for s in trims_atlas.sources if isinstance(s, PalettedPermutationsAtlasSource)]
        self.assertGreater(len(perm_sources), 0)
        p_src = perm_sources[0]
        self.assertIn("amethyst", p_src.permutations)
        self.assertIn("diamond", p_src.permutations)
        self.assertIn("resin", p_src.permutations)


if __name__ == "__main__":
    unittest.main()

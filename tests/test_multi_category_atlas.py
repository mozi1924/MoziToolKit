"""
Tests for multi-category Minecraft texture atlas construction, chunk partitioning,
material binding, and pack fallback stack.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from PIL import Image

import bpy

# Bootstrap MoziToolKit package (also activates the isolated test sandbox)
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from utils.materials.constants import (
    ATLAS_CATEGORY_BLOCKS,
    ATLAS_CATEGORY_ITEMS,
    ATLAS_CATEGORY_PARTICLES,
    ATLAS_CATEGORY_PAINTINGS,
    ATLAS_CATEGORY_ARMOR_TRIMS,
    ATLAS_CATEGORY_CHEST,
    ATLAS_CATEGORY_SHULKER_BOXES,
    ATLAS_CATEGORY_SHIELD_PATTERNS,
    ATLAS_CATEGORY_BANNER_PATTERNS,
    ATLAS_CATEGORY_DECORATED_POT,
    ATLAS_CATEGORY_CELESTIALS,
    ATLAS_CATEGORY_GUI,
    ATLAS_CATEGORY_MAP_DECORATIONS,
    ATLAS_CATEGORY_ENTITIES,
    ATLAS_CATEGORY_MISC,
    PROP_ATLAS_CHUNK_CATEGORY,
    PROP_ATLAS_CHUNK_ID,
    PROP_ATLAS_CHUNK_KIND,
    classify_texture_category,
)
from utils.materials.atlas.generator import AtlasGenerator
from utils.materials.atlas.builder import build_atlas_chunk_materials
from utils.materials.pack.pack_stack import ResourcePackStack


class TestMultiCategoryAtlas(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_classify_texture_category(self):
        """Test category classification for standard and specialized Minecraft texture paths."""
        self.assertEqual(classify_texture_category("block/stone"), ATLAS_CATEGORY_BLOCKS)
        self.assertEqual(classify_texture_category("textures/block/dirt.png"), ATLAS_CATEGORY_BLOCKS)
        self.assertEqual(classify_texture_category("item/diamond_sword"), ATLAS_CATEGORY_ITEMS)
        self.assertEqual(classify_texture_category("textures/item/apple.png"), ATLAS_CATEGORY_ITEMS)
        self.assertEqual(classify_texture_category("particle/flame"), ATLAS_CATEGORY_PARTICLES)
        self.assertEqual(classify_texture_category("painting/kebab"), ATLAS_CATEGORY_PAINTINGS)
        self.assertEqual(classify_texture_category("trims/items/chestplate_trim_silence"), ATLAS_CATEGORY_ARMOR_TRIMS)
        self.assertEqual(classify_texture_category("entity/chest/normal"), ATLAS_CATEGORY_CHEST)
        self.assertEqual(classify_texture_category("entity/shulker/shulker"), ATLAS_CATEGORY_SHULKER_BOXES)
        self.assertEqual(classify_texture_category("entity/shield/shield_base"), ATLAS_CATEGORY_SHIELD_PATTERNS)
        self.assertEqual(classify_texture_category("entity/banner/base"), ATLAS_CATEGORY_BANNER_PATTERNS)
        self.assertEqual(classify_texture_category("entity/decorated_pot/pot"), ATLAS_CATEGORY_DECORATED_POT)
        self.assertEqual(classify_texture_category("environment/sun"), ATLAS_CATEGORY_CELESTIALS)
        self.assertEqual(classify_texture_category("gui/widgets"), ATLAS_CATEGORY_GUI)
        self.assertEqual(classify_texture_category("map/map_icons"), ATLAS_CATEGORY_MAP_DECORATIONS)
        self.assertEqual(classify_texture_category("entity/creeper/creeper"), ATLAS_CATEGORY_ENTITIES)
        self.assertEqual(classify_texture_category("models/armor/diamond_layer_1"), ATLAS_CATEGORY_ENTITIES)
        self.assertEqual(classify_texture_category("misc/unknown_tex"), ATLAS_CATEGORY_MISC)

    def _create_sample_pack(self, name: str, texture_specs: dict[str, tuple[int, int, tuple[int, int, int, int]]]) -> Path:
        """Create a mock resource pack directory with various texture categories."""
        pack_dir = self.work_dir / name
        assets_dir = pack_dir / "assets" / "minecraft" / "textures"

        for rel_path, (w, h, color) in texture_specs.items():
            img_path = assets_dir / f"{rel_path}.png"
            img_path.parent.mkdir(parents=True, exist_ok=True)
            img = Image.new("RGBA", (w, h), color)
            img.save(img_path)

        return pack_dir

    def test_multi_category_chunk_partitioning(self):
        """Verify that blocks, items, entities, and animated textures are cleanly partitioned into distinct chunks."""
        pack_path = self._create_sample_pack("CategoryPack", {
            "block/stone": (16, 16, (128, 128, 128, 255)),
            "block/dirt": (16, 16, (100, 60, 20, 255)),
            "item/diamond_sword": (16, 16, (0, 255, 255, 255)),
            "item/golden_apple": (16, 16, (255, 215, 0, 255)),
            "entity/creeper/creeper": (64, 64, (0, 200, 0, 255)),
            "particle/flame": (8, 8, (255, 100, 0, 255)),
        })

        # Add an animated item texture with .mcmeta
        compass_dir = pack_path / "assets" / "minecraft" / "textures" / "item"
        Image.new("RGBA", (16, 64), (200, 200, 200, 255)).save(compass_dir / "compass.png")
        with open(compass_dir / "compass.png.mcmeta", "w", encoding="utf-8") as f:
            json.dump({"animation": {"frametime": 2, "interpolate": True}}, f)

        atlas_out = self.work_dir / "atlas_out"
        gen = AtlasGenerator(pack_path, default_tile_size=16, max_chunk_size=512)
        outputs = gen.build(atlas_out)

        mapping_path = atlas_out / "atlas_mapping.json"
        self.assertTrue(mapping_path.exists())

        with open(mapping_path, "r", encoding="utf-8") as f:
            mapping = json.load(f)

        chunks = mapping["chunks"]
        self.assertGreaterEqual(len(chunks), 4)

        categories_in_chunks = {c["category"] for c in chunks}
        self.assertIn("blocks", categories_in_chunks)
        self.assertIn("items", categories_in_chunks)
        self.assertIn("entities", categories_in_chunks)
        self.assertIn("particles", categories_in_chunks)

        # Check that block chunk contains stone & dirt
        block_chunk = next(c for c in chunks if c["category"] == "blocks")
        self.assertEqual(block_chunk["kind"], "static")

        # Check that item static chunk contains diamond_sword & golden_apple
        item_static_chunk = next(c for c in chunks if c["category"] == "items" and c["kind"] == "static")
        self.assertEqual(item_static_chunk["texture_count"], 2)

        # Check that item animated chunk contains compass
        item_anim_chunk = next(c for c in chunks if c["category"] == "items" and c["kind"] == "animation")
        self.assertEqual(item_anim_chunk["texture_count"], 1)

        # Verify lookups in textures map
        textures = mapping["textures"]
        self.assertIn("minecraft:item/diamond_sword", textures)
        self.assertIn("item/diamond_sword", textures)
        self.assertIn("item_diamond_sword", textures)
        self.assertEqual(textures["minecraft:item/diamond_sword"]["category"], "items")
        self.assertEqual(textures["minecraft:item/diamond_sword"]["chunk_id"], item_static_chunk["chunk_id"])

        self.assertIn("minecraft:item/compass", textures)
        self.assertEqual(textures["minecraft:item/compass"]["category"], "items")
        self.assertEqual(textures["minecraft:item/compass"]["chunk_id"], item_anim_chunk["chunk_id"])

    def test_included_categories_skips_ui_and_particle_images(self):
        """A focused world atlas must not decode or emit unrelated UI chunks."""
        pack_path = self._create_sample_pack("WorldOnlyPack", {
            "block/stone": (16, 16, (128, 128, 128, 255)),
            "particle/flame": (8, 8, (255, 100, 0, 255)),
            "gui/widgets": (256, 256, (0, 0, 0, 255)),
        })
        atlas_out = self.work_dir / "world_only_atlas"
        gen = AtlasGenerator(
            pack_path,
            default_tile_size=16,
            max_chunk_size=512,
            included_categories={ATLAS_CATEGORY_BLOCKS},
        )
        outputs = gen.build(atlas_out)

        with open(outputs["mapping"], "r", encoding="utf-8") as f:
            mapping = json.load(f)
        self.assertEqual({chunk["category"] for chunk in mapping["chunks"]}, {ATLAS_CATEGORY_BLOCKS})
        self.assertIn("stone", mapping["textures"])
        self.assertNotIn("flame", mapping["textures"])
        self.assertNotIn("widgets", mapping["textures"])

    def test_build_atlas_chunk_materials_sets_category_prop(self):
        """Verify build_atlas_chunk_materials assigns PROP_ATLAS_CHUNK_CATEGORY on material datablocks."""
        pack_path = self._create_sample_pack("PropsPack", {
            "block/stone": (16, 16, (128, 128, 128, 255)),
            "item/diamond_sword": (16, 16, (0, 255, 255, 255)),
        })

        atlas_out = self.work_dir / "atlas_props_out"
        gen = AtlasGenerator(pack_path, default_tile_size=16, max_chunk_size=512)
        gen.build(atlas_out)

        materials = build_atlas_chunk_materials(atlas_out, pack_hash="test_hash_123456")
        self.assertGreaterEqual(len(materials), 2)

        categories = set()
        material_names = set()
        for chunk_id, mat in materials.items():
            self.assertIn(PROP_ATLAS_CHUNK_CATEGORY, mat)
            self.assertIn(PROP_ATLAS_CHUNK_ID, mat)
            self.assertIn(PROP_ATLAS_CHUNK_KIND, mat)
            categories.add(mat[PROP_ATLAS_CHUNK_CATEGORY])
            material_names.add(mat.name)

        self.assertIn("blocks", categories)
        self.assertIn("items", categories)

        # Verify material naming contains category prefix and 1-based category chunk index
        self.assertTrue(any("blocks_chunk_001" in name for name in material_names))
        self.assertTrue(any("items_chunk_001" in name for name in material_names))

        # Verify generated PNG filenames contain category prefix and category chunk index
        self.assertTrue((atlas_out / "blocks_chunk_001_albedo.png").exists())
        self.assertTrue((atlas_out / "items_chunk_001_albedo.png").exists())

    def test_chunk_capacity_splitting_per_category(self):
        """Verify that when a category exceeds chunk capacity, it splits into multiple chunks of that category."""
        # Max chunk size = 32px, tile size = 16px -> 2x2 = 4 tiles capacity per chunk
        pack_specs = {f"item/sword_{i}": (16, 16, (i * 10, i * 10, i * 10, 255)) for i in range(10)}
        pack_specs["block/stone"] = (16, 16, (128, 128, 128, 255))

        pack_path = self._create_sample_pack("CapacitySplitPack", pack_specs)
        atlas_out = self.work_dir / "atlas_split_out"
        gen = AtlasGenerator(pack_path, default_tile_size=16, max_chunk_size=32)
        gen.build(atlas_out)

        with open(atlas_out / "atlas_mapping.json", "r", encoding="utf-8") as f:
            mapping = json.load(f)

        item_chunks = [c for c in mapping["chunks"] if c["category"] == "items"]
        # 10 items with capacity 4 -> 3 item chunks (4 + 4 + 2)
        self.assertEqual(len(item_chunks), 3)
        self.assertEqual([c["category_chunk_index"] for c in item_chunks], [1, 2, 3])
        self.assertTrue((atlas_out / "items_chunk_001_albedo.png").exists())
        self.assertTrue((atlas_out / "items_chunk_002_albedo.png").exists())
        self.assertTrue((atlas_out / "items_chunk_003_albedo.png").exists())

        block_chunks = [c for c in mapping["chunks"] if c["category"] == "blocks"]
        self.assertEqual(len(block_chunks), 1)
        self.assertEqual(block_chunks[0]["category_chunk_index"], 1)
        self.assertTrue((atlas_out / "blocks_chunk_001_albedo.png").exists())

    def test_multi_category_fallback_stack(self):
        """Verify prioritized fallback loading across categories from lower-priority packs."""
        base_path = self._create_sample_pack("BaseVanilla", {
            "block/stone": (16, 16, (128, 128, 128, 255)),
            "item/diamond_sword": (16, 16, (0, 255, 255, 255)),
            "particle/flame": (8, 8, (255, 100, 0, 255)),
        })

        custom_path = self._create_sample_pack("CustomPack", {
            # Only overrides stone and diamond sword with 32x32 high res
            "block/stone": (32, 32, (100, 100, 100, 255)),
            "item/diamond_sword": (32, 32, (0, 200, 200, 255)),
            # flame is missing in CustomPack
        })

        stack = ResourcePackStack([custom_path, base_path])
        atlas_out = self.work_dir / "atlas_fallback_out"
        gen = AtlasGenerator(custom_path, default_tile_size=16, max_chunk_size=512, fallback_stack=stack)
        gen.build(atlas_out)

        with open(atlas_out / "atlas_mapping.json", "r", encoding="utf-8") as f:
            mapping = json.load(f)

        textures = mapping["textures"]
        self.assertIn("minecraft:block/stone", textures)
        self.assertIn("minecraft:item/diamond_sword", textures)
        self.assertIn("minecraft:particle/flame", textures)

        self.assertEqual(textures["minecraft:block/stone"]["tile_size"], 32)
        self.assertEqual(textures["minecraft:item/diamond_sword"]["tile_size"], 32)
        self.assertEqual(textures["minecraft:particle/flame"]["tile_size"], 8)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

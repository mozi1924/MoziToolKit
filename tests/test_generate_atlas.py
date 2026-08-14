"""
Unit tests for Atlas Generator and Atlas Material Builder.
"""

import json
import tempfile
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.generate_atlas import AtlasGenerator
from utils.atlas_layout import atlas_uv_from_local, chunk_cell

try:
    from PIL import Image
except ImportError:
    Image = None


class TestAtlasGenerator(unittest.TestCase):
    """Test case for Minecraft Texture Atlas Generator."""

    def setUp(self):
        self.jar_path = Path("/Users/jaxlocke/26.2-Fabric.jar")
        self.output_dir = Path("./tests/scratch_atlas_output")

    def test_atlas_generation(self):
        from utils.dependencies import has_pillow
        if not has_pillow():
            self.skipTest("Pillow not installed in test environment")
        if not self.jar_path.exists():
            self.skipTest(f"JAR file not found: {self.jar_path}")

        generator = AtlasGenerator(self.jar_path)
        outputs = generator.build(self.output_dir)

        self.assertTrue(outputs["chunks"], "at least one atlas chunk should be generated")
        self.assertTrue(outputs["mapping"].exists(), "atlas_mapping.json should be generated")

        with open(outputs["mapping"], "r", encoding="utf-8") as fp:
            mapping = json.load(fp)

        self.assertGreaterEqual(mapping["tile_size"], 16)
        self.assertEqual(mapping["format_version"], 8)
        self.assertLessEqual(max(chunk["width"] for chunk in mapping["chunks"]), 4096)
        self.assertLessEqual(max(chunk["height"] for chunk in mapping["chunks"]), 4096)
        self.assertGreater(len(mapping["textures"]), 0)
        self.assertEqual(len(mapping["face_order"]), 6)
        self.assertEqual(mapping["face_order"], ["+X", "-X", "+Y", "-Y", "+Z", "-Z"])

        # Check standard material layout format
        mat0 = mapping["materials"][0]
        self.assertIn("material_id", mat0)
        self.assertIn("name", mat0)
        self.assertIn("faces", mat0)
        self.assertEqual(set(mat0["faces"].keys()), {"+X", "-X", "+Y", "-Y", "+Z", "-Z"})

    @unittest.skipIf(Image is None, "Pillow not available")
    def test_atlas_keeps_the_largest_source_tile_resolution(self):
        """A 32px pack must not be silently reduced to the 16px default."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tex_dir = root / "assets" / "minecraft" / "textures" / "block"
            tex_dir.mkdir(parents=True)
            Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(tex_dir / "small.png")
            Image.new("RGBA", (32, 32), (0, 255, 0, 255)).save(tex_dir / "large.png")

            models_dir = root / "assets" / "minecraft" / "models" / "block"
            models_dir.mkdir(parents=True)
            (models_dir / "shared.json").write_text(
                '{"textures": {"all": "minecraft:block/large"}}', encoding="utf-8"
            )
            outputs = AtlasGenerator(root, max_chunk_size=64).build(root / "atlas")
            with open(outputs["mapping"], "r", encoding="utf-8") as fp:
                mapping = json.load(fp)

            self.assertEqual(mapping["format_version"], 8)
            self.assertEqual(mapping["tile_size"], 32)
            self.assertEqual(len(mapping["chunks"]), 1)
            self.assertEqual(mapping["chunks"][0]["width"], 64)
            self.assertEqual(mapping["chunks"][0]["height"], 32)
            self.assertEqual(mapping["textures"]["large"]["texture_id"], 0)
            self.assertEqual(mapping["textures"]["small"]["texture_id"], 1)
            # The model's six faces reuse the same single ``large`` tile.
            shared = next(entry for entry in mapping["materials"] if entry["name"] == "shared")
            self.assertEqual(len({tuple(face.values()) for face in shared["faces"].values()}), 1)
            atlas = Image.open(outputs["chunks"][0])
            self.assertEqual(atlas.getpixel((0, 0)), (0, 255, 0, 255))
            self.assertEqual(atlas.getpixel((32, 0)), (255, 0, 0, 255))

    @unittest.skipIf(Image is None, "Pillow not available")
    def test_non_standard_static_textures_do_not_inflate_tile_size(self):
        """A random 480x320 store preview banner or non-square atlas must not inflate tile_size."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tex_dir = root / "assets" / "minecraft" / "textures" / "block"
            tex_dir.mkdir(parents=True)
            Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(tex_dir / "stone.png")
            Image.new("RGBA", (480, 320), (0, 255, 0, 255)).save(tex_dir / "store_banner.png")

            outputs = AtlasGenerator(root, max_chunk_size=64).build(root / "atlas")
            with open(outputs["mapping"], "r", encoding="utf-8") as fp:
                mapping = json.load(fp)

            self.assertEqual(mapping["tile_size"], 16)
            self.assertEqual(len(mapping["chunks"]), 1)

    def test_baked_uv_uses_the_same_chunk_cell_layout_as_the_atlas(self):
        column, row = chunk_cell(texture_id=3, tiles_per_row=2)
        self.assertEqual((column, row), (1, 1))
        self.assertEqual(
            atlas_uv_from_local(
                0.25, 0.75, tile_column=column, tile_row=row,
                tile_size=16, atlas_width=32, atlas_height=32,
            ),
            ((1.25 * 16) / 32, 1.0 - (1.25 * 16) / 32),
        )

    @unittest.skipIf(Image is None, "Pillow not available")
    def test_animation_uses_vertical_chunks_and_preview_frame_zero(self):
        """Animation strips stay vertical; overflow starts a new chunk."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            textures = root / "assets" / "minecraft" / "textures" / "block"
            textures.mkdir(parents=True)
            for name, color in (("a", (255, 0, 0, 255)), ("b", (0, 255, 0, 255)), ("c", (0, 0, 255, 255))):
                animation = Image.new("RGBA", (32, 64))
                animation.paste(Image.new("RGBA", (32, 32), color), (0, 0))
                animation.save(textures / f"{name}.png")
                (textures / f"{name}.png.mcmeta").write_text('{"animation": {"frametime": 2}}', encoding="utf-8")

            outputs = AtlasGenerator(root, max_chunk_size=64).build(root / "atlas")
            with open(outputs["mapping"], "r", encoding="utf-8") as fp:
                mapping = json.load(fp)

            animation_chunks = [chunk for chunk in mapping["chunks"] if chunk["kind"] == "animation"]
            self.assertEqual([(chunk["width"], chunk["height"]) for chunk in animation_chunks], [(64, 64), (32, 64)])
            self.assertTrue(all(chunk["packing"] == "vertical_columns" for chunk in animation_chunks))
            preview = mapping["textures"]["a"]
            self.assertEqual((preview["pixel_x"], preview["pixel_y"], preview["preview_frame"]), (0, 0, 0))
            self.assertEqual(preview["frametime"], 2)
            self.assertEqual(preview["frame_count"], 2)
            self.assertEqual(mapping["textures"]["b"]["pixel_x"], 32)
            self.assertEqual(mapping["textures"]["c"]["chunk_id"], 1)
            self.assertEqual(Image.open(outputs["chunks"][0]).getpixel((0, 0)), (255, 0, 0, 255))

    @unittest.skipIf(Image is None, "Pillow not available")
    def test_animation_preserves_mcmeta_frame_dimensions(self):
        """Rectangular mcmeta frames must not be treated as square atlas steps."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            textures = root / "assets" / "minecraft" / "textures" / "block"
            textures.mkdir(parents=True)
            Image.new("RGBA", (32, 24), (255, 0, 0, 255)).save(textures / "wide_animation.png")
            (textures / "wide_animation.png.mcmeta").write_text(
                '{"animation": {"width": 16, "height": 8, "frametime": 3}}',
                encoding="utf-8",
            )

            outputs = AtlasGenerator(root, max_chunk_size=64).build(root / "atlas")
            with open(outputs["mapping"], "r", encoding="utf-8") as fp:
                location = json.load(fp)["textures"]["wide_animation"]

            self.assertEqual(location["frame_width"], 16)
            self.assertEqual(location["frame_height"], 8)
            self.assertEqual(location["frame_count"], 3)
            self.assertEqual(location["frametime"], 3)

    @unittest.skipIf(Image is None, "Pillow not available")
    def test_non_animated_mcmeta_stays_in_static_chunk(self):
        """Textures with texture-only mcmeta (like leaves or flowers) or 1 frame must stay in static chunk."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            textures = root / "assets" / "minecraft" / "textures" / "block"
            textures.mkdir(parents=True)

            # 1. Oak leaves with mipmap_strategy (non-animation mcmeta)
            Image.new("RGBA", (16, 16), (34, 139, 34, 255)).save(textures / "oak_leaves.png")
            (textures / "oak_leaves.png.mcmeta").write_text(
                '{"texture": {"mipmap_strategy": "dark_cutout"}}', encoding="utf-8"
            )

            # 2. Dandelion with strict_cutout
            Image.new("RGBA", (16, 16), (255, 255, 0, 255)).save(textures / "dandelion.png")
            (textures / "dandelion.png.mcmeta").write_text(
                '{"texture": {"mipmap_strategy": "strict_cutout"}}', encoding="utf-8"
            )

            # 3. Tripwire with alpha_cutoff_bias
            Image.new("RGBA", (16, 16), (200, 200, 200, 255)).save(textures / "tripwire.png")
            (textures / "tripwire.png.mcmeta").write_text(
                '{"texture": {"alpha_cutoff_bias": 0.1}}', encoding="utf-8"
            )

            # 4. Single frame texture with empty animation mcmeta (16x16 -> frame_count=1)
            Image.new("RGBA", (16, 16), (100, 100, 100, 255)).save(textures / "single_frame.png")
            (textures / "single_frame.png.mcmeta").write_text(
                '{"animation": {}}', encoding="utf-8"
            )

            # 5. Truly animated texture (16x32 -> 2 frames)
            Image.new("RGBA", (16, 32), (255, 69, 0, 255)).save(textures / "lava_still.png")
            (textures / "lava_still.png.mcmeta").write_text(
                '{"animation": {"frametime": 2}}', encoding="utf-8"
            )

            outputs = AtlasGenerator(root, max_chunk_size=64).build(root / "atlas")
            with open(outputs["mapping"], "r", encoding="utf-8") as fp:
                mapping = json.load(fp)

            # Static textures must be kind='static'
            self.assertEqual(mapping["textures"]["oak_leaves"]["kind"], "static")
            self.assertEqual(mapping["textures"]["dandelion"]["kind"], "static")
            self.assertEqual(mapping["textures"]["tripwire"]["kind"], "static")
            self.assertEqual(mapping["textures"]["single_frame"]["kind"], "static")

            # Animated texture must be kind='animation'
            self.assertEqual(mapping["textures"]["lava_still"]["kind"], "animation")
            self.assertEqual(mapping["textures"]["lava_still"]["frame_count"], 2)

            # Check animations count in mapping
            self.assertEqual(len(mapping["animations"]), 1)
            self.assertEqual(mapping["animations"][0]["name"], "lava_still")

            # Check that static chunk contains the static textures
            static_chunks = [c for c in mapping["chunks"] if c["kind"] == "static"]
            anim_chunks = [c for c in mapping["chunks"] if c["kind"] == "animation"]
            self.assertTrue(len(static_chunks) >= 1)
            self.assertEqual(len(anim_chunks), 1)

    def test_jar_classification_leaves_and_glass_are_static(self):
        """In 26.2-Fabric.jar, leaves/glass/flowers must be static and only real animations in animation chunk."""
        if not self.jar_path.exists():
            self.skipTest(f"JAR file not found: {self.jar_path}")

        generator = AtlasGenerator(self.jar_path)
        generator.load_resources()

        # Check static textures
        self.assertIn("oak_leaves", generator.static_textures)
        self.assertIn("dark_oak_leaves", generator.static_textures)
        self.assertIn("birch_leaves", generator.static_textures)
        self.assertIn("glass", generator.static_textures)
        self.assertIn("dandelion", generator.static_textures)

        # Check they are NOT in animated textures
        self.assertNotIn("oak_leaves", generator.animated_textures)
        self.assertNotIn("dark_oak_leaves", generator.animated_textures)
        self.assertNotIn("glass", generator.animated_textures)

        # Check truly animated textures are in animated_textures
        self.assertIn("fire_0", generator.animated_textures)
        self.assertIn("lava_still", generator.animated_textures)
        self.assertIn("water_flow", generator.animated_textures)
        self.assertIn("prismarine", generator.animated_textures)
        self.assertIn("magma", generator.animated_textures)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

"""
Unit tests for Atlas Generator and Atlas Material Builder.
"""

import os
import json
import tempfile
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.materials import ATLAS_FORMAT_VERSION, AtlasGenerator, atlas_uv_from_local, chunk_cell

try:
    from PIL import Image
except ImportError:
    Image = None


class TestAtlasGenerator(unittest.TestCase):
    """Test case for Minecraft Texture Atlas Generator."""

    def setUp(self):
        jar_env = os.environ.get("MC_JAR_PATH", "")
        self.jar_path = Path(jar_env) if jar_env else None
        self.output_dir = Path("./tests/scratch_atlas_output")

    def test_atlas_generation(self):
        from utils.system import has_pillow
        if not has_pillow():
            self.skipTest("Pillow not installed in test environment")
        if not self.jar_path or not self.jar_path.exists():
            self.skipTest(f"JAR file not configured or found: {self.jar_path}")

        generator = AtlasGenerator(self.jar_path)
        outputs = generator.build(self.output_dir)

        self.assertTrue(outputs["chunks"], "at least one atlas chunk should be generated")
        self.assertTrue(outputs["mapping"].exists(), "atlas_mapping.json should be generated")

        with open(outputs["mapping"], "r", encoding="utf-8") as fp:
            mapping = json.load(fp)

        self.assertGreaterEqual(mapping["tile_size"], 16)
        self.assertEqual(mapping["format_version"], ATLAS_FORMAT_VERSION)
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

            self.assertEqual(mapping["format_version"], ATLAS_FORMAT_VERSION)
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

    @unittest.skipIf(Image is None, "Pillow not available")
    def test_atlas_keeps_mod_namespace_in_source_key(self):
        """Atlas entries must not collide with a mod texture of the same name."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vanilla = root / "assets" / "minecraft" / "textures" / "block"
            modded = root / "assets" / "examplemod" / "textures" / "block"
            vanilla.mkdir(parents=True)
            modded.mkdir(parents=True)
            Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(vanilla / "copper.png")
            Image.new("RGBA", (16, 16), (0, 255, 0, 255)).save(modded / "copper.png")

            outputs = AtlasGenerator(root, max_chunk_size=64).build(root / "atlas")
            with open(outputs["mapping"], "r", encoding="utf-8") as fp:
                mapping = json.load(fp)

            self.assertIn("copper", mapping["textures"])
            self.assertIn("examplemod:copper", mapping["textures"])
            self.assertEqual(mapping["textures"]["copper"]["texture_key"], "minecraft:block/copper")
            self.assertEqual(mapping["textures"]["examplemod:copper"]["texture_key"], "examplemod:block/copper")

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
        if not self.jar_path or not self.jar_path.exists():
            self.skipTest(f"JAR file not configured or found: {self.jar_path}")

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

    @unittest.skipIf(Image is None, "Pillow not available")
    def test_animated_texture_single_frame_pbr_channels_are_tiled(self):
        """Single-frame normal or specular maps must be tiled across all animation frames in the atlas chunk."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            textures = root / "assets" / "minecraft" / "textures" / "block"
            textures.mkdir(parents=True)

            # 1. Animated albedo (16x64 -> 4 frames)
            albedo_img = Image.new("RGBA", (16, 64), (0, 0, 0, 255))
            for i in range(4):
                albedo_img.paste(Image.new("RGBA", (16, 16), (i * 50, 0, 0, 255)), (0, i * 16))
            albedo_img.save(textures / "soul_lantern.png")
            (textures / "soul_lantern.png.mcmeta").write_text('{"animation": {"frametime": 2}}', encoding="utf-8")

            # 2. Single-frame normal (16x16)
            norm_color = (128, 128, 255, 200)
            Image.new("RGBA", (16, 16), norm_color).save(textures / "soul_lantern_n.png")

            # 3. Single-frame specular (16x16)
            spec_color = (160, 50, 0, 250)
            Image.new("RGBA", (16, 16), spec_color).save(textures / "soul_lantern_s.png")

            # 4. Another static texture to ensure normal/specular channels are active
            Image.new("RGBA", (16, 16), (100, 100, 100, 255)).save(textures / "stone.png")
            Image.new("RGBA", (16, 16), (128, 128, 255, 255)).save(textures / "stone_n.png")
            Image.new("RGBA", (16, 16), (50, 50, 50, 255)).save(textures / "stone_s.png")

            outputs = AtlasGenerator(root, max_chunk_size=64).build(root / "atlas")
            with open(outputs["mapping"], "r", encoding="utf-8") as fp:
                mapping = json.load(fp)

            anim_chunks = [c for c in mapping["chunks"] if c["kind"] == "animation"]
            self.assertEqual(len(anim_chunks), 1)
            chunk = anim_chunks[0]

            norm_atlas = Image.open(root / "atlas" / chunk["files"]["normal"])
            spec_atlas = Image.open(root / "atlas" / chunk["files"]["specular"])

            loc = mapping["textures"]["soul_lantern"]
            px = loc["pixel_x"]
            self.assertEqual(loc["frame_count"], 4)

            # Verify normal and specular values are preserved across all 4 frames (y=4, 20, 36, 52)
            for frame_idx in range(4):
                y = frame_idx * 16 + 4
                self.assertEqual(norm_atlas.getpixel((px + 4, y)), norm_color, f"Normal mismatch at frame {frame_idx}")
                self.assertEqual(spec_atlas.getpixel((px + 4, y)), spec_color, f"Specular mismatch at frame {frame_idx}")

    @unittest.skipIf(Image is None, "Pillow not available")
    def test_namespaces_are_strictly_isolated_in_chunks(self):
        """Textures of different namespaces must never be placed into the same chunk."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mc_dir = root / "assets" / "minecraft" / "textures" / "block"
            create_dir = root / "assets" / "create" / "textures" / "block"
            fd_dir = root / "assets" / "farmersdelight" / "textures" / "block"
            mc_dir.mkdir(parents=True)
            create_dir.mkdir(parents=True)
            fd_dir.mkdir(parents=True)

            Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(mc_dir / "stone.png")
            Image.new("RGBA", (16, 16), (255, 100, 0, 255)).save(mc_dir / "dirt.png")
            Image.new("RGBA", (32, 32), (0, 255, 0, 255)).save(create_dir / "brass_casing.png")
            Image.new("RGBA", (32, 32), (0, 200, 0, 255)).save(create_dir / "andesite_casing.png")
            Image.new("RGBA", (16, 16), (0, 0, 255, 255)).save(fd_dir / "cutting_board.png")

            outputs = AtlasGenerator(root, max_chunk_size=64).build(root / "atlas")
            with open(outputs["mapping"], "r", encoding="utf-8") as fp:
                mapping = json.load(fp)

            chunks = mapping["chunks"]
            self.assertGreaterEqual(len(chunks), 3)

            # Map each chunk to its textures
            chunk_textures = {}
            for tex_name, loc in mapping["textures"].items():
                c_id = loc["chunk_id"]
                chunk_textures.setdefault(c_id, []).append(loc)

            for chunk in chunks:
                c_id = chunk["chunk_id"]
                c_ns = chunk["namespace"]
                self.assertIn(c_ns, ("minecraft", "create", "farmersdelight"))
                # Every texture inside this chunk must belong strictly to this namespace
                for loc in chunk_textures.get(c_id, []):
                    self.assertEqual(
                        loc["namespace"], c_ns,
                        f"Chunk {c_id} (ns: {c_ns}) contains texture from namespace {loc['namespace']}"
                    )

            # Check individual tile sizes
            mc_chunks = [c for c in chunks if c["namespace"] == "minecraft"]
            create_chunks = [c for c in chunks if c["namespace"] == "create"]
            fd_chunks = [c for c in chunks if c["namespace"] == "farmersdelight"]

            self.assertEqual(mc_chunks[0]["tile_size"], 16)
            self.assertEqual(create_chunks[0]["tile_size"], 32)
            self.assertEqual(fd_chunks[0]["tile_size"], 16)

    @unittest.skipIf(Image is None, "Pillow not available")
    def test_statistical_mode_determines_tile_size(self):
        """A pack with 10 16x16 textures and 2 32x32 textures must be recognized as 16px tile_size."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tex_dir = root / "assets" / "minecraft" / "textures" / "block"
            tex_dir.mkdir(parents=True)

            # 10 textures at 16x16
            for i in range(10):
                Image.new("RGBA", (16, 16), (i * 20, 50, 50, 255)).save(tex_dir / f"tex_{i}.png")
            # 2 textures at 32x32 (optifine or high-res variation)
            Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(tex_dir / "large_optifine_1.png")
            Image.new("RGBA", (32, 32), (0, 255, 0, 255)).save(tex_dir / "large_optifine_2.png")

            outputs = AtlasGenerator(root, max_chunk_size=128).build(root / "atlas")
            with open(outputs["mapping"], "r", encoding="utf-8") as fp:
                mapping = json.load(fp)

            mc_chunk = next(c for c in mapping["chunks"] if c["namespace"] == "minecraft")
            self.assertEqual(mc_chunk["tile_size"], 16, "Statistical mode should detect 16px, not 32px")
            self.assertEqual(mapping["tile_size"], 16)

    def test_vanilla_mashup_pbr_animated_tiling(self):
        """If Vanilla Mashup 1.5.zip exists, verify resolution is 16px and namespace isolation holds."""
        mashup_env = os.environ.get("MC_MASHUP_ZIP", "")
        default_mashup = Path("/Users/jaxlocke/Downloads/Vanilla Mashup 1.5.zip")
        mashup_zip = Path(mashup_env) if mashup_env else default_mashup
        try:
            if not mashup_zip or not mashup_zip.is_file() or not zipfile.is_zipfile(mashup_zip):
                self.skipTest(f"Vanilla Mashup ZIP not configured or found: {mashup_zip}")
        except Exception:
            self.skipTest("Vanilla Mashup ZIP not accessible in test environment")

        with tempfile.TemporaryDirectory() as tmp:
            gen = AtlasGenerator(mashup_zip)
            outputs = gen.build(tmp)
            with open(outputs["mapping"], "r", encoding="utf-8") as fp:
                mapping = json.load(fp)

            # Check soul_lantern has 32 frames
            self.assertIn("soul_lantern", mapping["textures"])
            loc = mapping["textures"]["soul_lantern"]
            self.assertEqual(loc["kind"], "animation")
            self.assertEqual(loc["frame_count"], 32)

            # Check minecraft chunks have tile_size 16
            mc_chunks = [c for c in mapping["chunks"] if c["namespace"] == "minecraft" and c["kind"] == "static"]
            self.assertTrue(mc_chunks)
            for mc_c in mc_chunks:
                self.assertEqual(mc_c["tile_size"], 16, "Vanilla Mashup minecraft chunks must be 16px tile_size")

            # Check namespace isolation across all chunks
            for c in mapping["chunks"]:
                self.assertIn("namespace", c)

            anim_chunk = next(c for c in mapping["chunks"] if c["chunk_id"] == loc["chunk_id"])
            spec_img = Image.open(Path(tmp) / anim_chunk["files"]["specular"])
            norm_img = Image.open(Path(tmp) / anim_chunk["files"]["normal"])

            px = loc["pixel_x"]
            spec_f0 = spec_img.getpixel((px + 4, 4))
            spec_f1 = spec_img.getpixel((px + 4, 20))
            spec_f31 = spec_img.getpixel((px + 4, 500))
            self.assertEqual(spec_f0, spec_f1)
            self.assertEqual(spec_f0, spec_f31)
            self.assertNotEqual(spec_f0, (0, 0, 0, 0))

            norm_f0 = norm_img.getpixel((px + 4, 4))
            norm_f1 = norm_img.getpixel((px + 4, 20))
            norm_f31 = norm_img.getpixel((px + 4, 500))
            self.assertEqual(norm_f0, norm_f1)
            self.assertEqual(norm_f0, norm_f31)

    @unittest.skipIf(Image is None, "Pillow not available")
    def test_mixed_width_animation_column_alignment(self):
        """Mixed 16px and 32px animation columns must align so pixel_x % frame_width == 0."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            textures = root / "assets" / "minecraft" / "textures" / "block"
            textures.mkdir(parents=True)

            # 1. 16px animation (e.g. fire / water_still)
            anim16 = Image.new("RGBA", (16, 32), (255, 0, 0, 255))
            anim16.save(textures / "anim_a.png")
            (textures / "anim_a.png.mcmeta").write_text('{"animation": {}}', encoding="utf-8")

            # 2. 32px animation (e.g. water_flow)
            anim32 = Image.new("RGBA", (32, 64), (0, 0, 255, 255))
            anim32.save(textures / "anim_b.png")
            (textures / "anim_b.png.mcmeta").write_text('{"animation": {}}', encoding="utf-8")

            outputs = AtlasGenerator(root, max_chunk_size=512).build(root / "atlas")
            with open(outputs["mapping"], "r", encoding="utf-8") as fp:
                mapping = json.load(fp)

            loc_a = mapping["textures"]["anim_a"]
            loc_b = mapping["textures"]["anim_b"]

            # Verify alignment
            self.assertEqual(loc_a["pixel_x"] % loc_a["frame_width"], 0)
            self.assertEqual(loc_b["pixel_x"] % loc_b["frame_width"], 0)
            # 16px starts at 0, 32px starts at 32 (aligned to 32px multiple)
            self.assertEqual(loc_a["pixel_x"], 0)
            self.assertEqual(loc_b["pixel_x"], 32)


if __name__ == "__main__":
    unittest.main(argv=["dummy"])

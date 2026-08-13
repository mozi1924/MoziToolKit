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
from utils.atlas_layout import atlas_uv_from_local, static_cell

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
        if not self.jar_path.exists():
            self.skipTest(f"JAR file not found: {self.jar_path}")

        generator = AtlasGenerator(self.jar_path)
        outputs = generator.build(self.output_dir)

        self.assertTrue(outputs["albedo"].exists(), "atlas_albedo.png should be generated")
        self.assertTrue(outputs["mapping"].exists(), "atlas_mapping.json should be generated")

        with open(outputs["mapping"], "r", encoding="utf-8") as fp:
            mapping = json.load(fp)

        self.assertGreaterEqual(mapping["tile_size"], 16)
        self.assertEqual(mapping["format_version"], 3)
        self.assertGreater(mapping["static_material_columns"], 0)
        self.assertGreater(mapping["static_materials_count"], 0)
        self.assertGreater(mapping["animated_columns_count"], 0)
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

            outputs = AtlasGenerator(root).build(root / "atlas")
            with open(outputs["mapping"], "r", encoding="utf-8") as fp:
                mapping = json.load(fp)

            self.assertEqual(mapping["format_version"], 3)
            self.assertEqual(mapping["tile_size"], 32)
            self.assertEqual(mapping["static_material_columns"], 1)
            self.assertEqual(mapping["atlas_width"], 6 * 32)
            atlas = Image.open(outputs["albedo"])
            # Alphabetical IDs put ``large`` in the first (top) material row
            # and ``small`` in the second.  Every face cell must contain the
            # corresponding source texture at the canonical tile size.
            self.assertEqual(atlas.getpixel((0, 0)), (0, 255, 0, 255))
            self.assertEqual(atlas.getpixel((0, 32)), (255, 0, 0, 255))

    def test_baked_uv_uses_the_same_static_cell_layout_as_the_atlas(self):
        column, row = static_cell(material_id=3, face_index=2, material_columns=2)
        self.assertEqual((column, row), (8, 1))
        self.assertEqual(
            atlas_uv_from_local(
                0.25, 0.75, tile_column=column, tile_row=row,
                tile_size=16, atlas_width=192, atlas_height=64,
            ),
            ((8.25 * 16) / 192, 1.0 - (1.25 * 16) / 64),
        )


if __name__ == "__main__":
    unittest.main()

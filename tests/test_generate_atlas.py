"""
Unit tests for Atlas Generator and Atlas Material Builder.
"""

import json
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.generate_atlas import AtlasGenerator


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

        self.assertEqual(mapping["tile_size"], 16)
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


if __name__ == "__main__":
    unittest.main()

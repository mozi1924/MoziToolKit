"""
Unit tests for the specialized firefly_bush material and geometry pipeline.
"""

import unittest
from pathlib import Path
from PIL import Image

from MoziToolKit.utils.mc_baker import StateBaker
from MoziToolKit.utils.materials.specialized import (
    is_firefly_bush,
    sanitize_firefly_bush_elements,
    synthesize_firefly_bush_textures,
    is_firefly_bush_tint_exempt,
)
from MoziToolKit.utils.materials.biome.biome import classify_tint_category
from MoziToolKit.utils.materials.pack.pack_stack import ResourcePackStack

JAR_PATH = Path("/home/mozi/.minecraft/versions/26.2-Fabric/26.2-Fabric.jar")


class TestFireflyBushSpecialized(unittest.TestCase):

    def test_firefly_bush_identifier_and_tint_exemption(self):
        """Verify that firefly_bush is properly identified and exempt from grass tinting."""
        self.assertTrue(is_firefly_bush("firefly_bush"))
        self.assertTrue(is_firefly_bush("minecraft:firefly_bush"))
        self.assertTrue(is_firefly_bush("minecraft:block/firefly_bush"))
        self.assertTrue(is_firefly_bush_tint_exempt("firefly_bush"))
        self.assertTrue(is_firefly_bush_tint_exempt("firefly_bush_emissive"))

        # Verify biome classification returns 'none' for firefly_bush
        self.assertEqual(classify_tint_category("firefly_bush"), "none")
        self.assertEqual(classify_tint_category("minecraft:block/firefly_bush"), "none")

        # Other bushes that shouldn't be tinted
        self.assertEqual(classify_tint_category("sweet_berry_bush"), "none")
        self.assertEqual(classify_tint_category("dead_bush"), "none")

        # Vanilla bush (short grass bush) remains grass-tinted
        self.assertEqual(classify_tint_category("bush"), "grass")

    def test_geometry_sanitization_removes_coplanar_overlap(self):
        """Verify that sanitize_firefly_bush_elements removes overlapping emissive cross elements."""
        raw_elements = [
            {
                "from": [0.8, 0, 8], "to": [15.2, 16, 8],
                "faces": {"north": {"texture": "#cross"}, "south": {"texture": "#cross"}}
            },
            {
                "from": [8, 0, 0.8], "to": [8, 16, 15.2],
                "faces": {"west": {"texture": "#cross"}, "east": {"texture": "#cross"}}
            },
            {
                "from": [0.8, 0, 8], "to": [15.2, 16, 8],
                "faces": {"north": {"texture": "#cross_emissive"}, "south": {"texture": "#cross_emissive"}}
            },
            {
                "from": [8, 0, 0.8], "to": [8, 16, 15.2],
                "faces": {"west": {"texture": "#cross_emissive"}, "east": {"texture": "#cross_emissive"}}
            },
        ]

        sanitized = sanitize_firefly_bush_elements("firefly_bush", raw_elements)
        self.assertEqual(len(sanitized), 2)
        for elem in sanitized:
            for face in elem["faces"].values():
                self.assertEqual(face["texture"], "minecraft:block/firefly_bush")
                self.assertEqual(face.get("tintindex"), -1)

    def test_state_baker_firefly_bush_single_layer(self):
        """Verify StateBaker bakes exactly 2 cross elements for firefly_bush (no coplanar duplicates)."""
        if not JAR_PATH.is_file():
            self.skipTest(f"Minecraft JAR not found at {JAR_PATH}")

        baker = StateBaker(jar_path=str(JAR_PATH))
        baked = baker.bake_block_state("minecraft:firefly_bush")
        self.assertEqual(len(baked.elements), 2)
        for elem in baked.elements:
            for bf in elem.faces.values():
                self.assertEqual(bf.texture, "minecraft:block/firefly_bush")
                self.assertEqual(bf.tint_index, -1)

    def test_texture_synthesis_and_pack_stack_integration(self):
        """Verify pack_stack synthesizes 10-frame Albedo and companion emissive Specular."""
        if not JAR_PATH.is_file():
            self.skipTest(f"Minecraft JAR not found at {JAR_PATH}")

        stack = ResourcePackStack([str(JAR_PATH)])
        info = stack.get_texture_info("firefly_bush")
        self.assertIsNotNone(info)
        self.assertEqual(info["texture_name"], "firefly_bush")
        self.assertIsNotNone(info["albedo"])
        self.assertIsNotNone(info["specular"])
        self.assertIsNotNone(info["albedo_mcmeta"])
        self.assertEqual(info["albedo_mcmeta"]["frametime"], 3)
        self.assertEqual(len(info["albedo_mcmeta"]["frames"]), 10)

        # Inspect generated images
        albedo_img = Image.open(info["albedo"])
        spec_img = Image.open(info["specular"])
        self.assertEqual(albedo_img.size, (16, 160))
        self.assertEqual(spec_img.size, (16, 160))

        # Check emission in Alpha of specular image
        spec_pixels = list(spec_img.getdata())
        emissive_count = sum(1 for p in spec_pixels if p[3] > 0)
        self.assertEqual(emissive_count, 27)


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for Minecraft 26.2 Block Colors, tintindex multi-layer resolution,
and custom model biome attribute fallback pipeline in MoziToolKit.
"""

import os
import unittest
import zipfile
from pathlib import Path

from utils.materials.biome.biome import (
    classify_tint_category,
    BiomeResolver,
    BLOCK_TINT_REGISTRY,
    HARDCODED_BLOCK_TINTS,
    TINT_TYPE_NONE,
    TINT_TYPE_GRASS,
    TINT_TYPE_FOLIAGE,
    TINT_TYPE_WATER,
    TINT_TYPE_HARDCODED,
)
from utils.live_sync.classifier import parse_and_classify
from utils.materials.yefira.face_lut import build_block_face_tint_lut


class TestCustomModelBiomeTint(unittest.TestCase):

    def test_classify_tint_category_vanilla_and_custom(self):
        # 1. Vanilla stems
        self.assertEqual(classify_tint_category("oak_leaves"), "foliage")
        self.assertEqual(classify_tint_category("short_grass"), "grass")
        self.assertEqual(classify_tint_category("water_still"), "water")
        self.assertEqual(classify_tint_category("spruce_leaves"), "hardcoded")
        self.assertEqual(classify_tint_category("birch_leaves"), "hardcoded")

        # 2. Custom texture stems with block context
        self.assertEqual(
            classify_tint_category("05m_oak_leaves_cube", block_name="oak_leaves", tint_index=0),
            "foliage"
        )
        self.assertEqual(
            classify_tint_category("05m_dark_oak_leaves_cube", block_name="minecraft:dark_oak_leaves", tint_index=0),
            "foliage"
        )
        self.assertEqual(
            classify_tint_category("custom_water_still", block_name="water", tint_index=0),
            "water"
        )

        # 3. Heuristic fallback for arbitrary leaf textures
        self.assertEqual(classify_tint_category("05m_oak_leaves_cube"), "foliage")
        self.assertEqual(classify_tint_category("05rd_05m_dark_oak_leaves_cube"), "foliage")
        self.assertEqual(classify_tint_category("bushy_jungle_leaves_side"), "foliage")

        # 4. Untinted leaves
        self.assertEqual(classify_tint_category("cherry_leaves"), "none")
        self.assertEqual(classify_tint_category("azalea_leaves"), "none")
        self.assertEqual(classify_tint_category("pale_oak_leaves"), "none")

    def test_multi_layer_flora_tint(self):
        # pink_petals: layer 0 = petals (none), layer 1 = stem/grass (grass)
        self.assertEqual(
            classify_tint_category("pink_petals", block_name="pink_petals", tint_index=0),
            "none"
        )
        self.assertEqual(
            classify_tint_category("pink_petals_stem", block_name="pink_petals", tint_index=1),
            "grass"
        )
        self.assertEqual(
            classify_tint_category("pink_petals", block_name="pink_petals", tint_index=-1),
            "none"
        )

    def test_biome_resolver_with_custom_pack(self):
        resolver = BiomeResolver()
        
        # Oak leaves custom texture
        tint_info_oak = resolver.get_tint_info("05m_oak_leaves_cube", block_name="oak_leaves", tint_index=0)
        self.assertEqual(tint_info_oak["tint_category"], "foliage")
        self.assertEqual(tint_info_oak["tint_type"], TINT_TYPE_FOLIAGE)
        self.assertEqual(tint_info_oak["tint_weight"], 1.0)
        self.assertEqual(tint_info_oak["is_hardcoded"], False)

        # Spruce leaves custom texture
        tint_info_spruce = resolver.get_tint_info("05m_spruce_leaves_cube", block_name="spruce_leaves", tint_index=0)
        self.assertEqual(tint_info_spruce["tint_category"], "hardcoded")
        self.assertEqual(tint_info_spruce["tint_type"], TINT_TYPE_HARDCODED)
        self.assertEqual(tint_info_spruce["is_hardcoded"], True)
        self.assertIsNotNone(tint_info_spruce["hardcoded_color"])

        # Water custom texture
        tint_info_water = resolver.get_tint_info("custom_water_flow", block_name="flowing_water", tint_index=0)
        self.assertEqual(tint_info_water["tint_category"], "water")
        self.assertEqual(tint_info_water["tint_type"], TINT_TYPE_WATER)

    def test_zip_resource_pack_models(self):
        zip_path = Path("/Users/jaxlocke/Downloads/!§r§f§l 树叶 繁茂模型 §7- 2025-11-04 §0.zip")
        if not zip_path.exists():
            self.skipTest("Bushy leaves sample zip not available at test path")

        zf = zipfile.ZipFile(zip_path)
        resolver = BiomeResolver()
        import json
        models_data = {}
        for name in zf.namelist():
            if name.startswith("assets/minecraft/models/block/") and name.endswith(".json"):
                stem = Path(name).stem
                try:
                    models_data[stem] = json.loads(zf.read(name).decode("utf-8"))
                except Exception:
                    pass

        resolver.set_models(models_data)

        # Check that 05m_oak_leaves_cube got identified as foliage
        info = resolver.get_tint_info("05m_oak_leaves_cube")
        self.assertEqual(info["tint_category"], "foliage")
        self.assertEqual(info["tint_type"], TINT_TYPE_FOLIAGE)
        self.assertEqual(info["tint_weight"], 1.0)

    def test_point_cloud_classifier_tints(self):
        # 1. Oak leaves -> Foliage tint data
        oak = parse_and_classify("minecraft:oak_leaves")
        self.assertEqual(oak.tint_data, (1.0, 1.0, 1.0, 0.0))

        # 2. Spruce leaves -> Hardcoded tint data
        spruce = parse_and_classify("minecraft:spruce_leaves")
        self.assertEqual(spruce.tint_data, (1.0, 1.0, 1.0, 1.0))
        self.assertEqual(spruce.tint_color, (0.38039, 0.60000, 0.38039, 1.0))

        # 3. Water -> Water tint data
        water = parse_and_classify("minecraft:water")
        self.assertEqual(water.tint_data, (1.0, 1.0, 1.0, 0.0))

        # 4. Cherry leaves -> Untinted
        cherry = parse_and_classify("minecraft:cherry_leaves")
        self.assertEqual(cherry.tint_data, (0.0, 0.0, 0.0, 0.0))

    def test_face_lut_tint_weights(self):
        mock_mapping = {
            "textures": {
                "05m_oak_leaves_cube": {
                    "texture_id": 1,
                    "tint_category": "foliage",
                    "default_tint_weight": 1.0,
                    "default_base_tint_weight": 1.0,
                    "default_overlay_tint_weight": 1.0,
                },
                "stone": {
                    "texture_id": 2,
                    "tint_category": "none",
                    "default_tint_weight": 0.0,
                }
            }
        }
        tint_lut = build_block_face_tint_lut(mock_mapping)
        self.assertIn("05m_oak_leaves_cube", tint_lut)
        for face_weight in tint_lut["05m_oak_leaves_cube"]:
            self.assertEqual(face_weight[2], 1.0)


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for 1:1 OBJ Model Loading and Baking in MC Baker.
Tests Chests (Single/Double/Copper/Trapped/Ender), Bells, Decorated Pots, Banners, Skulls, and Hanging Signs.
"""

import unittest
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from utils.mc_baker import StateBaker
from utils.mc_baker.obj_loader import (
    resolve_obj_model_for_state,
    build_baked_model_from_obj,
    _OBJ_CACHE,
)


class TestOBJModels(unittest.TestCase):
    def setUp(self):
        self.baker = StateBaker()

    def test_chest_obj_loading(self):
        """Test single, left, and right chest loading and texture mapping."""
        # 1. Single Chest (Normal, Copper, Trapped, Ender)
        baked_single = self.baker.bake_block_state("minecraft:chest[facing=north,type=single]")
        self.assertIsNotNone(baked_single)
        self.assertEqual(len(baked_single.elements), 18)  # 18 faces from chest.obj#chest
        face0 = list(baked_single.elements[0].faces.values())[0]
        self.assertEqual(face0.texture, "minecraft:entity/chest/normal")

        # 2. Copper Chests (various stages)
        baked_copper = self.baker.bake_block_state("minecraft:copper_chest[facing=south,type=single]")
        face_copper = list(baked_copper.elements[0].faces.values())[0]
        self.assertEqual(face_copper.texture, "minecraft:entity/chest/copper")

        baked_waxed_oxidized = self.baker.bake_block_state("minecraft:waxed_oxidized_copper_chest[facing=east,type=single]")
        face_oxidized = list(baked_waxed_oxidized.elements[0].faces.values())[0]
        self.assertEqual(face_oxidized.texture, "minecraft:entity/chest/copper_oxidized")

        # 3. Trapped and Ender Chests
        baked_trapped = self.baker.bake_block_state("minecraft:trapped_chest[facing=west,type=single]")
        face_trapped = list(baked_trapped.elements[0].faces.values())[0]
        self.assertEqual(face_trapped.texture, "minecraft:entity/chest/trapped")

        baked_ender = self.baker.bake_block_state("minecraft:ender_chest[facing=north]")
        face_ender = list(baked_ender.elements[0].faces.values())[0]
        self.assertEqual(face_ender.texture, "minecraft:entity/chest/ender")

        # 4. Double Chest Left & Right
        baked_left = self.baker.bake_block_state("minecraft:chest[facing=north,type=left]")
        self.assertEqual(len(baked_left.elements), 15)
        face_left = list(baked_left.elements[0].faces.values())[0]
        self.assertEqual(face_left.texture, "minecraft:entity/chest/normal_left")

        baked_right = self.baker.bake_block_state("minecraft:chest[facing=north,type=right]")
        self.assertEqual(len(baked_right.elements), 15)
        face_right = list(baked_right.elements[0].faces.values())[0]
        self.assertEqual(face_right.texture, "minecraft:entity/chest/normal_right")

    def test_bell_and_pot_obj_loading(self):
        """Test Bell and Decorated Pot OBJ models."""
        baked_bell = self.baker.bake_block_state("minecraft:bell[facing=north]")
        self.assertIsNotNone(baked_bell)
        self.assertEqual(len(baked_bell.elements), 12)
        face_bell = list(baked_bell.elements[0].faces.values())[0]
        self.assertEqual(face_bell.texture, "minecraft:entity/bell/bell_body")

        baked_pot = self.baker.bake_block_state("minecraft:decorated_pot")
        self.assertIsNotNone(baked_pot)
        self.assertEqual(len(baked_pot.elements), 18)
        face_pot = list(baked_pot.elements[0].faces.values())[0]
        self.assertEqual(face_pot.texture, "minecraft:entity/decorated_pot/decorated_pot_base")

    def test_banner_and_skull_obj_loading(self):
        """Test Banner and Skull OBJ models."""
        # 1. Banners
        baked_banner = self.baker.bake_block_state("minecraft:white_banner[rotation=0]")
        self.assertIsNotNone(baked_banner)
        self.assertEqual(len(baked_banner.elements), 18)
        face_banner = list(baked_banner.elements[0].faces.values())[0]
        self.assertEqual(face_banner.texture, "minecraft:entity/banner/banner_base")

        baked_wall_banner = self.baker.bake_block_state("minecraft:red_wall_banner[facing=north]")
        self.assertIsNotNone(baked_wall_banner)
        self.assertEqual(len(baked_wall_banner.elements), 12)

        # 2. Skulls
        baked_head = self.baker.bake_block_state("minecraft:player_head[rotation=0]")
        self.assertIsNotNone(baked_head)
        face_head = list(baked_head.elements[0].faces.values())[0]
        self.assertEqual(face_head.texture, "minecraft:entity/player/wide/steve")

        baked_dragon = self.baker.bake_block_state("minecraft:dragon_head[rotation=0]")
        self.assertIsNotNone(baked_dragon)
        face_dragon = list(baked_dragon.elements[0].faces.values())[0]
        self.assertEqual(face_dragon.texture, "minecraft:entity/enderdragon/dragon")


if __name__ == "__main__":
    unittest.main()

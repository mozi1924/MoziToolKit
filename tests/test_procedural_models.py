"""
Unit tests for Procedural Model Generators in MC Baker.
Tests Chests, Shulker Boxes, Banners, Beds, Skulls, Conduits, Pots, Bells, and Portals.
"""

import unittest
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Bootstrap environment
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from utils.mc_baker import StateBaker
from utils.mc_baker.procedural import (
    build_chest_elements,
    build_shulker_box_elements,
    build_banner_elements,
    build_bed_elements,
    build_skull_elements,
    build_conduit_elements,
    build_decorated_pot_elements,
    build_bell_elements,
    build_end_portal_elements,
    get_procedural_elements,
    is_chest_block,
    is_shulker_block,
    is_banner_block,
    is_bed_block,
    is_skull_block,
)


class TestProceduralModels(unittest.TestCase):
    def setUp(self):
        self.baker = StateBaker()

    def test_chest_elements(self):
        """Test single and double chest element generation and textures."""
        # 1. Single Chest
        elems_single = build_chest_elements("chest", {"facing": "north", "type": "single"})
        self.assertEqual(len(elems_single), 3)  # bottom, lid, lock
        self.assertEqual(elems_single[0]["from"], [1, 0, 1])
        self.assertEqual(elems_single[0]["to"], [15, 10, 15])
        self.assertEqual(elems_single[2]["from"], [7, 7, 15])
        self.assertEqual(elems_single[2]["to"], [9, 11, 16])
        self.assertEqual(elems_single[0]["faces"]["north"]["texture"], "minecraft:entity/chest/normal")

        # 2. Trapped Chest & Ender Chest
        elems_trapped = build_chest_elements("trapped_chest", {"facing": "south", "type": "single"})
        self.assertEqual(elems_trapped[0]["faces"]["north"]["texture"], "minecraft:entity/chest/trapped")

        elems_ender = build_chest_elements("ender_chest", {"facing": "east", "type": "single"})
        self.assertEqual(elems_ender[0]["faces"]["north"]["texture"], "minecraft:entity/chest/ender")

        # 3. Double Chest (Left & Right)
        elems_left = build_chest_elements("chest", {"facing": "north", "type": "left"})
        self.assertEqual(elems_left[0]["from"], [0, 0, 1])
        self.assertNotIn("west", elems_left[0]["faces"])
        self.assertEqual(elems_left[0]["faces"]["north"]["texture"], "minecraft:entity/chest/normal_left")

        elems_right = build_chest_elements("chest", {"facing": "north", "type": "right"})
        self.assertEqual(elems_right[0]["to"], [16, 10, 15])
        self.assertNotIn("east", elems_right[0]["faces"])
        self.assertEqual(elems_right[0]["faces"]["north"]["texture"], "minecraft:entity/chest/normal_right")

        # 4. Baking through StateBaker
        baked = self.baker.bake_block_state("minecraft:chest[facing=north,type=single]")
        self.assertGreater(len(baked.elements), 0)

    def test_shulker_box_elements(self):
        """Test Shulker Box base + lid across colors and facings."""
        # 1. Undyed Shulker Box
        elems_undyed = build_shulker_box_elements("shulker_box", {"facing": "up"})
        self.assertEqual(len(elems_undyed), 2)  # base, lid
        self.assertEqual(elems_undyed[0]["faces"]["north"]["texture"], "minecraft:entity/shulker/shulker")

        # 2. Dyed Shulker Box
        elems_red = build_shulker_box_elements("red_shulker_box", {"facing": "north"})
        self.assertEqual(elems_red[0]["faces"]["north"]["texture"], "minecraft:entity/shulker/shulker_red")
        self.assertIsNotNone(elems_red[0].get("rotation"))

        # 3. Baking through StateBaker
        baked = self.baker.bake_block_state("minecraft:cyan_shulker_box[facing=up]")
        self.assertEqual(len(baked.elements), 2)

    def test_banner_elements(self):
        """Test standing and wall banner procedural generation."""
        # 1. Standing Banner
        elems_stand = build_banner_elements("white_banner", {"rotation": "0"})
        self.assertEqual(len(elems_stand), 3)  # cloth, crossbar, pole
        self.assertEqual(elems_stand[0]["faces"]["north"]["texture"], "minecraft:entity/banner/banner_base")

        # 2. Wall Banner
        elems_wall = build_banner_elements("red_wall_banner", {"facing": "north"})
        self.assertEqual(len(elems_wall), 2)  # cloth, crossbar

        # 3. Baking through StateBaker
        baked = self.baker.bake_block_state("minecraft:black_banner[rotation=4]")
        self.assertGreater(len(baked.elements), 0)

    def test_bed_elements(self):
        """Test bed head and foot parts for various colors."""
        elems_foot = build_bed_elements("red_bed", {"part": "foot"})
        self.assertEqual(len(elems_foot), 3)  # 2 legs + mattress

        elems_head = build_bed_elements("blue_bed", {"part": "head"})
        self.assertEqual(len(elems_head), 3)  # 2 legs + mattress (with pillow)

        # Baking through StateBaker
        baked = self.baker.bake_block_state("minecraft:yellow_bed[facing=north,part=foot]")
        self.assertEqual(len(baked.elements), 3)

    def test_skull_elements(self):
        """Test skull procedural elements for player, skeleton, piglin, dragon."""
        # 1. Floor Player Head
        elems_player = build_skull_elements("player_head", {"rotation": "0"})
        self.assertEqual(len(elems_player), 2)  # head + hat layer
        self.assertEqual(elems_player[0]["from"], [4, 0, 4])
        self.assertEqual(elems_player[0]["to"], [12, 8, 12])

        # 2. Wall Skeleton Skull
        elems_skel_wall = build_skull_elements("skeleton_wall_skull", {"facing": "north"})
        self.assertEqual(len(elems_skel_wall), 1)
        self.assertEqual(elems_skel_wall[0]["from"], [4, 4, 8])

        # 3. Piglin & Dragon
        elems_piglin = build_skull_elements("piglin_head", {"rotation": "0"})
        self.assertEqual(len(elems_piglin), 1)

        elems_dragon = build_skull_elements("dragon_head", {"rotation": "0"})
        self.assertEqual(len(elems_dragon), 1)

        # 4. Baking through StateBaker
        baked = self.baker.bake_block_state("minecraft:player_head[rotation=0]")
        self.assertEqual(len(baked.elements), 2)

    def test_conduit_and_pot_and_bell_and_portal(self):
        """Test Conduit, Decorated Pot, Bell, and End Portal element builders."""
        # 1. Conduit
        elems_conduit = build_conduit_elements("conduit", {})
        self.assertEqual(len(elems_conduit), 2)  # shell, eye

        # 2. Decorated Pot
        elems_pot = build_decorated_pot_elements("decorated_pot", {})
        self.assertEqual(len(elems_pot), 3)  # body, neck, rim

        # 3. Bell
        elems_bell = build_bell_elements("bell", {})
        self.assertEqual(len(elems_bell), 2)  # body, flange

        # 4. End Portal
        elems_portal = build_end_portal_elements("end_portal", {})
        self.assertEqual(len(elems_portal), 1)
        self.assertEqual(elems_portal[0]["from"], [0, 12, 0])

        # Baking through StateBaker
        baked_conduit = self.baker.bake_block_state("minecraft:conduit")
        self.assertEqual(len(baked_conduit.elements), 2)

        baked_pot = self.baker.bake_block_state("minecraft:decorated_pot")
        self.assertEqual(len(baked_pot.elements), 3)

        baked_portal = self.baker.bake_block_state("minecraft:end_portal")
        self.assertEqual(len(baked_portal.elements), 1)

    def test_registry_predicates(self):
        """Test category predicates in procedural registry."""
        self.assertTrue(is_chest_block("chest"))
        self.assertTrue(is_chest_block("trapped_chest"))
        self.assertTrue(is_chest_block("waxed_oxidized_copper_chest"))
        self.assertFalse(is_chest_block("stone"))

        self.assertTrue(is_shulker_block("shulker_box"))
        self.assertTrue(is_shulker_block("black_shulker_box"))

        self.assertTrue(is_banner_block("orange_banner"))
        self.assertTrue(is_banner_block("white_wall_banner"))

        self.assertTrue(is_bed_block("red_bed"))

        self.assertTrue(is_skull_block("player_head"))
        self.assertTrue(is_skull_block("wither_skeleton_skull"))


if __name__ == "__main__":
    unittest.main()

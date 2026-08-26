"""
Unit tests for Python Headless Minecraft Model Baker.
Tests Model resolution, Blockstate variants matching, UV rotations, and directional face generation.
"""

import unittest
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Bootstrap MoziToolKit package (also activates the isolated test sandbox)
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from utils.mc_baker import (
    StateBaker,
    ModelParser,
    BlockStateResolver,
    MC_DIRECTIONS,
)
from tests.fixtures.mc_block_fixtures import (
    FIXTURE_BLOCKSTATES,
    FIXTURE_MODELS,
    GROUND_TRUTH_FACES,
)


class TestMCModelBaker(unittest.TestCase):
    def setUp(self):
        self.parser = ModelParser()
        for k, v in FIXTURE_MODELS.items():
            self.parser.register_model(k, v)

        self.resolver = BlockStateResolver()
        for k, v in FIXTURE_BLOCKSTATES.items():
            self.resolver.register_blockstate(k, v)

        self.baker = StateBaker(model_parser=self.parser, state_resolver=self.resolver)

    def test_model_inheritance_resolution(self):
        """Test recursive parent inheritance and #pattern texture substitution."""
        resolved = self.parser.resolve_model("minecraft:block/magenta_glazed_terracotta")
        self.assertEqual(resolved["textures"]["pattern"], "minecraft:block/magenta_glazed_terracotta")
        self.assertEqual(len(resolved["elements"]), 1)
        faces = resolved["elements"][0]["faces"]
        self.assertIn("up", faces)
        self.assertEqual(faces["up"]["texture"], "minecraft:block/magenta_glazed_terracotta")

    def test_glazed_terracotta_directional_rotations(self):
        """Test Glazed Terracotta in all 4 horizontal facings and UV rotations."""
        test_states = [
            "minecraft:magenta_glazed_terracotta[facing=north]",
            "minecraft:magenta_glazed_terracotta[facing=east]",
            "minecraft:magenta_glazed_terracotta[facing=south]",
            "minecraft:magenta_glazed_terracotta[facing=west]",
        ]

        for state_str in test_states:
            baked = self.baker.bake_block_state(state_str)
            self.assertTrue(baked.is_cube)
            self.assertEqual(len(baked.faces), 6)

            if state_str in GROUND_TRUTH_FACES:
                expected_list = GROUND_TRUTH_FACES[state_str]
                for i, exp in enumerate(expected_list):
                    actual_face = baked.faces[i]
                    self.assertEqual(
                        actual_face.direction,
                        exp.direction,
                        f"Direction mismatch at idx {i} for {state_str}"
                    )
                    self.assertEqual(
                        actual_face.texture,
                        exp.texture,
                        f"Texture mismatch at idx {i} for {state_str}"
                    )
                    self.assertEqual(
                        actual_face.uv_rot,
                        exp.uv_rot,
                        f"UV rotation mismatch for {actual_face.direction} on {state_str}: got {actual_face.uv_rot}, expected {exp.uv_rot}"
                    )

    def test_command_block_facings(self):
        """Test Command Block 6 facings and conditional texture changes."""
        # Facing UP (x=270)
        baked_up = self.baker.bake_block_state("minecraft:command_block[conditional=false,facing=up]")
        # Index 2: Up (+Y) -> command_block_front with 180 deg UV rotation
        self.assertEqual(baked_up.faces[2].texture, "minecraft:block/command_block_front")
        self.assertEqual(baked_up.faces[2].uv_rot, 180.0)
        # Index 3: Down (-Y) -> command_block_back with 0 deg UV rotation
        self.assertEqual(baked_up.faces[3].texture, "minecraft:block/command_block_back")
        self.assertEqual(baked_up.faces[3].uv_rot, 0.0)
        # Sides -> command_block_side
        self.assertEqual(baked_up.faces[0].texture, "minecraft:block/command_block_side")
        self.assertEqual(baked_up.faces[1].texture, "minecraft:block/command_block_side")
        self.assertEqual(baked_up.faces[4].texture, "minecraft:block/command_block_side")
        self.assertEqual(baked_up.faces[5].texture, "minecraft:block/command_block_side")

        # Facing NORTH (x=0, y=0)
        baked_north = self.baker.bake_block_state("minecraft:command_block[conditional=false,facing=north]")
        # North (-Z, index 5) is front
        self.assertEqual(baked_north.faces[5].texture, "minecraft:block/command_block_front")
        self.assertEqual(baked_north.faces[5].uv_rot, 0.0)
        # South (+Z, index 4) is back
        self.assertEqual(baked_north.faces[4].texture, "minecraft:block/command_block_back")
        self.assertEqual(baked_north.faces[4].uv_rot, 0.0)

        # Conditional = true facing NORTH
        baked_cond = self.baker.bake_block_state("minecraft:command_block[conditional=true,facing=north]")
        self.assertEqual(baked_cond.faces[5].texture, "minecraft:block/command_block_front")
        self.assertEqual(baked_cond.faces[0].texture, "minecraft:block/command_block_conditional")

    def test_observer_facings(self):
        """Test Observer facings and UV rotations in vertical and horizontal orientations."""
        # Observer facing NORTH (x=0, y=0)
        baked_north = self.baker.bake_block_state("minecraft:observer[facing=north,powered=false]")
        self.assertEqual(baked_north.faces[5].texture, "minecraft:block/observer_front")
        self.assertEqual(baked_north.faces[4].texture, "minecraft:block/observer_back")
        self.assertEqual(baked_north.faces[2].texture, "minecraft:block/observer_top")
        self.assertEqual(baked_north.faces[2].uv_rot, 180.0)
        self.assertEqual(baked_north.faces[3].texture, "minecraft:block/observer_top")
        self.assertEqual(baked_north.faces[3].uv_rot, 0.0)

        # Observer facing UP (x=270)
        baked_up = self.baker.bake_block_state("minecraft:observer[facing=up,powered=false]")
        # Front eyes rotate to UP with 180 deg UV rotation
        self.assertEqual(baked_up.faces[2].texture, "minecraft:block/observer_front")
        self.assertEqual(baked_up.faces[2].uv_rot, 180.0)
        # Back red dot rotates to DOWN with 0 deg UV rotation
        self.assertEqual(baked_up.faces[3].texture, "minecraft:block/observer_back")
        self.assertEqual(baked_up.faces[3].uv_rot, 0.0)
        # Side orientations
        self.assertEqual(baked_up.faces[0].uv_rot, 270.0)  # East
        self.assertEqual(baked_up.faces[1].uv_rot, 90.0)   # West
        self.assertEqual(baked_up.faces[4].uv_rot, 180.0)  # South
        self.assertEqual(baked_up.faces[5].uv_rot, 180.0)  # North

        # Observer facing DOWN (x=90)
        baked_down = self.baker.bake_block_state("minecraft:observer[facing=down,powered=false]")
        # Front eyes rotate to DOWN with 180 deg UV rotation
        self.assertEqual(baked_down.faces[3].texture, "minecraft:block/observer_front")
        self.assertEqual(baked_down.faces[3].uv_rot, 180.0)
        # Back red dot rotates to UP with 0 deg UV rotation
        self.assertEqual(baked_down.faces[2].texture, "minecraft:block/observer_back")
        self.assertEqual(baked_down.faces[2].uv_rot, 0.0)
        self.assertEqual(baked_down.faces[4].uv_rot, 0.0)   # South
        self.assertEqual(baked_down.faces[5].uv_rot, 0.0)   # North

    def test_piston_facings(self):
        """Test Piston model baking in vertical and horizontal orientations."""
        # Facing UP (x=270)
        baked_up = self.baker.bake_block_state("minecraft:piston[extended=false,facing=up]")
        # Top (+Y) has piston_top with 180 deg UV rotation
        self.assertEqual(baked_up.faces[2].texture, "minecraft:block/piston_top")
        self.assertEqual(baked_up.faces[2].uv_rot, 180.0)
        # Bottom (-Y) has piston_bottom with 0 deg UV rotation
        self.assertEqual(baked_up.faces[3].texture, "minecraft:block/piston_bottom")
        self.assertEqual(baked_up.faces[3].uv_rot, 0.0)
        # Sides have piston_side
        self.assertEqual(baked_up.faces[0].texture, "minecraft:block/piston_side")

        # Facing DOWN (x=90)
        baked_down = self.baker.bake_block_state("minecraft:piston[extended=false,facing=down]")
        # Bottom (-Y) has piston_top with 180 deg UV rotation
        self.assertEqual(baked_down.faces[3].texture, "minecraft:block/piston_top")
        self.assertEqual(baked_down.faces[3].uv_rot, 180.0)
        # Top (+Y) has piston_bottom with 0 deg UV rotation
        self.assertEqual(baked_down.faces[2].texture, "minecraft:block/piston_bottom")
        self.assertEqual(baked_down.faces[2].uv_rot, 0.0)

    def test_cross_plant_zero_thickness_face_deduplication(self):
        """Verify that 2D cross models (poppy, grass) and flat models (lily_pad) deduplicate opposing faces."""
        # 1. Poppy (X-shaped cross block)
        baked_poppy = self.baker.bake_block_state("minecraft:poppy")
        self.assertFalse(baked_poppy.is_cube)
        self.assertEqual(len(baked_poppy.elements), 2, "Poppy should have 2 intersecting diagonal elements!")

        # Each element must contain exactly 1 face (not 2 duplicated opposing faces)
        for i, el in enumerate(baked_poppy.elements):
            self.assertEqual(
                len(el.faces), 1,
                f"Element {i} of cross model should have exactly 1 face to avoid internal overlapping faces, got {len(el.faces)}"
            )

        # 2. Lily Pad (horizontal flat plane)
        baked_lily = self.baker.bake_block_state("minecraft:lily_pad")
        self.assertFalse(baked_lily.is_cube)
        self.assertEqual(len(baked_lily.elements), 1)
        self.assertEqual(len(baked_lily.elements[0].faces), 1, "Lily pad should only have 1 up face, not duplicated down face!")
        self.assertIn("up", baked_lily.elements[0].faces)

    def test_chest_lid_body_latch_uv_and_geometry(self):
        """Verify that single and double chests bake 3 distinct components with exact 64x64 UV mappings."""
        # 1. Single Chest
        single = self.baker.bake_block_state("minecraft:chest[facing=north,type=single]")
        self.assertFalse(single.is_cube)
        self.assertEqual(len(single.elements), 3, "Chest must have 3 elements: lid, body, latch")

        lid = single.elements[0]
        body = single.elements[1]
        latch = single.elements[2]

        self.assertEqual(lid.from_pos, (1, 9, 1))
        self.assertEqual(lid.to_pos, (15, 14, 15))
        self.assertEqual(body.from_pos, (1, 0, 1))
        self.assertEqual(body.to_pos, (15, 10, 15))
        self.assertEqual(latch.from_pos, (7, 7, 0))
        self.assertEqual(latch.to_pos, (9, 11, 1))

        # Check UV coordinate bounds for 64x64 entity texture
        # Lid top: [28, 0, 42, 14] in 64x64 -> min_u=28/64, min_v=0/64, max_u=42/64, max_v=14/64
        self.assertEqual(lid.faces["up"].uv_bounds, (28.0 / 64.0, 0.0, 42.0 / 64.0, 14.0 / 64.0))
        # Lid bottom (underside): [14, 0, 28, 14] in 64x64
        self.assertEqual(lid.faces["down"].uv_bounds, (14.0 / 64.0, 0.0, 28.0 / 64.0, 14.0 / 64.0))
        # Body top rim: [28, 19, 42, 33] in 64x64
        self.assertEqual(body.faces["up"].uv_bounds, (28.0 / 64.0, 19.0 / 64.0, 42.0 / 64.0, 33.0 / 64.0))
        # Body bottom: [14, 19, 28, 33] in 64x64
        self.assertEqual(body.faces["down"].uv_bounds, (14.0 / 64.0, 19.0 / 64.0, 28.0 / 64.0, 33.0 / 64.0))
        # Body front: [14, 33, 28, 43] in 64x64
        self.assertEqual(body.faces["north"].uv_bounds, (14.0 / 64.0, 33.0 / 64.0, 28.0 / 64.0, 43.0 / 64.0))
        # Latch top: [3, 0, 5, 1] in 64x64
        self.assertEqual(latch.faces["up"].uv_bounds, (3.0 / 64.0, 0.0, 5.0 / 64.0, 1.0 / 64.0))
        # Latch bottom: [1, 0, 3, 1] in 64x64
        self.assertEqual(latch.faces["down"].uv_bounds, (1.0 / 64.0, 0.0, 3.0 / 64.0, 1.0 / 64.0))
        # Latch front: [1, 1, 3, 5] in 64x64
        self.assertEqual(latch.faces["north"].uv_bounds, (1.0 / 64.0, 1.0 / 64.0, 3.0 / 64.0, 5.0 / 64.0))

        # 2. Double Chest Left & Right
        left = self.baker.bake_block_state("minecraft:chest[facing=north,type=left]")
        self.assertEqual(left.elements[0].from_pos, (0, 9, 1))
        self.assertEqual(left.elements[0].to_pos, (15, 14, 15))
        self.assertEqual(left.elements[0].faces["up"].texture, "minecraft:entity/chest/normal_left")

        right = self.baker.bake_block_state("minecraft:chest[facing=north,type=right]")
        self.assertEqual(right.elements[0].from_pos, (1, 9, 1))
        self.assertEqual(right.elements[0].to_pos, (16, 14, 15))
        self.assertEqual(right.elements[0].faces["up"].texture, "minecraft:entity/chest/normal_right")

    def test_banner_proportions_and_assembly(self):
        """Verify standing and wall banner dimensions, pole-to-crossbar joint, and front cloth mounting."""
        # 1. Standing Banner
        standing = self.baker.bake_block_state("minecraft:white_banner[rotation=0]")
        self.assertFalse(standing.is_cube)
        self.assertEqual(len(standing.elements), 3, "Standing banner should have cloth, crossbar, and pole elements!")

        cloth = standing.elements[0]
        crossbar = standing.elements[1]
        pole = standing.elements[2]

        # Seamless connection: Pole top Y matches Crossbar bottom Y
        self.assertAlmostEqual(pole.to_pos[1], 28.0, places=2)
        self.assertAlmostEqual(crossbar.from_pos[1], 28.0, places=2)
        self.assertAlmostEqual(crossbar.to_pos[1], 29.333333, places=2)

        # Height is 2 blocks (~29.33 in 16-grid, reaching near 32)
        self.assertAlmostEqual(crossbar.to_pos[1], 29.333333, places=2)

        # Cloth attached to the front surface of crossbar (Z: 6.667..7.333 vs Crossbar Z: 7.333..8.667)
        self.assertAlmostEqual(cloth.to_pos[2], crossbar.from_pos[2], places=2)
        self.assertLess(cloth.from_pos[2], crossbar.from_pos[2], "Cloth should be on the front surface of the crossbar!")

        # 2. Wall Banner
        wall = self.baker.bake_block_state("minecraft:white_wall_banner[facing=north]")
        self.assertEqual(len(wall.elements), 2, "Wall banner should have cloth and crossbar elements!")
        wall_cloth = wall.elements[0]
        wall_bar = wall.elements[1]
        self.assertAlmostEqual(wall_cloth.to_pos[2], wall_bar.from_pos[2], places=2)


if __name__ == "__main__":
    unittest.main(argv=["dummy"])

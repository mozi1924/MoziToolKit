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
        # Unrotated Facing UP
        baked_up = self.baker.bake_block_state("minecraft:command_block[conditional=false,facing=up]")
        # Index 2: Up (+Y) -> command_block_front
        self.assertEqual(baked_up.faces[2].texture, "minecraft:block/command_block_front")
        # Index 3: Down (-Y) -> command_block_back
        self.assertEqual(baked_up.faces[3].texture, "minecraft:block/command_block_back")
        # Sides -> command_block_side
        self.assertEqual(baked_up.faces[0].texture, "minecraft:block/command_block_side")
        self.assertEqual(baked_up.faces[1].texture, "minecraft:block/command_block_side")
        self.assertEqual(baked_up.faces[4].texture, "minecraft:block/command_block_side")
        self.assertEqual(baked_up.faces[5].texture, "minecraft:block/command_block_side")

        # Facing NORTH (x=90)
        baked_north = self.baker.bake_block_state("minecraft:command_block[conditional=false,facing=north]")
        # When pitched 90 deg:
        # Original Up (front) rotates to North (-Z, index 5)
        self.assertEqual(baked_north.faces[5].texture, "minecraft:block/command_block_front")
        # Original Down (back) rotates to South (+Z, index 4)
        self.assertEqual(baked_north.faces[4].texture, "minecraft:block/command_block_back")

        # Conditional = true facing NORTH
        baked_cond = self.baker.bake_block_state("minecraft:command_block[conditional=true,facing=north]")
        self.assertEqual(baked_cond.faces[5].texture, "minecraft:block/command_block_front")
        self.assertEqual(baked_cond.faces[0].texture, "minecraft:block/command_block_conditional")

    def test_observer_facings(self):
        """Test Observer facings and powered states."""
        # Observer facing UP (x=0, y=0)
        baked_up = self.baker.bake_block_state("minecraft:observer[facing=up,powered=false]")
        # In unrotated observer:
        # North face has observer_front
        self.assertEqual(baked_up.faces[5].texture, "minecraft:block/observer_front")
        # South face has observer_back
        self.assertEqual(baked_up.faces[4].texture, "minecraft:block/observer_back")
        # Up/Down have observer_top
        self.assertEqual(baked_up.faces[2].texture, "minecraft:block/observer_top")
        self.assertEqual(baked_up.faces[3].texture, "minecraft:block/observer_top")

        # Observer facing NORTH, powered=true (x=90)
        baked_on = self.baker.bake_block_state("minecraft:observer[facing=north,powered=true]")
        # Original South (observer_back_on) rotated 90 deg around X goes to Up (+Y, index 2)
        self.assertEqual(baked_on.faces[2].texture, "minecraft:block/observer_back_on")
        # Original North (observer_front) rotated 90 deg around X goes to Down (-Y, index 3)
        self.assertEqual(baked_on.faces[3].texture, "minecraft:block/observer_front")
        # Original Up (observer_top) rotated 90 deg around X goes to North (-Z, index 5)
        self.assertEqual(baked_on.faces[5].texture, "minecraft:block/observer_top")

    def test_piston_facings(self):
        """Test Piston model baking."""
        baked_up = self.baker.bake_block_state("minecraft:piston[extended=false,facing=up]")
        # Top (+Y) has piston_top
        self.assertEqual(baked_up.faces[2].texture, "minecraft:block/piston_top")
        # Bottom (-Y) has piston_bottom
        self.assertEqual(baked_up.faces[3].texture, "minecraft:block/piston_bottom")
        # Sides have piston_side
        self.assertEqual(baked_up.faces[0].texture, "minecraft:block/piston_side")


if __name__ == "__main__":
    unittest.main(argv=["dummy"])

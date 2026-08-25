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


if __name__ == "__main__":
    unittest.main(argv=["dummy"])

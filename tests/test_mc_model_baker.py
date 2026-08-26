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

    def test_chest_model_json_driven_baking(self):
        """Verify that chests with JSON models bake purely from JSON elements, UVs, and variants."""
        # Register a sample 3D chest JSON model and blockstate fixture
        chest_json_model = {
            "textures": {
                "particle": "minecraft:entity/chest/normal",
                "texture": "minecraft:entity/chest/normal",
            },
            "elements": [
                {
                    "from": [1, 9, 1],
                    "to": [15, 14, 15],
                    "faces": {
                        "up": {"uv": [7, 0, 10.5, 3.5], "texture": "#texture"},
                        "down": {"uv": [3.5, 0, 7, 3.5], "texture": "#texture"},
                        "north": {"uv": [7, 3.5, 3.5, 4.75], "texture": "#texture"},
                        "south": {"uv": [14, 3.5, 10.5, 4.75], "texture": "#texture"},
                    }
                },
                {
                    "from": [1, 0, 1],
                    "to": [15, 10, 15],
                    "faces": {
                        "up": {"uv": [7, 4.75, 10.5, 8.25], "texture": "#texture"},
                        "down": {"uv": [3.5, 4.75, 7, 8.25], "texture": "#texture"},
                    }
                }
            ]
        }
        self.parser.register_model("minecraft:block/custom_chest", chest_json_model)
        self.resolver.register_blockstate("minecraft:custom_chest", {
            "variants": {
                "facing=north": {"model": "minecraft:block/custom_chest"},
                "facing=south": {"model": "minecraft:block/custom_chest", "y": 180},
                "facing=west": {"model": "minecraft:block/custom_chest", "y": 270},
                "facing=east": {"model": "minecraft:block/custom_chest", "y": 90},
            }
        })

        # Bake north facing
        baked_north = self.baker.bake_block_state("minecraft:custom_chest[facing=north]")
        self.assertFalse(baked_north.is_cube)
        self.assertEqual(len(baked_north.elements), 2)
        self.assertEqual(baked_north.elements[0].from_pos, (1, 9, 1))
        self.assertEqual(baked_north.elements[0].to_pos, (15, 14, 15))
        self.assertEqual(baked_north.elements[0].faces["up"].texture, "minecraft:entity/chest/normal")

        # Bake south facing (y=180 rotation applied by unified FaceBakery)
        baked_south = self.baker.bake_block_state("minecraft:custom_chest[facing=south]")
        self.assertEqual(len(baked_south.elements), 2)
        # Element rotated 180 degrees around (8, 8, 8): from (1, 9, 1) -> (1, 9, 1) to (15, 14, 15)
        self.assertEqual(baked_south.elements[0].from_pos, (1, 9, 1))
        self.assertEqual(baked_south.elements[0].to_pos, (15, 14, 15))

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

        # Unrotated base bounds check
        self.assertAlmostEqual(cloth.to_pos[2], crossbar.from_pos[2], places=2)
        self.assertLess(cloth.from_pos[2], crossbar.from_pos[2], "Base cloth should be on the front surface of the crossbar!")

        # 2. Verify Standing Banner Rotations (0: South, 4: West, 8: North, 12: East)
        expected_dirs = {0: "south", 4: "west", 8: "north", 12: "east"}
        for rot_idx, exp_dir in expected_dirs.items():
            b = self.baker.bake_block_state(f"minecraft:white_banner[rotation={rot_idx}]")
            cloth_face = b.elements[0].faces["north"]
            self.assertEqual(cloth_face.direction, exp_dir, f"Standing banner rotation={rot_idx} should face {exp_dir}!")

        # 3. Wall Banner
        wall = self.baker.bake_block_state("minecraft:white_wall_banner[facing=north]")
        self.assertEqual(len(wall.elements), 2, "Wall banner should have cloth and crossbar elements!")
        wall_cloth = wall.elements[0]
        wall_bar = wall.elements[1]
        self.assertAlmostEqual(wall_cloth.to_pos[2], wall_bar.from_pos[2], places=2)

        # Verify all 4 Wall Banner Facings
        for f in ["north", "south", "west", "east"]:
            wb = self.baker.bake_block_state(f"minecraft:white_wall_banner[facing={f}]")
            wf = wb.elements[0].faces["north"]
            self.assertEqual(wf.direction, f, f"Wall banner facing={f} should face {f}!")


if __name__ == "__main__":
    unittest.main(argv=["dummy"])

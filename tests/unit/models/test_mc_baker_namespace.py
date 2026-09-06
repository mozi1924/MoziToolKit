"""
Unit tests for mc_baker cross-namespace support and non-minecraft mod block baking.
Validates that mod namespaces (e.g. create, thermal, biomesoplenty) are fully preserved
and never corrupted with 'minecraft:' prefixes.
"""

import unittest
from pathlib import Path

from tests._bootstrap import bootstrap_environment
bootstrap_environment()

from utils.mc_baker.blockstate_resolver import parse_block_state_string, BlockStateResolver
from utils.mc_baker.model_parser import ModelParser
from utils.mc_baker.state_baker import StateBaker


class TestMcBakerNamespace(unittest.TestCase):
    """Test suite for cross-namespace model baking in mc_baker."""

    def test_parse_block_state_string_preserves_namespace(self):
        """Verify parse_block_state_string keeps mod namespace intact."""
        # 1. Plain mod block without properties
        block_id, props = parse_block_state_string("create:cogwheel")
        self.assertEqual(block_id, "create:cogwheel")
        self.assertEqual(props, {})

        # 2. Mod block with properties
        block_id, props = parse_block_state_string("create:cogwheel[axis=y]")
        self.assertEqual(block_id, "create:cogwheel")
        self.assertEqual(props, {"axis": "y"})

        # 3. Multiple properties
        block_id, props = parse_block_state_string("thermal:machine[facing=north,active=true]")
        self.assertEqual(block_id, "thermal:machine")
        self.assertEqual(props, {"facing": "north", "active": "true"})

        # 4. Minecraft vanilla block without namespace should get default
        block_id, props = parse_block_state_string("stone")
        self.assertEqual(block_id, "minecraft:stone")

        # 5. Minecraft vanilla block with namespace
        block_id, props = parse_block_state_string("minecraft:observer[facing=north]")
        self.assertEqual(block_id, "minecraft:observer")
        self.assertEqual(props, {"facing": "north"})

    def test_blockstate_resolver_mod_namespace(self):
        """Verify BlockStateResolver registers and resolves mod blockstates correctly."""
        resolver = BlockStateResolver()

        mock_state = {
            "variants": {
                "axis=x": {"model": "create:block/cogwheel", "x": 90, "y": 90},
                "axis=y": {"model": "create:block/cogwheel"},
                "axis=z": {"model": "create:block/cogwheel", "x": 90},
            }
        }
        resolver.register_blockstate("create:cogwheel", mock_state)

        # Cache key must be 'create:cogwheel', NEVER 'minecraft:create:cogwheel'
        self.assertIn("create:cogwheel", resolver._state_cache)
        self.assertNotIn("minecraft:create:cogwheel", resolver._state_cache)

        # Resolve variant
        matches = resolver.resolve_state("create:cogwheel[axis=y]")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].model_id, "create:block/cogwheel")
        self.assertEqual(matches[0].rot_x, 0.0)

        # Fallback for unknown mod blockstate
        fallback_matches = resolver.resolve_state("create:unknown_shaft[axis=y]")
        self.assertEqual(len(fallback_matches), 1)
        self.assertEqual(fallback_matches[0].model_id, "create:block/unknown_shaft")
        self.assertFalse(fallback_matches[0].model_id.startswith("minecraft:"))

    def test_blockstate_resolver_short_model_name_uses_default_namespace(self):
        """Verify variant models with omitted namespace inherit block's mod namespace."""
        resolver = BlockStateResolver()
        mock_state = {
            "variants": {
                "": {"model": "block/custom_crate"}
            }
        }
        resolver.register_blockstate("farmersdelight:crate", mock_state)
        matches = resolver.resolve_state("farmersdelight:crate")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].model_id, "farmersdelight:block/custom_crate")

    def test_model_parser_normalization_and_cross_inheritance(self):
        """Verify ModelParser preserves mod namespace and resolves cross-namespace parents."""
        parser = ModelParser()

        # ID normalization
        self.assertEqual(parser._normalize_id("create:cogwheel"), "create:block/cogwheel")
        self.assertEqual(parser._normalize_id("create:block/cogwheel"), "create:block/cogwheel")
        self.assertEqual(parser._normalize_id("create:custom/special"), "create:custom/special")
        self.assertEqual(parser._normalize_id("stone"), "minecraft:block/stone")

        # Texture normalization
        self.assertEqual(parser._normalize_texture("create:block/cogwheel_side"), "create:block/cogwheel_side")
        self.assertEqual(parser._normalize_texture("block/stone"), "minecraft:block/stone")
        self.assertEqual(parser._normalize_texture("stone"), "minecraft:block/stone")

        # Cross-namespace parent inheritance:
        # Parent is vanilla cube_all: minecraft:block/cube_all
        # Child is mod model: create:block/brass_block
        parent_model = {
            "parent": "minecraft:block/block",
            "elements": [
                {
                    "from": [0, 0, 0],
                    "to": [16, 16, 16],
                    "faces": {
                        "down": {"texture": "#all", "cullface": "down"},
                        "up": {"texture": "#all", "cullface": "up"},
                        "north": {"texture": "#all", "cullface": "north"},
                        "south": {"texture": "#all", "cullface": "south"},
                        "west": {"texture": "#all", "cullface": "west"},
                        "east": {"texture": "#all", "cullface": "east"},
                    }
                }
            ]
        }
        child_model = {
            "parent": "minecraft:block/cube_all",
            "textures": {
                "all": "create:block/brass_block"
            }
        }

        parser.register_model("minecraft:block/cube_all", parent_model)
        parser.register_model("create:block/brass_block", child_model)

        resolved = parser.resolve_model("create:block/brass_block")
        self.assertEqual(resolved["model_id"], "create:block/brass_block")
        self.assertEqual(resolved["textures"]["all"], "create:block/brass_block")
        self.assertEqual(len(resolved["elements"]), 1)
        faces = resolved["elements"][0]["faces"]
        self.assertEqual(faces["up"]["texture"], "create:block/brass_block")
        self.assertEqual(faces["north"]["texture"], "create:block/brass_block")

    def test_state_baker_mod_block(self):
        """Verify StateBaker fully bakes a mod block into BakedModel with mod textures."""
        baker = StateBaker()

        # Register blockstate
        baker.state_resolver.register_blockstate("create:brass_block", {
            "variants": {
                "": {"model": "create:block/brass_block"}
            }
        })

        # Register model
        baker.model_parser.register_model("create:block/brass_block", {
            "elements": [
                {
                    "from": [0, 0, 0],
                    "to": [16, 16, 16],
                    "faces": {
                        "down": {"texture": "create:block/brass_block", "cullface": "down"},
                        "up": {"texture": "create:block/brass_block", "cullface": "up"},
                        "north": {"texture": "create:block/brass_block", "cullface": "north"},
                        "south": {"texture": "create:block/brass_block", "cullface": "south"},
                        "west": {"texture": "create:block/brass_block", "cullface": "west"},
                        "east": {"texture": "create:block/brass_block", "cullface": "east"},
                    }
                }
            ]
        })

        baked = baker.bake_block_state("create:brass_block")
        self.assertIsNotNone(baked)
        self.assertEqual(baked.block_state, "create:brass_block")
        self.assertTrue(baked.is_cube)
        self.assertEqual(len(baked.faces), 6)
        for face in baked.faces:
            self.assertEqual(face.texture, "create:block/brass_block")

    def test_state_baker_fallback_texture_for_mod(self):
        """Verify fallback base elements for mod block uses mod namespace."""
        baker = StateBaker()
        # No blockstate or model registered -> triggers fallback cuboid
        baked = baker.bake_block_state("create:unmodeled_gear")
        self.assertIsNotNone(baked)
        self.assertEqual(baked.block_state, "create:unmodeled_gear")
        for face in baked.faces:
            self.assertEqual(face.texture, "create:block/unmodeled_gear")


if __name__ == "__main__":
    unittest.main()

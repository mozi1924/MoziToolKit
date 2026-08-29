"""
Unit tests for JSON-First Minecraft Model Baking with OBJ Fallback on Demand.
Verifies that:
1. Blocks with valid JSON models (e.g. modern hanging signs, custom resource packs) bake from JSON.
2. Entity blocks without JSON elements (e.g. chests, shulker boxes, heads) fall back to 1:1 OBJ models.
3. Legacy hanging sign OBJ fallback properly uses material_map for multi-texture separation.
"""

import unittest
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from utils.mc_baker import (
    StateBaker,
    ModelParser,
    BlockStateResolver,
)
from utils.mc_baker.resource_loader import JarResourceLoader


class TestJsonFirstBaker(unittest.TestCase):
    def test_json_first_with_26_2_jar(self):
        """Test baking against real 26.2-Fabric.jar: hanging_sign uses JSON, chest falls back to OBJ."""
        jar_path = "/Users/jaxlocke/26.2-Fabric.jar"
        if not Path(jar_path).exists():
            self.skipTest(f"Jar not found at {jar_path}")

        loader = JarResourceLoader(jar_path)
        parser = ModelParser(model_loader_fn=loader.load_model)
        resolver = BlockStateResolver(blockstate_loader_fn=loader.load_blockstate)
        baker = StateBaker(model_parser=parser, state_resolver=resolver)
        baker.resource_loader = loader

        # 1. Oak Hanging Sign in 26.2 jar has native JSON models (5 elements)
        state_hanging = "minecraft:oak_hanging_sign[rotation=0,attached=false]"
        baked_hanging = baker.bake_block_state(state_hanging)
        self.assertIsNotNone(baked_hanging)
        # Verify it baked from JSON elements (5 elements in template_hanging_sign_rot_0)
        self.assertEqual(len(baked_hanging.elements), 5)
        # Verify textures map to native block texture
        hanging_textures = {f.texture for el in baked_hanging.elements for f in el.faces.values()}
        self.assertIn("minecraft:block/oak_hanging_sign", hanging_textures)

        # 2. Wall Hanging Sign in 26.2 jar (6 elements)
        state_wall = "minecraft:spruce_wall_hanging_sign[facing=north]"
        baked_wall = baker.bake_block_state(state_wall)
        self.assertIsNotNone(baked_wall)
        self.assertEqual(len(baked_wall.elements), 6)
        wall_textures = {f.texture for el in baked_wall.elements for f in el.faces.values()}
        self.assertIn("minecraft:block/spruce_hanging_sign", wall_textures)

        # 3. Chest has no elements in JSON model, falls back to 1:1 OBJ model (18 elements)
        state_chest = "minecraft:chest[facing=north,type=single]"
        baked_chest = baker.bake_block_state(state_chest)
        self.assertIsNotNone(baked_chest)
        self.assertEqual(len(baked_chest.elements), 18)
        chest_textures = {f.texture for el in baked_chest.elements for f in el.faces.values()}
        self.assertIn("minecraft:entity/chest/normal", chest_textures)

        # 4. Shulker Box falls back to OBJ model (122 elements)
        state_shulker = "minecraft:cyan_shulker_box[facing=up]"
        baked_shulker = baker.bake_block_state(state_shulker)
        self.assertIsNotNone(baked_shulker)
        self.assertEqual(len(baked_shulker.elements), 122)
        shulker_textures = {f.texture for el in baked_shulker.elements for f in el.faces.values()}
        self.assertIn("minecraft:entity/shulker/shulker_cyan", shulker_textures)

    def test_custom_json_model_overrides_obj_fallback(self):
        """Test that if a resource pack provides a custom JSON model for an entity block, it is honored."""
        parser = ModelParser()
        resolver = BlockStateResolver()

        # Custom JSON chest model with 1 custom cuboid element
        custom_chest_model = {
            "textures": {
                "custom_tex": "minecraft:block/custom_chest_texture",
            },
            "elements": [
                {
                    "from": [1, 1, 1],
                    "to": [15, 15, 15],
                    "faces": {
                        "up": {"uv": [0, 0, 16, 16], "texture": "#custom_tex"},
                        "down": {"uv": [0, 0, 16, 16], "texture": "#custom_tex"},
                        "north": {"uv": [0, 0, 16, 16], "texture": "#custom_tex"},
                        "south": {"uv": [0, 0, 16, 16], "texture": "#custom_tex"},
                        "east": {"uv": [0, 0, 16, 16], "texture": "#custom_tex"},
                        "west": {"uv": [0, 0, 16, 16], "texture": "#custom_tex"},
                    },
                }
            ],
        }
        custom_chest_blockstate = {
            "variants": {
                "": {"model": "minecraft:block/custom_chest"}
            }
        }

        parser.register_model("minecraft:block/custom_chest", custom_chest_model)
        resolver.register_blockstate("minecraft:chest", custom_chest_blockstate)

        baker = StateBaker(model_parser=parser, state_resolver=resolver)
        baked = baker.bake_block_state("minecraft:chest[facing=north,type=single]")

        # Should use the 1 custom JSON element, NOT the 18-element default OBJ
        self.assertEqual(len(baked.elements), 1)
        face_up = baked.elements[0].faces["up"]
        self.assertEqual(face_up.texture, "minecraft:block/custom_chest_texture")

    def test_hanging_sign_obj_fallback_material_map(self):
        """When baking a hanging sign with no JSON models registered (legacy fallback), verify material_map."""
        baker = StateBaker()  # Empty baker without JSON models registered
        state_wall = "minecraft:oak_wall_hanging_sign[facing=north]"
        baked = baker.bake_block_state(state_wall)
        self.assertIsNotNone(baked)

        textures = {f.texture for el in baked.elements for f in el.faces.values()}
        # Verify that chains and top bar have dedicated material slots
        self.assertIn("minecraft:block/iron_chain", textures)
        self.assertIn("minecraft:block/stripped_oak_log", textures)
        self.assertIn("minecraft:entity/signs/hanging/oak", textures)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

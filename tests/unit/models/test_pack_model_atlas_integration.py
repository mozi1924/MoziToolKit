"""
Test Resource Pack Model and UV Detection into Atlas JSON and Yefira Integration.
"""

import sys
import unittest
import tempfile
import zipfile
import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from PIL import Image

# Bootstrap MoziToolKit package (also activates the isolated test sandbox)
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from utils.materials.atlas.generator import AtlasGenerator
from utils.materials.constants import FACE_ORDER


class TestPackModelAtlasIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.pack_zip = self.root / "custom_pack.zip"
        self.atlas_dir = self.root / "atlas_out"

        # Build a mock resource pack with custom blockstates, custom models, and custom textures
        with zipfile.ZipFile(self.pack_zip, "w") as zf:
            # 1. Custom PNG textures
            # Create a 16x16 red image for observer front
            img_front = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
            # Create a 16x16 green image for observer top
            img_top = Image.new("RGBA", (16, 16), (0, 255, 0, 255))
            # Create a 16x16 blue image for observer side
            img_side = Image.new("RGBA", (16, 16), (0, 0, 255, 255))
            # Create a 16x16 yellow image for observer back
            img_back = Image.new("RGBA", (16, 16), (255, 255, 0, 255))

            for name, img in (
                ("observer_front.png", img_front),
                ("observer_top.png", img_top),
                ("observer_side.png", img_side),
                ("observer_back.png", img_back),
            ):
                img_path = self.root / name
                img.save(img_path)
                zf.write(img_path, f"assets/minecraft/textures/block/{name}")

            # 2. Custom block model with inverted UV [0, 16, 16, 0] on top face
            custom_observer_model = {
                "parent": "minecraft:block/block",
                "textures": {
                    "bottom": "minecraft:block/observer_back",
                    "side": "minecraft:block/observer_side",
                    "top": "minecraft:block/observer_top",
                    "front": "minecraft:block/observer_front",
                },
                "elements": [
                    {
                        "from": [0, 0, 0],
                        "to": [16, 16, 16],
                        "faces": {
                            "down":  {"uv": [0, 0, 16, 16], "texture": "#top", "cullface": "down"},
                            "up":    {"uv": [0, 16, 16, 0], "texture": "#top", "cullface": "up"},
                            "north": {"uv": [0, 0, 16, 16], "texture": "#front", "cullface": "north"},
                            "south": {"uv": [0, 0, 16, 16], "texture": "#bottom", "cullface": "south"},
                            "west":  {"uv": [0, 0, 16, 16], "texture": "#side", "cullface": "west"},
                            "east":  {"uv": [0, 0, 16, 16], "texture": "#side", "cullface": "east"},
                        }
                    }
                ]
            }
            zf.writestr(
                "assets/minecraft/models/block/observer.json",
                json.dumps(custom_observer_model, indent=2)
            )

            # 3. Custom blockstate with 6-way rotations
            custom_observer_state = {
                "variants": {
                    "facing=north": {"model": "minecraft:block/observer"},
                    "facing=south": {"model": "minecraft:block/observer", "y": 180},
                    "facing=east":  {"model": "minecraft:block/observer", "y": 90},
                    "facing=west":  {"model": "minecraft:block/observer", "y": 270},
                    "facing=up":    {"model": "minecraft:block/observer", "x": 270},
                    "facing=down":  {"model": "minecraft:block/observer", "x": 90},
                }
            }
            zf.writestr(
                "assets/minecraft/blockstates/observer.json",
                json.dumps(custom_observer_state, indent=2)
            )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_atlas_generator_bakes_custom_pack_models_and_uvs(self):
        """AtlasGenerator must bake pack blockstates and store UV rotations in atlas_mapping.json."""
        generator = AtlasGenerator(self.pack_zip, max_chunk_size=64)
        outputs = generator.build(self.atlas_dir)

        mapping_path = outputs.get("mapping")
        self.assertIsNotNone(mapping_path)
        self.assertTrue(mapping_path.exists())

        with open(mapping_path, "r", encoding="utf-8") as f:
            mapping = json.load(f)

        # 1. Verify block_states is generated in mapping JSON
        self.assertIn("block_states", mapping)
        block_states = mapping["block_states"]
        self.assertGreater(len(block_states), 0)

        # 2. Check observer[facing=north]
        north_state = block_states.get("minecraft:observer[facing=north]")
        self.assertIsNotNone(north_state, "minecraft:observer[facing=north] must be baked in block_states")
        self.assertTrue(north_state["is_cube"])
        self.assertIn("faces", north_state)

        # Top face (+Y) on observer facing north with inverted UV [0, 16, 16, 0] must have uv_rotation = 180.0°
        top_face = north_state["faces"].get("+Y")
        self.assertIsNotNone(top_face)
        self.assertEqual(top_face["uv_rotation"], 180.0)

        # 3. Check observer[facing=south]
        south_state = block_states.get("minecraft:observer[facing=south]")
        self.assertIsNotNone(south_state)
        top_face_south = south_state["faces"].get("+Y")
        self.assertEqual(top_face_south["uv_rotation"], 0.0)

        # 4. Check observer[facing=east]
        east_state = block_states.get("minecraft:observer[facing=east]")
        self.assertIsNotNone(east_state)
        top_face_east = east_state["faces"].get("+Y")
        self.assertEqual(top_face_east["uv_rotation"], 270.0)

        # 5. Check observer[facing=west]
        west_state = block_states.get("minecraft:observer[facing=west]")
        self.assertIsNotNone(west_state)
        top_face_west = west_state["faces"].get("+Y")
        self.assertEqual(top_face_west["uv_rotation"], 90.0)

        # 6. Check base model in materials
        obs_mat = next((m for m in mapping.get("materials", []) if "observer" in m.get("name", "")), None)
        self.assertIsNotNone(obs_mat)
        self.assertIn("+Y", obs_mat["faces"])
        self.assertEqual(obs_mat["faces"]["+Y"]["uv_rotation"], 180.0)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

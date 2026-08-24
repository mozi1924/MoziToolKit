"""
Tests for Entity and Non-Square Texture 2D Bin Packing, Zero-Distortion Guarantee,
and UV Coordinate Remapping.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from PIL import Image

import bpy

from utils.materials.constants import (
    ATLAS_CATEGORY_ENTITIES,
    ATLAS_CATEGORY_PAINTINGS,
    PROP_ATLAS_CHUNK_CATEGORY,
)
from utils.materials.atlas_generator import AtlasGenerator
from utils.materials.atlas_builder import build_atlas_chunk_materials
from utils.materials.atlas_layout import (
    atlas_uv_from_rect,
    local_uv_from_rect,
    remap_local_to_target_uv,
    remap_uv_to_local,
    remap_uv_coordinate,
)


class TestEntityAtlasPacking(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_sample_pack(self, name: str, texture_specs: dict[str, tuple[int, int, tuple[int, int, int, int]]]) -> Path:
        pack_dir = self.work_dir / name
        assets_dir = pack_dir / "assets" / "minecraft" / "textures"

        for rel_path, (w, h, color) in texture_specs.items():
            img_path = assets_dir / f"{rel_path}.png"
            img_path.parent.mkdir(parents=True, exist_ok=True)
            img = Image.new("RGBA", (w, h), color)
            img.save(img_path)

        return pack_dir

    def test_entity_zero_distortion_packing(self):
        """Verify that entities with various rectangular dimensions retain their native dimensions."""
        textures = {
            "entity/creeper/creeper": (64, 32, (0, 200, 0, 255)),
            "entity/boat/oak": (128, 64, (139, 69, 19, 255)),
            "entity/steve": (64, 64, (0, 0, 255, 255)),
            "entity/horse/horse_brown": (128, 128, (160, 82, 45, 255)),
            "painting/kebab": (16, 16, (200, 100, 50, 255)),
            "painting/aztec2": (32, 16, (220, 120, 60, 255)),
            "painting/donkey_kong": (64, 48, (100, 50, 20, 255)),
        }

        pack_path = self._create_sample_pack("EntityPack", textures)
        atlas_out = self.work_dir / "atlas_entity_out"

        gen = AtlasGenerator(pack_path, default_tile_size=16, max_chunk_size=512)
        gen.build(atlas_out)

        mapping_path = atlas_out / "atlas_mapping.json"
        self.assertTrue(mapping_path.exists())

        with open(mapping_path, "r", encoding="utf-8") as f:
            mapping = json.load(f)

        # Verify entity chunks used rect_bin_pack
        entity_chunk = next(c for c in mapping["chunks"] if c["category"] == "entities")
        self.assertEqual(entity_chunk["packing"], "rect_bin_pack")
        self.assertEqual(entity_chunk["kind"], "static")

        # Verify painting chunk used rect_bin_pack
        painting_chunk = next(c for c in mapping["chunks"] if c["category"] == "paintings")
        self.assertEqual(painting_chunk["packing"], "rect_bin_pack")

        textures_map = mapping["textures"]

        # Check Creeper (64x32) preserved exact dimensions
        creeper_loc = textures_map["minecraft:entity/creeper/creeper"]
        self.assertEqual(creeper_loc["rect_width"], 64)
        self.assertEqual(creeper_loc["rect_height"], 32)
        self.assertEqual(creeper_loc["packing"], "rect")

        # Check Boat (128x64) preserved exact dimensions
        boat_loc = textures_map["minecraft:entity/boat/oak"]
        self.assertEqual(boat_loc["rect_width"], 128)
        self.assertEqual(boat_loc["rect_height"], 64)

        # Check Donkey Kong Painting (64x48) preserved exact dimensions
        dk_loc = textures_map["minecraft:painting/donkey_kong"]
        self.assertEqual(dk_loc["rect_width"], 64)
        self.assertEqual(dk_loc["rect_height"], 48)

        # Verify the pixel values in the generated atlas image match the source rectangles exactly
        atlas_img_path = atlas_out / entity_chunk["files"]["albedo"]
        self.assertTrue(atlas_img_path.exists())
        atlas_img = Image.open(atlas_img_path)

        # Check pixel color in creeper region
        cx = creeper_loc["pixel_x"]
        cy = creeper_loc["pixel_y"]
        self.assertEqual(atlas_img.getpixel((cx + 5, cy + 5)), (0, 200, 0, 255))

        # Check pixel color in boat region
        bx = boat_loc["pixel_x"]
        by = boat_loc["pixel_y"]
        self.assertEqual(atlas_img.getpixel((bx + 10, by + 10)), (139, 69, 19, 255))

    def test_entity_uv_remapping_and_inversion(self):
        """Verify that UV remapping for non-square packed textures preserves aspect ratio and inverts losslessly."""
        chunk = {
            "chunk_id": 0,
            "category": "entities",
            "packing": "rect_bin_pack",
            "width": 512,
            "height": 512,
        }
        creeper_loc = {
            "chunk_id": 0,
            "category": "entities",
            "packing": "rect",
            "pixel_x": 128,
            "pixel_y": 64,
            "rect_width": 64,
            "rect_height": 32,
        }

        # Local quad corners (0,0) to (1,1) in texture space
        local_uvs = [
            (0.0, 0.0),
            (1.0, 0.0),
            (1.0, 1.0),
            (0.0, 1.0),
            (0.5, 0.5),
        ]

        for u_loc, v_loc in local_uvs:
            u_atlas, v_atlas = remap_local_to_target_uv(
                u_loc, v_loc,
                target_location=creeper_loc,
                target_chunk=chunk,
            )

            # Invert back to local
            u_inv, v_inv = remap_uv_to_local(
                u_atlas, v_atlas,
                orig_mode="ATLAS_CHUNK",
                old_loc=creeper_loc,
                old_chunk=chunk,
            )

            self.assertAlmostEqual(u_loc, u_inv, places=6)
            self.assertAlmostEqual(v_loc, v_inv, places=6)

            # Verify that atlas bounds match the 64x32 region on 512x512 canvas
            expected_u = (128.0 + u_loc * 64.0) / 512.0
            expected_v = 1.0 - (64.0 + (1.0 - v_loc) * 32.0) / 512.0
            self.assertAlmostEqual(u_atlas, expected_u, places=6)
            self.assertAlmostEqual(v_atlas, expected_v, places=6)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

"""
Unit tests for P0 fixes in MoziToolKit:
1. Seagrass tint classification fix (biome.py)
2. JMC2OBJ candidate extraction & namespace stability (jmc2obj.py)
3. Resource pack deterministic priority resolution (resource_pack.py)
4. Atlas mapping index cache isolation (matching/__init__.py)
5. Face image finder clean fallback (texture_finder.py)
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from utils.system.dependencies import ensure_wheels_in_sys_path
ensure_wheels_in_sys_path()

import bpy
from utils.materials.biome import (
    BiomeResolver,
    TINT_TYPE_NONE,
    TINT_TYPE_GRASS,
    TINT_TYPE_FOLIAGE,
    TINT_TYPE_WATER,
    hex_to_rgb,
    hex_to_rgba,
)
from utils.materials.matching.jmc2obj import (
    jmc2obj_texture_candidates,
)
from utils.materials.resource_pack import (
    texture_category_priority,
)
from utils.materials.matching import (
    _atlas_mapping_index,
    extract_face_texture_info,
)
from utils.materials.texture_finder import (
    find_face_image,
)


class TestP0Fixes(unittest.TestCase):

    def test_seagrass_tint_classification_is_none(self):
        """Verify seagrass and aquatic plants are NOT misclassified as grass tint."""
        resolver = BiomeResolver()

        # Underwater plants that MUST be TINT_TYPE_NONE (0)
        underwater_stems = [
            "seagrass",
            "tall_seagrass_top",
            "tall_seagrass_bottom",
            "tall_seagrass",
            "seagrass_bottom",
            "kelp",
            "kelp_plant",
        ]
        for stem in underwater_stems:
            info = resolver.get_tint_info(stem)
            self.assertEqual(
                info["tint_type"],
                TINT_TYPE_NONE,
                f"Expected '{stem}' to have TINT_TYPE_NONE (0), got {info['tint_type']} ({info['tint_category']})"
            )
            self.assertEqual(info["tint_category"], "none")

        # Legitimate grass stems that MUST be TINT_TYPE_GRASS (1)
        grass_stems = [
            "grass_block_top",
            "grass",
            "short_grass",
            "tall_grass_top",
            "tall_grass_bottom",
            "tall_grass",
            "fern",
            "large_fern_top",
            "large_fern_bottom",
        ]
        for stem in grass_stems:
            info = resolver.get_tint_info(stem)
            self.assertEqual(
                info["tint_type"],
                TINT_TYPE_GRASS,
                f"Expected '{stem}' to have TINT_TYPE_GRASS (1), got {info['tint_type']} ({info['tint_category']})"
            )
            self.assertEqual(info["tint_category"], "grass")

        # Foliage stems that MUST be TINT_TYPE_FOLIAGE (2)
        foliage_stems = [
            "oak_leaves",
            "jungle_leaves",
            "acacia_leaves",
            "dark_oak_leaves",
            "vine",
        ]
        for stem in foliage_stems:
            info = resolver.get_tint_info(stem)
            self.assertEqual(
                info["tint_type"],
                TINT_TYPE_FOLIAGE,
                f"Expected '{stem}' to have TINT_TYPE_FOLIAGE (2), got {info['tint_type']} ({info['tint_category']})"
            )

    def test_hex_to_rgb_and_rgba(self):
        """Verify hex_to_rgb and hex_to_rgba 6-digit and 8-digit handling."""
        # 6-digit
        rgb = hex_to_rgb("#FF8000")
        self.assertAlmostEqual(rgb[0], 1.0, places=2)
        self.assertAlmostEqual(rgb[1], 0.5019, places=2)
        self.assertAlmostEqual(rgb[2], 0.0, places=2)

        # 8-digit RGBA
        rgba = hex_to_rgba("#FF800080")
        self.assertAlmostEqual(rgba[0], 1.0, places=2)
        self.assertAlmostEqual(rgba[1], 0.5019, places=2)
        self.assertAlmostEqual(rgba[2], 0.0, places=2)
        self.assertAlmostEqual(rgba[3], 0.5019, places=2)

    def test_jmc2obj_candidate_extraction_namespace(self):
        """Verify jmc2obj_texture_candidates preserves custom namespaces and generates candidates."""
        mat = bpy.data.materials.new(name="minecraft_block-stone")
        mat.use_nodes = True
        ns, cands = jmc2obj_texture_candidates(mat)
        self.assertEqual(ns, "minecraft")
        self.assertIn("block/stone", cands)
        bpy.data.materials.remove(mat)

        # Modded prefix material
        mat2 = bpy.data.materials.new(name="botania_block-pure_daisy")
        mat2.use_nodes = True
        ns2, cands2 = jmc2obj_texture_candidates(mat2)
        self.assertEqual(ns2, "botania")
        self.assertTrue(any("pure_daisy" in c for c in cands2))
        bpy.data.materials.remove(mat2)

    def test_texture_category_priority(self):
        """Verify deterministic category priority ranking."""
        self.assertEqual(texture_category_priority("block/stone"), 1)
        self.assertEqual(texture_category_priority("item/apple"), 2)
        self.assertEqual(texture_category_priority("items/stick"), 2)
        self.assertEqual(texture_category_priority("entity/zombie/zombie"), 3)
        self.assertEqual(texture_category_priority("painting/kebab"), 4)
        self.assertEqual(texture_category_priority("particle/footprint"), 5)
        self.assertEqual(texture_category_priority("gui/widgets"), 6)

        self.assertLess(
            texture_category_priority("block/chest"),
            texture_category_priority("entity/chest/normal")
        )
        self.assertLess(
            texture_category_priority("block/apple"),
            texture_category_priority("item/apple")
        )

    def test_atlas_mapping_index_cache_safety(self):
        """Verify _atlas_mapping_index does NOT mutate input mapping with non-string/tuple keys."""
        mapping = {
            "chunks": [{"chunk_id": 0, "kind": "static"}],
            "textures": {
                "minecraft:block/stone": {"chunk_id": 0, "texture_id": 1, "texture_key": "minecraft:block/stone"}
            },
            "animations": []
        }
        index = _atlas_mapping_index(mapping)
        self.assertIn((0, 1), index["locations"])
        self.assertEqual(index["locations"][(0, 1)][0], "minecraft:block/stone")

        # Verify mapping dict was not corrupted with tuple keys
        for k in mapping.keys():
            self.assertIsInstance(k, str)

    def test_texture_finder_clean_fallback(self):
        """Verify find_face_image returns None when face material has no image instead of grabbing random images."""
        # Create an unrelated image in bpy.data.images
        dummy_img = bpy.data.images.new(name="UnrelatedEnvironmentHDR", width=128, height=128)

        # Create an object with an empty material
        bpy.ops.mesh.primitive_plane_add()
        obj = bpy.context.active_object
        mat = bpy.data.materials.new(name="NoTextureMaterial")
        obj.data.materials.append(mat)

        poly = obj.data.polygons[0]
        img = find_face_image(poly, obj)
        self.assertIsNone(img, "find_face_image should return None for material without image nodes")

        # Cleanup
        bpy.data.objects.remove(obj)
        bpy.data.materials.remove(mat)
        bpy.data.images.remove(dummy_img)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

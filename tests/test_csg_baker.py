"""
Unit tests for 3D AABB CSG Boolean Baking module in MC Baker.
Tests orthogonal box decomposition, volume conservation, waterlogged element generation,
and StateBaker integration for waterlogged blocks (slabs, stairs, fences).
"""

import unittest
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Bootstrap MoziToolKit package
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from utils.mc_baker import (
    StateBaker,
    ModelParser,
    BlockStateResolver,
    subtract_aabb,
    difference_aabbs,
    bake_waterlogged_elements,
    BakedElement,
    BakedFace,
)
from tests.fixtures.mc_block_fixtures import (
    FIXTURE_BLOCKSTATES,
    FIXTURE_MODELS,
)


def aabb_volume(box: tuple[float, float, float, float, float, float]) -> float:
    """Compute volume of an AABB."""
    return max(0.0, box[3] - box[0]) * max(0.0, box[4] - box[1]) * max(0.0, box[5] - box[2])


class TestCSGBaker(unittest.TestCase):

    def test_subtract_aabb_no_overlap(self):
        """Disjoint boxes should return the original box unaltered."""
        box = (0.0, 0.0, 0.0, 16.0, 16.0, 16.0)
        cut = (20.0, 20.0, 20.0, 30.0, 30.0, 30.0)
        res = subtract_aabb(box, cut)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0], box)

    def test_subtract_aabb_complete_containment(self):
        """If cut completely covers the box, result should be empty."""
        box = (2.0, 2.0, 2.0, 14.0, 14.0, 14.0)
        cut = (0.0, 0.0, 0.0, 16.0, 16.0, 16.0)
        res = subtract_aabb(box, cut)
        self.assertEqual(len(res), 0)

    def test_subtract_aabb_slab_bottom(self):
        """Water box [0..16, 0..16, 0..16] minus bottom slab [0..16, 0..8, 0..16] = top half [0..16, 8..16, 0..16]."""
        water_box = (0.0, 0.0, 0.0, 16.0, 16.0, 16.0)
        slab_bottom = (0.0, 0.0, 0.0, 16.0, 8.0, 16.0)
        res = subtract_aabb(water_box, slab_bottom)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0], (0.0, 8.0, 0.0, 16.0, 16.0, 16.0))
        self.assertAlmostEqual(aabb_volume(res[0]), 16.0 * 8.0 * 16.0)

    def test_subtract_aabb_slab_top(self):
        """Water box [0..16, 0..16, 0..16] minus top slab [0..16, 8..16, 0..16] = bottom half [0..16, 0..8, 0..16]."""
        water_box = (0.0, 0.0, 0.0, 16.0, 16.0, 16.0)
        slab_top = (0.0, 8.0, 0.0, 16.0, 16.0, 16.0)
        res = subtract_aabb(water_box, slab_top)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0], (0.0, 0.0, 0.0, 16.0, 8.0, 16.0))
        self.assertAlmostEqual(aabb_volume(res[0]), 16.0 * 8.0 * 16.0)

    def test_subtract_aabb_stair_cavity(self):
        """Water box minus 2 stair cuboids (base + back) leaves exact top step cavity."""
        water_box = (0.0, 0.0, 0.0, 16.0, 16.0, 16.0)
        stair_base = (0.0, 0.0, 0.0, 16.0, 8.0, 16.0)
        stair_back = (0.0, 8.0, 8.0, 16.0, 16.0, 16.0)

        res = difference_aabbs([water_box], [stair_base, stair_back])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0], (0.0, 8.0, 0.0, 16.0, 16.0, 8.0))
        total_vol = sum(aabb_volume(b) for b in res)
        self.assertAlmostEqual(total_vol, 16.0 * 8.0 * 8.0)

    def test_difference_aabbs_volume_conservation(self):
        """Volume of (Subject) minus (Intersecting Cut) must strictly equal sum of resultant sub-boxes."""
        water_box = (0.0, 0.0, 0.0, 16.0, 16.0, 16.0)
        # Center post of a fence: 4x16x4
        fence_post = (6.0, 0.0, 6.0, 10.0, 16.0, 10.0)
        res = difference_aabbs([water_box], [fence_post])

        orig_vol = aabb_volume(water_box)
        post_vol = aabb_volume(fence_post)
        res_vol = sum(aabb_volume(b) for b in res)

        self.assertAlmostEqual(res_vol, orig_vol - post_vol, places=4)

    def test_bake_waterlogged_elements_faces_and_uvs(self):
        """Verify generated water elements have valid vertices, UVs, and water_still texture."""
        # Mock slab element
        slab_elem = BakedElement(
            from_pos=(0.0, 0.0, 0.0),
            to_pos=(16.0, 8.0, 16.0),
            faces={},
        )
        water_elems = bake_waterlogged_elements([slab_elem], fluid_height=16.0)
        self.assertEqual(len(water_elems), 1)
        w_elem = water_elems[0]
        self.assertEqual(w_elem.from_pos, (0.0, 8.0, 0.0))
        self.assertEqual(w_elem.to_pos, (16.0, 16.0, 16.0))

        # Check 6 faces
        for d in ("east", "west", "up", "down", "south", "north"):
            self.assertIn(d, w_elem.faces)
            f = w_elem.faces[d]
            self.assertEqual(f.texture, "minecraft:block/water_still")
            self.assertEqual(len(f.vertices), 4)
            self.assertEqual(len(f.uvs), 4)
            # All vertices in [0..1] range
            for v in f.vertices:
                for coord in v:
                    self.assertTrue(0.0 <= coord <= 1.0)
            # All UVs in [0..1] range
            for u, v in f.uvs:
                self.assertTrue(0.0 <= u <= 1.0)
                self.assertTrue(0.0 <= v <= 1.0)

    def test_state_baker_waterlogged_integration(self):
        """Verify StateBaker seamlessly produces water elements for waterlogged=true states."""
        parser = ModelParser()
        for k, v in FIXTURE_MODELS.items():
            parser.register_model(k, v)

        # Register a mock slab model and blockstate
        parser.register_model("minecraft:block/oak_slab", {
            "textures": {"bottom": "minecraft:block/oak_planks", "top": "minecraft:block/oak_planks", "side": "minecraft:block/oak_planks"},
            "elements": [
                {"from": [0, 0, 0], "to": [16, 8, 16], "faces": {
                    "down": {"texture": "#bottom", "cullface": "down"},
                    "up": {"texture": "#top"},
                    "north": {"texture": "#side", "cullface": "north"},
                    "south": {"texture": "#side", "cullface": "south"},
                    "west": {"texture": "#side", "cullface": "west"},
                    "east": {"texture": "#side", "cullface": "east"},
                }}
            ]
        })

        resolver = BlockStateResolver()
        resolver.register_blockstate("minecraft:oak_slab", {
            "variants": {
                "type=bottom,waterlogged=false": {"model": "minecraft:block/oak_slab"},
                "type=bottom,waterlogged=true": {"model": "minecraft:block/oak_slab"},
            }
        })

        baker = StateBaker(model_parser=parser, state_resolver=resolver)

        # Non-waterlogged slab
        dry_slab = baker.bake_block_state("minecraft:oak_slab[type=bottom,waterlogged=false]")
        self.assertEqual(len(dry_slab.elements), 1)
        self.assertEqual(dry_slab.elements[0].faces["up"].texture, "minecraft:block/oak_planks")

        # Waterlogged slab
        wet_slab = baker.bake_block_state("minecraft:oak_slab[type=bottom,waterlogged=true]")
        # Must have wood element + water element (total 2 elements)
        self.assertEqual(len(wet_slab.elements), 2)
        self.assertFalse(wet_slab.is_opaque)
        # Element 0 is wood slab [0..16, 0..8, 0..16]
        self.assertEqual(wet_slab.elements[0].from_pos, (0.0, 0.0, 0.0))
        self.assertEqual(wet_slab.elements[0].to_pos, (16.0, 8.0, 16.0))
        # Element 1 is water sub-box [0..16, 8..16, 0..16]
        self.assertEqual(wet_slab.elements[1].from_pos, (0.0, 8.0, 0.0))
        self.assertEqual(wet_slab.elements[1].to_pos, (16.0, 16.0, 16.0))
        self.assertEqual(wet_slab.elements[1].faces["up"].texture, "minecraft:block/water_still")

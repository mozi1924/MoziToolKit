"""
Automated unit tests for the Unified Face Culling System (MoziToolKit.Culling).
Verifies canonical alignment with Minecraft 1.21+ Block.shouldRenderFace and BlockBehaviour.skipRendering.
"""

import unittest
from utils.culling import (
    FaceCuller,
    get_shared_face_culler,
    CullCategory,
    LeavesCullMode,
    GlassCullMode,
    FaceOcclusionRect,
    FULL_FACE_RECT,
    EMPTY_FACE_RECT,
    is_face_completely_occluded,
    subtract_rect,
)


class TestFaceCullingSystem(unittest.TestCase):
    """Test suite for FaceCuller rules and shape occlusion tests."""

    def setUp(self):
        self.culler = FaceCuller()
        self.culler.clear_cache()

    def test_2d_rectangle_boolean_subtraction(self):
        """Test subtracting 2D occlusion rectangles."""
        full = FaceOcclusionRect(0.0, 0.0, 1.0, 1.0)
        half_left = FaceOcclusionRect(0.0, 0.0, 0.5, 1.0)
        half_right = FaceOcclusionRect(0.5, 0.0, 1.0, 1.0)

        # Subtract half left from full: remainder should be half right
        remainder = subtract_rect(full, half_left)
        self.assertEqual(len(remainder), 1)
        self.assertAlmostEqual(remainder[0].min_u, 0.5)
        self.assertAlmostEqual(remainder[0].max_u, 1.0)

        # Completely occluding with two halves
        self.assertTrue(is_face_completely_occluded([full], [half_left, half_right]))

        # Partially occluding: half_left alone leaves half unoccluded
        self.assertFalse(is_face_completely_occluded([full], [half_left]))

    def test_solid_opaque_mutual_culling(self):
        """Rule 1: Solid opaque cubes mutually cull touching faces, but render against air."""
        stone_meta = self.culler.get_meta("minecraft:stone")
        dirt_meta = self.culler.get_meta("minecraft:dirt")
        air_meta = self.culler.get_meta("minecraft:air")

        self.assertEqual(stone_meta.category, CullCategory.SOLID_OPAQUE)
        self.assertTrue(stone_meta.has_full_face("east"))

        # Stone touching Dirt on East (+X): Stone East face should be culled
        self.assertFalse(self.culler.should_render_face(stone_meta, dirt_meta, "east"))
        # Dirt touching Stone on West (-X): Dirt West face should be culled
        self.assertFalse(self.culler.should_render_face(dirt_meta, stone_meta, "west"))

        # Stone touching Air: Stone face should be rendered
        self.assertTrue(self.culler.should_render_face(stone_meta, air_meta, "east"))
        self.assertTrue(self.culler.should_render_face(stone_meta, None, "east"))

    def test_glass_translucent_culling(self):
        """Rule 2: Glass culls internal interface with same glass group, culls itself against solid stone, while stone renders against glass."""
        glass_meta = self.culler.get_meta("minecraft:glass")
        red_glass_meta = self.culler.get_meta("minecraft:red_stained_glass")
        stone_meta = self.culler.get_meta("minecraft:stone")

        self.assertEqual(glass_meta.category, CullCategory.GLASS_TRANSLUCENT)

        # 1. Glass touching Glass: mutually culled
        self.assertFalse(self.culler.should_render_face(glass_meta, glass_meta, "east"))
        self.assertFalse(self.culler.should_render_face(glass_meta, glass_meta, "west"))

        # 2. In GROUP mode: Red Stained Glass touching Plain Glass -> culled
        self.culler.glass_cull_mode = GlassCullMode.GROUP
        self.assertFalse(self.culler.should_render_face(red_glass_meta, glass_meta, "east"))

        # 3. In SAME_BLOCK mode: Red Stained Glass touching Plain Glass -> rendered partition
        self.culler.glass_cull_mode = GlassCullMode.SAME_BLOCK
        self.assertTrue(self.culler.should_render_face(red_glass_meta, glass_meta, "east"))

        # 4. Glass touching Stone:
        # Glass touching Stone: Stone has full occlusion -> Glass culls its own face against Stone
        self.assertFalse(self.culler.should_render_face(glass_meta, stone_meta, "east"))
        # Stone touching Glass: Glass has empty occlusion shape -> Stone RENDERS its face against Glass
        self.assertTrue(self.culler.should_render_face(stone_meta, glass_meta, "west"))

    def test_cutout_leaves_modes(self):
        """Rule 3: Leaves culling in Fancy, Single-Face, and Fast modes, and culling against logs."""
        oak_leaves = self.culler.get_meta("minecraft:oak_leaves")
        birch_leaves = self.culler.get_meta("minecraft:birch_leaves")
        oak_log = self.culler.get_meta("minecraft:oak_log")

        self.assertEqual(oak_leaves.category, CullCategory.CUTOUT_LEAVES)

        # 1. Fancy Mode (default): both leaves faces rendered (internal volume visible)
        self.culler.leaves_cull_mode = LeavesCullMode.FANCY
        self.assertTrue(self.culler.should_render_face(oak_leaves, birch_leaves, "east"))
        self.assertTrue(self.culler.should_render_face(birch_leaves, oak_leaves, "west"))

        # 2. Single-Face Mode: exactly one face rendered between touching leaves
        self.culler.leaves_cull_mode = LeavesCullMode.SINGLE_FACE
        pos_a = (0, 0, 0)
        pos_b = (1, 0, 0)
        render_a = self.culler.should_render_face(
            oak_leaves, oak_leaves, "east", block_pos=pos_a, neighbor_pos=pos_b
        )
        render_b = self.culler.should_render_face(
            oak_leaves, oak_leaves, "west", block_pos=pos_b, neighbor_pos=pos_a
        )
        # Exactly one of them should be True and the other False!
        self.assertNotEqual(render_a, render_b)
        self.assertTrue(render_a or render_b)

        # 3. Fast Mode: mutually culled
        self.culler.leaves_cull_mode = LeavesCullMode.FAST
        self.assertFalse(self.culler.should_render_face(oak_leaves, birch_leaves, "east"))
        self.assertFalse(self.culler.should_render_face(birch_leaves, oak_leaves, "west"))

        # 4. Leaves touching Solid Log:
        # Leaf face against log -> culled (log has full occlusion)
        self.assertFalse(self.culler.should_render_face(oak_leaves, oak_log, "down"))
        # Log face against leaf -> rendered
        self.assertTrue(self.culler.should_render_face(oak_log, oak_leaves, "up"))

    def test_partial_shape_slab_occlusion(self):
        """Rule 4: Slabs 2D face occlusion tests."""
        bottom_slab = self.culler.get_meta("minecraft:oak_slab[type=bottom]")
        top_slab = self.culler.get_meta("minecraft:oak_slab[type=top]")
        stone = self.culler.get_meta("minecraft:stone")

        # Bottom slab on Stone (down direction) -> Stone has full face -> Bottom slab down face is CULLED
        self.assertFalse(self.culler.should_render_face(bottom_slab, stone, "down"))
        # Stone placed above bottom slab (up direction) -> bottom slab up is empty -> Stone RENDERS down face
        self.assertTrue(self.culler.should_render_face(stone, bottom_slab, "down"))

        # Top slab below Stone (up direction) -> Stone has full face -> Top slab up face is CULLED
        self.assertFalse(self.culler.should_render_face(top_slab, stone, "up"))

    def test_fluid_culling(self):
        """Rule 5: Fluid culls against same fluid and solid blocks, renders against air."""
        water = self.culler.get_meta("minecraft:water")
        lava = self.culler.get_meta("minecraft:lava")
        stone = self.culler.get_meta("minecraft:stone")
        air = self.culler.get_meta("minecraft:air")

        self.assertEqual(water.category, CullCategory.FLUID)

        # Water touching Water: culled
        self.assertFalse(self.culler.should_render_face(water, water, "east"))
        # Water touching Lava: rendered (different fluid)
        self.assertTrue(self.culler.should_render_face(water, lava, "east"))
        # Water touching Stone: culled against solid
        self.assertFalse(self.culler.should_render_face(water, stone, "down"))
        # Water touching Air: rendered
        self.assertTrue(self.culler.should_render_face(water, air, "up"))


if __name__ == "__main__":
    unittest.main()

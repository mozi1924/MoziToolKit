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
    def test_quad_face_occlusion_rect_extraction(self):
        """Test extracting 2D occlusion rects directly from 3D quad vertices."""
        from utils.culling import extract_quad_face_occlusion_rect

        # Top face of a bottom half slab (Y=0.5 plane) -> Not on Y=1 outer boundary -> None
        slab_top_inner = [(0.0, 0.5, 0.0), (0.0, 0.5, 1.0), (1.0, 0.5, 1.0), (1.0, 0.5, 0.0)]
        self.assertIsNone(extract_quad_face_occlusion_rect(slab_top_inner, "up"))

        # Bottom face of a bottom half slab (Y=0.0 plane) -> Full 2D face on boundary
        slab_bottom_outer = [(0.0, 0.0, 1.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0)]
        rect = extract_quad_face_occlusion_rect(slab_bottom_outer, "down")
        self.assertIsNotNone(rect)
        self.assertTrue(rect.is_full)

        # Partial element: East face half-width quad at X=1.0 plane
        quad_half_east = [(1.0, 0.5, 1.0), (1.0, 0.0, 1.0), (1.0, 0.0, 0.0), (1.0, 0.5, 0.0)]
        rect_east = extract_quad_face_occlusion_rect(quad_half_east, "east")
        self.assertIsNotNone(rect_east)
        self.assertAlmostEqual(rect_east.min_v, 0.0)
        self.assertAlmostEqual(rect_east.max_v, 0.5)

    def test_quad_level_element_culling(self):
        """Test that passing quad_face_shape allows fine-grained element quad culling."""
        stone = self.culler.get_meta("minecraft:stone")
        slab_top = self.culler.get_meta("minecraft:oak_slab[type=top]")

        # A partial element quad on bottom boundary
        partial_bottom_quad = FaceOcclusionRect(0.0, 0.0, 1.0, 0.5)

        # When touching a solid stone below (down direction), the partial quad is completely occluded by stone's full top face
        self.assertFalse(self.culler.should_render_face(
            slab_top, stone, "down", quad_face_shape=[partial_bottom_quad]
        ))

        # When touching an empty air below, the partial quad is visible
        air = self.culler.get_meta("minecraft:air")
        self.assertTrue(self.culler.should_render_face(
            slab_top, air, "down", quad_face_shape=[partial_bottom_quad]
        ))


    def test_non_full_blocks_do_not_cull_glass_or_solid_faces(self):
        """Rule 6: Non-full blocks (fences, panes, walls, trapdoors, doors, carpets, torches, etc.) do NOT cull adjacent glass or stone faces."""
        glass_meta = self.culler.get_meta("minecraft:glass")
        stone_meta = self.culler.get_meta("minecraft:stone")

        non_full_blocks = [
            "minecraft:oak_fence",
            "minecraft:spruce_fence_gate",
            "minecraft:glass_pane",
            "minecraft:white_stained_glass_pane",
            "minecraft:red_stained_glass_pane",
            "minecraft:iron_bars",
            "minecraft:cobblestone_wall",
            "minecraft:stone_brick_wall",
            "minecraft:oak_trapdoor",
            "minecraft:iron_trapdoor",
            "minecraft:oak_door",
            "minecraft:iron_door",
            "minecraft:white_carpet",
            "minecraft:moss_carpet",
            "minecraft:chest",
            "minecraft:trapped_chest",
            "minecraft:ender_chest",
            "minecraft:torch",
            "minecraft:lantern",
            "minecraft:soul_lantern",
            "minecraft:chain",
            "minecraft:lightning_rod",
            "minecraft:end_rod",
            "minecraft:flower_pot",
            "minecraft:conduit",
            "minecraft:bell",
            "minecraft:anvil",
            "minecraft:cauldron",
            "minecraft:hopper",
            "minecraft:brewing_stand",
            "minecraft:scaffolding",
            "minecraft:pointed_dripstone",
        ]

        for block_name in non_full_blocks:
            n_meta = self.culler.get_meta(block_name)

            # 1. Non-full block placed on top of Glass -> Glass UP face MUST render
            render_glass_up = self.culler.should_render_face(glass_meta, n_meta, "up")
            self.assertTrue(
                render_glass_up,
                f"Glass top face was erroneously culled under non-full block: {block_name}"
            )

            # 2. Non-full block placed on top of Stone -> Stone UP face MUST render
            render_stone_up = self.culler.should_render_face(stone_meta, n_meta, "up")
            self.assertTrue(
                render_stone_up,
                f"Stone top face was erroneously culled under non-full block: {block_name}"
            )

            # 3. Non-full block placed to the side (East) of Glass -> Glass East face MUST render
            render_glass_east = self.culler.should_render_face(glass_meta, n_meta, "east")
            self.assertTrue(
                render_glass_east,
                f"Glass east face was erroneously culled next to non-full block: {block_name}"
            )

            # 4. Non-full block placed to the side (East) of Stone -> Stone East face MUST render
            render_stone_east = self.culler.should_render_face(stone_meta, n_meta, "east")
            self.assertTrue(
                render_stone_east,
                f"Stone east face was erroneously culled next to non-full block: {block_name}"
            )

    def test_glass_pane_and_stained_glass_pane_do_not_skip_rendering_with_glass_block(self):
        """Rule 7: Glass panes and stained glass panes must not skip rendering when touching full glass blocks."""
        glass = self.culler.get_meta("minecraft:glass")
        red_glass = self.culler.get_meta("minecraft:red_stained_glass")
        pane = self.culler.get_meta("minecraft:glass_pane")
        red_pane = self.culler.get_meta("minecraft:red_stained_glass_pane")
        white_pane = self.culler.get_meta("minecraft:white_stained_glass_pane")

        # Glass against glass pane in any direction must render
        self.assertTrue(self.culler.should_render_face(glass, pane, "up"))
        self.assertTrue(self.culler.should_render_face(glass, red_pane, "up"))
        self.assertTrue(self.culler.should_render_face(glass, white_pane, "up"))
        self.assertTrue(self.culler.should_render_face(red_glass, pane, "east"))
        self.assertTrue(self.culler.should_render_face(red_glass, red_pane, "east"))

    def test_double_slab_and_stairs_culling(self):
        """Rule 8: Double slab behaves as solid cube; stairs have directional occlusion."""
        stone = self.culler.get_meta("minecraft:stone")
        glass = self.culler.get_meta("minecraft:glass")
        double_slab = self.culler.get_meta("minecraft:oak_slab[type=double]")
        stairs_bottom = self.culler.get_meta("minecraft:oak_stairs[facing=north,half=bottom]")
        stairs_top = self.culler.get_meta("minecraft:oak_stairs[facing=north,half=top]")

        # Double slab is solid cube:
        self.assertEqual(double_slab.category, CullCategory.SOLID_OPAQUE)
        self.assertTrue(double_slab.has_full_face("up"))
        self.assertTrue(double_slab.has_full_face("down"))
        # Double slab touching Stone: mutually culled
        self.assertFalse(self.culler.should_render_face(double_slab, stone, "east"))
        self.assertFalse(self.culler.should_render_face(stone, double_slab, "west"))
        # Double slab above Glass: Glass top face is culled (double slab bottom is full solid)
        self.assertFalse(self.culler.should_render_face(glass, double_slab, "up"))

        # Bottom stairs above Stone: stairs bottom is full solid, so Stone top face is culled
        self.assertFalse(self.culler.should_render_face(stone, stairs_bottom, "up"))
        # Top stairs above Stone: stairs bottom is not full, so Stone top face MUST render
        self.assertTrue(self.culler.should_render_face(stone, stairs_top, "up"))

    def test_culling_with_state_baker_models(self):
        """Rule 9: Validates that metadata built with StateBaker models maintains proper face visibility."""
        from utils.mc_baker import StateBaker
        baker = StateBaker()

        glass_baked = baker.bake_block_state("minecraft:glass")
        stone_baked = baker.bake_block_state("minecraft:stone")
        fence_baked = baker.bake_block_state("minecraft:oak_fence")
        pane_baked = baker.bake_block_state("minecraft:glass_pane")
        stained_pane_baked = baker.bake_block_state("minecraft:white_stained_glass_pane")
        wall_baked = baker.bake_block_state("minecraft:cobblestone_wall")
        trapdoor_baked = baker.bake_block_state("minecraft:oak_trapdoor")
        carpet_baked = baker.bake_block_state("minecraft:white_carpet")

        meta_glass = self.culler.get_meta("minecraft:glass", baked_model=glass_baked)
        meta_stone = self.culler.get_meta("minecraft:stone", baked_model=stone_baked)
        meta_fence = self.culler.get_meta("minecraft:oak_fence", baked_model=fence_baked)
        meta_pane = self.culler.get_meta("minecraft:glass_pane", baked_model=pane_baked)
        meta_stained_pane = self.culler.get_meta("minecraft:white_stained_glass_pane", baked_model=stained_pane_baked)
        meta_wall = self.culler.get_meta("minecraft:cobblestone_wall", baked_model=wall_baked)
        meta_trapdoor = self.culler.get_meta("minecraft:oak_trapdoor", baked_model=trapdoor_baked)
        meta_carpet = self.culler.get_meta("minecraft:white_carpet", baked_model=carpet_baked)

        # Glass under non-full blocks with baked models MUST render
        self.assertTrue(self.culler.should_render_face(meta_glass, meta_fence, "up"))
        self.assertTrue(self.culler.should_render_face(meta_glass, meta_pane, "up"))
        self.assertTrue(self.culler.should_render_face(meta_glass, meta_stained_pane, "up"))
        self.assertTrue(self.culler.should_render_face(meta_glass, meta_wall, "up"))
        self.assertTrue(self.culler.should_render_face(meta_glass, meta_trapdoor, "up"))
        self.assertTrue(self.culler.should_render_face(meta_glass, meta_carpet, "up"))

        # Stone under non-full blocks with baked models MUST render
        self.assertTrue(self.culler.should_render_face(meta_stone, meta_fence, "up"))
        self.assertTrue(self.culler.should_render_face(meta_stone, meta_pane, "up"))
        self.assertTrue(self.culler.should_render_face(meta_stone, meta_stained_pane, "up"))
        self.assertTrue(self.culler.should_render_face(meta_stone, meta_wall, "up"))
        self.assertTrue(self.culler.should_render_face(meta_stone, meta_trapdoor, "up"))
        self.assertTrue(self.culler.should_render_face(meta_stone, meta_carpet, "up"))

    def test_culler_cache_fifo_eviction(self):
        """Rule 10: Verify FIFO eviction maintains bounded cache when exceeding limit."""
        # Populate cache with dummy entries up to 8192
        for i in range(8192):
            self.culler._meta_cache[f"dummy:state_{i}"] = None  # type: ignore

        self.assertEqual(len(self.culler._meta_cache), 8192)

        # Getting a new state should evict oldest (dummy:state_0) and insert new
        self.culler.get_meta("minecraft:emerald_block")
        self.assertEqual(len(self.culler._meta_cache), 8192)
        self.assertNotIn("dummy:state_0", self.culler._meta_cache)
        self.assertIn("minecraft:emerald_block", self.culler._meta_cache)


if __name__ == "__main__":
    unittest.main()




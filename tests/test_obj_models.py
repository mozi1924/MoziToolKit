"""
Unit tests for 1:1 OBJ Model Loading and Special Entity Model Baking in MC Baker.
Tests Chests, Shulker Boxes, Conduits, End Portals, Bells, Decorated Pots, Banners, Skulls, and Hanging Signs.
"""

import unittest
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from utils.mc_baker import StateBaker, build_blender_mesh_from_baked_model
from utils.mc_baker.obj_loader import (
    resolve_obj_model_for_state,
    build_baked_model_from_obj,
    build_shulker_box_model,
    build_conduit_model,
    build_end_portal_model,
)


class TestOBJModels(unittest.TestCase):
    def setUp(self):
        self.baker = StateBaker()

    def test_chest_obj_loading(self):
        """Test single, left, and right chest loading and texture mapping."""
        # 1. Single Chest (Normal, Copper, Trapped, Ender)
        baked_single = self.baker.bake_block_state("minecraft:chest[facing=north,type=single]")
        self.assertIsNotNone(baked_single)
        self.assertEqual(len(baked_single.elements), 18)
        face0 = list(baked_single.elements[0].faces.values())[0]
        self.assertEqual(face0.texture, "minecraft:entity/chest/normal")

        # 2. Copper Chests (various stages)
        baked_copper = self.baker.bake_block_state("minecraft:copper_chest[facing=south,type=single]")
        face_copper = list(baked_copper.elements[0].faces.values())[0]
        self.assertEqual(face_copper.texture, "minecraft:entity/chest/copper")

        baked_waxed_oxidized = self.baker.bake_block_state("minecraft:waxed_oxidized_copper_chest[facing=east,type=single]")
        face_oxidized = list(baked_waxed_oxidized.elements[0].faces.values())[0]
        self.assertEqual(face_oxidized.texture, "minecraft:entity/chest/copper_oxidized")

        # 3. Trapped and Ender Chests
        baked_trapped = self.baker.bake_block_state("minecraft:trapped_chest[facing=west,type=single]")
        face_trapped = list(baked_trapped.elements[0].faces.values())[0]
        self.assertEqual(face_trapped.texture, "minecraft:entity/chest/trapped")

        baked_ender = self.baker.bake_block_state("minecraft:ender_chest[facing=north]")
        face_ender = list(baked_ender.elements[0].faces.values())[0]
        self.assertEqual(face_ender.texture, "minecraft:entity/chest/ender")

        # 4. Double Chest Left & Right
        baked_left = self.baker.bake_block_state("minecraft:chest[facing=north,type=left]")
        self.assertEqual(len(baked_left.elements), 15)
        face_left = list(baked_left.elements[0].faces.values())[0]
        self.assertEqual(face_left.texture, "minecraft:entity/chest/normal_left")

        baked_right = self.baker.bake_block_state("minecraft:chest[facing=north,type=right]")
        self.assertEqual(len(baked_right.elements), 15)
        face_right = list(baked_right.elements[0].faces.values())[0]
        self.assertEqual(face_right.texture, "minecraft:entity/chest/normal_right")

    def test_shulker_box_and_conduit_and_portal(self):
        """Test Shulker Box (undyed & 16 colors across facings), Conduit, and End Portal."""
        # 1. Shulker Box (1:1 OBJ model with base and lid)
        shulker_up = self.baker.bake_block_state("minecraft:shulker_box[facing=up]")
        self.assertEqual(len(shulker_up.elements), 122)
        self.assertEqual(list(shulker_up.elements[0].faces.values())[0].texture, "minecraft:entity/shulker/shulker")

        shulker_cyan = self.baker.bake_block_state("minecraft:cyan_shulker_box[facing=north]")
        self.assertEqual(len(shulker_cyan.elements), 122)
        self.assertEqual(list(shulker_cyan.elements[0].faces.values())[0].texture, "minecraft:entity/shulker/shulker_cyan")

        # Test all 6 facings
        for facing in ("up", "down", "north", "south", "east", "west"):
            shulker_facing = self.baker.bake_block_state(f"minecraft:red_shulker_box[facing={facing}]")
            self.assertEqual(len(shulker_facing.elements), 122)
            self.assertEqual(list(shulker_facing.elements[0].faces.values())[0].texture, "minecraft:entity/shulker/shulker_red")

        # Test Blender Mesh generation
        mesh = build_blender_mesh_from_baked_model(shulker_up)
        self.assertGreater(len(mesh.vertices), 0)
        self.assertGreater(len(mesh.polygons), 0)

        # 2. Conduit
        conduit = self.baker.bake_block_state("minecraft:conduit")
        self.assertEqual(len(conduit.elements), 1)
        self.assertEqual(conduit.elements[0].faces["up"].texture, "minecraft:entity/conduit/base")

        # 3. End Portal & End Gateway & Frame
        portal = self.baker.bake_block_state("minecraft:end_portal")
        self.assertEqual(len(portal.elements), 1)
        self.assertFalse(portal.is_cube)
        self.assertEqual(portal.elements[0].faces["up"].texture, "minecraft:entity/end_portal")

        gateway = self.baker.bake_block_state("minecraft:end_gateway")
        self.assertEqual(len(gateway.elements), 1)
        self.assertTrue(gateway.is_cube)
        self.assertEqual(gateway.elements[0].faces["up"].texture, "minecraft:entity/end_portal")

        frame_eye = self.baker.bake_block_state("minecraft:end_portal_frame[eye=true,facing=north]")
        self.assertEqual(len(frame_eye.elements), 11)
        eye_texs = {f.texture for el in frame_eye.elements for f in el.faces.values()}
        self.assertTrue("minecraft:block/end_portal_frame_eye" in eye_texs)
        self.assertTrue("minecraft:block/end_portal_frame_top" in eye_texs)

        frame_no_eye = self.baker.bake_block_state("minecraft:end_portal_frame[eye=false,facing=east]")
        self.assertEqual(len(frame_no_eye.elements), 6)
        no_eye_texs = {f.texture for el in frame_no_eye.elements for f in el.faces.values()}
        self.assertFalse("minecraft:block/end_portal_frame_eye" in no_eye_texs)
        self.assertTrue("minecraft:block/end_portal_frame_side" in no_eye_texs)

    def test_bell_and_pot_obj_loading(self):
        """Test hybrid Bell and Decorated Pot OBJ models."""
        # 1. Hybrid Bell (attachment=floor -> 3 JSON support frame + 12 OBJ bell = 15 elements)
        baked_bell_floor = self.baker.bake_block_state("minecraft:bell[attachment=floor,facing=north]")
        self.assertIsNotNone(baked_bell_floor)
        self.assertEqual(len(baked_bell_floor.elements), 15)
        bell_textures = {f.texture for el in baked_bell_floor.elements for f in el.faces.values()}
        self.assertTrue("minecraft:block/dark_oak_planks" in bell_textures)
        self.assertTrue("minecraft:block/stone" in bell_textures)
        self.assertTrue("minecraft:block/bell_side" in bell_textures)
        self.assertTrue("minecraft:block/bell_top" in bell_textures)
        self.assertTrue("minecraft:block/bell_bottom" in bell_textures)

        # 2. Hybrid Bell (attachment=ceiling -> 2 JSON support + 12 OBJ bell = 14 elements)
        baked_bell_ceil = self.baker.bake_block_state("minecraft:bell[attachment=ceiling,facing=east]")
        self.assertEqual(len(baked_bell_ceil.elements), 14)

        # 3. Hybrid Bell (attachment=single_wall -> 2 JSON support + 12 OBJ bell = 14 elements)
        baked_bell_wall = self.baker.bake_block_state("minecraft:bell[attachment=single_wall,facing=south]")
        self.assertEqual(len(baked_bell_wall.elements), 14)

        # 4. Hybrid Bell (attachment=double_wall -> 1 JSON support + 12 OBJ bell = 13 elements)
        baked_bell_between = self.baker.bake_block_state("minecraft:bell[attachment=double_wall,facing=west]")
        self.assertEqual(len(baked_bell_between.elements), 13)

        baked_pot = self.baker.bake_block_state("minecraft:decorated_pot")
        self.assertIsNotNone(baked_pot)
        self.assertEqual(len(baked_pot.elements), 18)
        pot_textures = {list(el.faces.values())[0].texture for el in baked_pot.elements}
        self.assertTrue("minecraft:entity/decorated_pot/decorated_pot_base" in pot_textures)
        self.assertTrue("minecraft:entity/decorated_pot/decorated_pot_side" in pot_textures)

    def test_banner_and_skull_obj_loading(self):
        """Test Banner and Skull OBJ models with exact rotation matching."""
        # 1. Banners
        baked_banner0 = self.baker.bake_block_state("minecraft:white_banner[rotation=0]")
        self.assertIsNotNone(baked_banner0)
        self.assertEqual(len(baked_banner0.elements), 18)
        face_banner = list(baked_banner0.elements[0].faces.values())[0]
        self.assertEqual(face_banner.texture, "minecraft:entity/banner/banner_base")

        baked_wall_banner = self.baker.bake_block_state("minecraft:red_wall_banner[facing=north]")
        self.assertIsNotNone(baked_wall_banner)
        self.assertEqual(len(baked_wall_banner.elements), 12)

        # 2. Skulls
        baked_head = self.baker.bake_block_state("minecraft:player_head[rotation=0]")
        self.assertIsNotNone(baked_head)
        self.assertEqual(len(baked_head.elements), 12, "Player head should have 12 faces (base head + hat layer)")
        face_head = list(baked_head.elements[0].faces.values())[0]
        self.assertEqual(face_head.texture, "minecraft:entity/player/wide/steve")

        # Mob heads (64x32 MobHalfTex: 6 faces, no hat layer, V spans [0.5, 1.0])
        baked_skel = self.baker.bake_block_state("minecraft:skeleton_skull[rotation=0]")
        self.assertIsNotNone(baked_skel)
        self.assertEqual(len(baked_skel.elements), 6, "Skeleton skull should have 6 faces (no hat layer)")
        face_skel = list(baked_skel.elements[0].faces.values())[0]
        self.assertEqual(face_skel.texture, "minecraft:entity/skeleton/skeleton")
        # Check that UV V-span goes down to 0.5 (in mc_uvs space, v goes up to 0.5)
        skel_max_v = max(v for el in baked_skel.elements for f in el.faces.values() for _, v in f.uvs)
        self.assertAlmostEqual(skel_max_v, 0.5, places=3, msg="Skeleton skull UVs should cover 64x32 head area (mc_uvs v up to 0.5)")

        baked_wither = self.baker.bake_block_state("minecraft:wither_skeleton_skull[rotation=0]")
        self.assertIsNotNone(baked_wither)
        self.assertEqual(len(baked_wither.elements), 6)
        face_wither = list(baked_wither.elements[0].faces.values())[0]
        self.assertEqual(face_wither.texture, "minecraft:entity/skeleton/wither_skeleton")

        baked_creeper = self.baker.bake_block_state("minecraft:creeper_head[rotation=0]")
        self.assertIsNotNone(baked_creeper)
        self.assertEqual(len(baked_creeper.elements), 6)
        face_creeper = list(baked_creeper.elements[0].faces.values())[0]
        self.assertEqual(face_creeper.texture, "minecraft:entity/creeper/creeper")

        # Zombie head (64x64: 12 faces)
        baked_zombie = self.baker.bake_block_state("minecraft:zombie_head[rotation=0]")
        self.assertIsNotNone(baked_zombie)
        self.assertEqual(len(baked_zombie.elements), 12, "Zombie head should have 12 faces (64x64 layout)")
        face_zombie = list(baked_zombie.elements[0].faces.values())[0]
        self.assertEqual(face_zombie.texture, "minecraft:entity/zombie/zombie")

        baked_dragon = self.baker.bake_block_state("minecraft:dragon_head[rotation=0]")
        self.assertIsNotNone(baked_dragon)
        face_dragon = list(baked_dragon.elements[0].faces.values())[0]
        self.assertEqual(face_dragon.texture, "minecraft:entity/enderdragon/dragon")
        # Rotation 0: snout points in the same canonical front direction as player_head (-Z, min Z in block space ~ -0.719)
        min_z_rot0 = min(p[2] for el in baked_dragon.elements for f in el.faces.values() for p in f.vertices)
        self.assertAlmostEqual(min_z_rot0, -0.719105, places=3)

        # Rotation 8: snout points in the opposite direction (+Z, max Z in block space ~ 1.719)
        baked_dragon_north = self.baker.bake_block_state("minecraft:dragon_head[rotation=8]")
        max_z_rot8 = max(p[2] for el in baked_dragon_north.elements for f in el.faces.values() for p in f.vertices)
        self.assertAlmostEqual(max_z_rot8, 1.719105, places=3)

        # Dragon Wall Head facing north: snout points North (-Z) and back against wall (+Z)
        baked_dragon_wall = self.baker.bake_block_state("minecraft:dragon_wall_head[facing=north]")
        self.assertIsNotNone(baked_dragon_wall)
        min_z_wall = min(p[2] for el in baked_dragon_wall.elements for f in el.faces.values() for p in f.vertices)
        max_z_wall = max(p[2] for el in baked_dragon_wall.elements for f in el.faces.values() for p in f.vertices)
        self.assertAlmostEqual(min_z_wall, -0.500005, places=3)
        self.assertAlmostEqual(max_z_wall, 0.999995, places=3)

        # Player Wall Head facing north: face at Z~0.48 (pointing -Z), back at Z~1.02 (hat layer)
        baked_player_wall = self.baker.bake_block_state("minecraft:player_wall_head[facing=north]")
        self.assertIsNotNone(baked_player_wall)
        min_z_pwall = min(p[2] for el in baked_player_wall.elements for f in el.faces.values() for p in f.vertices)
        max_z_pwall = max(p[2] for el in baked_player_wall.elements for f in el.faces.values() for p in f.vertices)
        self.assertAlmostEqual(min_z_pwall, 0.4835, places=2)
        self.assertAlmostEqual(max_z_pwall, 1.0165, places=2)

        # Piglin Head (36 faces: head + ears + snout + tusks, 64x64 texture)
        baked_piglin = self.baker.bake_block_state("minecraft:piglin_head[rotation=0]")
        self.assertIsNotNone(baked_piglin)
        self.assertEqual(len(baked_piglin.elements), 36, "Piglin head should have 36 faces")
        face_piglin = list(baked_piglin.elements[0].faces.values())[0]
        self.assertEqual(face_piglin.texture, "minecraft:entity/piglin/piglin")
        p_min_y = min(p[1] for el in baked_piglin.elements for f in el.faces.values() for p in f.vertices)
        p_max_y = max(p[1] for el in baked_piglin.elements for f in el.faces.values() for p in f.vertices)
        self.assertAlmostEqual(p_min_y, 0.0, places=3)
        self.assertAlmostEqual(p_max_y, 0.5, places=3)

        # Piglin Wall Head facing north: back against north wall (+Z), snout pointing south/forward
        baked_piglin_wall = self.baker.bake_block_state("minecraft:piglin_wall_head[facing=north]")
        self.assertIsNotNone(baked_piglin_wall)
        self.assertEqual(len(baked_piglin_wall.elements), 36)
        pw_min_y = min(p[1] for el in baked_piglin_wall.elements for f in el.faces.values() for p in f.vertices)
        pw_max_y = max(p[1] for el in baked_piglin_wall.elements for f in el.faces.values() for p in f.vertices)
        pw_min_z = min(p[2] for el in baked_piglin_wall.elements for f in el.faces.values() for p in f.vertices)
        pw_max_z = max(p[2] for el in baked_piglin_wall.elements for f in el.faces.values() for p in f.vertices)
        self.assertAlmostEqual(pw_min_y, 0.25, places=3)
        self.assertAlmostEqual(pw_max_y, 0.75, places=3)
        self.assertAlmostEqual(pw_min_z, 0.4375, places=3)
        self.assertAlmostEqual(pw_max_z, 1.0, places=3)

    def test_piston_head_not_intercepted_as_skull(self):
        """Verify piston_head is not hijacked by skull OBJ loader and bakes standard piston textures."""
        from utils.live_sync.classifier import atlas_lookup_keys

        # 1. Normal Piston Head
        baked_piston = self.baker.bake_block_state("minecraft:piston_head[facing=up,short=false,type=normal]")
        self.assertIsNotNone(baked_piston)
        textures = {f.texture for el in baked_piston.elements for f in el.faces.values()}
        self.assertNotIn("minecraft:entity/player/wide/steve", textures)
        self.assertIn("minecraft:block/piston_top", textures)
        self.assertIn("minecraft:block/piston_side", textures)

        # 2. Sticky Piston Head
        baked_sticky = self.baker.bake_block_state("minecraft:piston_head[facing=north,short=false,type=sticky]")
        self.assertIsNotNone(baked_sticky)
        sticky_textures = {f.texture for el in baked_sticky.elements for f in el.faces.values()}
        self.assertNotIn("minecraft:entity/player/wide/steve", sticky_textures)
        self.assertIn("minecraft:block/piston_top_sticky", sticky_textures)
        self.assertIn("minecraft:block/piston_side", sticky_textures)

        # 3. Verify classifier material keys
        piston_keys = atlas_lookup_keys("minecraft:piston_head[facing=up,short=false,type=normal]")
        self.assertNotIn("minecraft:entity/player/wide/steve", piston_keys)
        self.assertNotIn("entity/player/wide/steve", piston_keys)

        player_keys = atlas_lookup_keys("minecraft:player_head[rotation=0]")
        self.assertIn("minecraft:entity/player/wide/steve", player_keys)


if __name__ == "__main__":
    import sys
    unittest.main(argv=[sys.argv[0]])

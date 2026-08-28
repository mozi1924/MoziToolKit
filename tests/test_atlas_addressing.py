"""
Unit tests for the Unified Authoritative Atlas Addressing System:
- Scene Object Blacklist (Living Mob entities, UI, Map decorations)
- Authoritative AtlasAddressResolver (Static mesh & Dynamic mesh patch)
- mc_baker model baking and custom namespace addressing convention
- HD Pack and Rect Packing UV projection precision
"""

import unittest
from typing import Any
import bpy

from utils.materials.constants import (
    is_scene_blacklisted,
    SCENE_BLACKLIST_CATEGORIES,
    SCENE_BLACKLIST_PREFIXES,
    LIVING_MOB_ENTITY_PREFIXES,
    ALLOWED_SCENE_ENTITY_PREFIXES,
    FALLBACK_TEXTURE_KEY,
)
from utils.materials.atlas.addressing import (
    AtlasAddressResolver,
    ResolvedAtlasAddress,
)
from utils.live_sync.classifier import parse_and_classify
from utils.live_sync.material_manager import LiveSyncMaterialManager, ResolvedFaceTexture
from utils.mc_baker.model_parser import ModelParser
from utils.mc_baker.atlas_bridge import AtlasBridge, ResolvedAtlasFace
from utils.mc_baker.types import BakedFace, BakedModel


class TestSceneObjectBlacklist(unittest.TestCase):
    """Verify authoritative filtering of non-scene items (Living Mobs, UI, Map)."""

    def test_living_mob_entities_blacklisted(self):
        """Living mob entities must be recognized as blacklisted."""
        mobs = [
            "entity/spider/spider",
            "entity/cow/cow",
            "entity/pig/pig",
            "entity/sheep/sheep",
            "entity/chicken/chicken",
            "entity/villager/villager",
            "entity/warden/warden",
            "entity/frog/frog",
            "entity/axolotl/axolotl",
            "entity/breeze/breeze",
            "entity/sniffer/sniffer",
            "entity/allay/allay",
            "textures/entity/spider/spider.png",
        ]
        for mob in mobs:
            self.assertTrue(is_scene_blacklisted(mob), f"Expected {mob} to be blacklisted")

    def test_ui_and_gui_blacklisted(self):
        """User interface and GUI graphics must be blacklisted."""
        ui_textures = [
            "gui/widgets",
            "gui/container/furnace",
            "gui/title/minecraft",
            "textures/gui/toasts.png",
            "widgets/button",
            "hud/hotbar",
            "advancements/backgrounds/stone",
        ]
        for ui in ui_textures:
            self.assertTrue(is_scene_blacklisted(ui), f"Expected {ui} to be blacklisted")

    def test_map_decorations_blacklisted(self):
        """Map graphics and icons must be blacklisted."""
        map_textures = [
            "map/map_icons",
            "map_icons",
            "map_background",
            "textures/map/map_icons.png",
            "map_decorations/target_x",
        ]
        for m in map_textures:
            self.assertTrue(is_scene_blacklisted(m), f"Expected {m} to be blacklisted")

    def test_allowed_placeable_scene_entities_preserved(self):
        """Placeable blocks/props that happen to live under entity/ must NOT be blacklisted."""
        allowed = [
            "entity/chest/normal",
            "entity/chest/trapped",
            "entity/chest/ender",
            "entity/shulker/shulker_top",
            "entity/banner/base",
            "entity/shield/shield_base",
            "entity/decorated_pot/pot",
            "entity/bed/red",
            "entity/bell/bell_body",
            "entity/signs/oak",
            "entity/sign/oak",
            "entity/conduit/conduit",
            "entity/end_portal",
            "entity/end_portal/end_portal",
            "entity/end_gateway",
            "entity/enchanting_table/book",
            "entity/armorstand/wood",
            "painting/kebab",
            # Skulls and Heads
            "entity/skeleton/skeleton",
            "entity/skeleton/wither_skeleton",
            "entity/zombie/zombie",
            "entity/creeper/creeper",
            "entity/piglin/piglin",
            "entity/player/wide/steve",
            "entity/steve",
            "entity/alex",
            "entity/enderdragon/dragon",
        ]
        for item in allowed:
            self.assertFalse(is_scene_blacklisted(item), f"Expected {item} to be allowed in scene")

    def test_standard_blocks_and_items_preserved(self):
        """Blocks and items must never be blacklisted."""
        blocks_and_items = [
            "block/stone",
            "block/dirt",
            "block/furnace_front",
            "minecraft:block/oak_planks",
            "item/diamond_sword",
            "item/apple",
            "custom_pack:block/cogwheel",
        ]
        for b in blocks_and_items:
            self.assertFalse(is_scene_blacklisted(b), f"Expected {b} to be allowed")


class TestAtlasAddressResolver(unittest.TestCase):
    """Verify authoritative lookup and UV projection for static and dynamic mesh paths."""

    def setUp(self):
        self.mock_mapping = {
            "format_version": 2,
            "chunks": [
                {
                    "chunk_id": 0,
                    "kind": "static",
                    "width": 1024,
                    "height": 512,
                    "tile_size": 16,
                    "tiles_per_row": 64,
                },
                {
                    "chunk_id": 1,
                    "kind": "animation",
                    "width": 512,
                    "height": 512,
                    "tile_size": 16,
                },
                {
                    "chunk_id": 2,
                    "kind": "rect_packed",
                    "width": 2048,
                    "height": 2048,
                },
            ],
            "textures": {
                FALLBACK_TEXTURE_KEY: {
                    "chunk_id": 0,
                    "texture_id": 0,
                    "tile_column": 0,
                    "tile_row": 0,
                    "texture_key": FALLBACK_TEXTURE_KEY,
                },
                "minecraft:block/stone": {
                    "chunk_id": 0,
                    "texture_id": 1,
                    "tile_column": 4,
                    "tile_row": 2,
                    "texture_key": "minecraft:block/stone",
                },
                "minecraft:block/furnace_front": {
                    "chunk_id": 0,
                    "texture_id": 2,
                    "tile_column": 3,
                    "tile_row": 1,
                    "texture_key": "minecraft:block/furnace_front",
                },
                "custom_mod:block/cogwheel": {
                    "chunk_id": 0,
                    "texture_id": 3,
                    "tile_column": 5,
                    "tile_row": 2,
                    "texture_key": "custom_mod:block/cogwheel",
                },
                "minecraft:entity/chest/normal": {
                    "chunk_id": 0,
                    "texture_id": 4,
                    "tile_column": 6,
                    "tile_row": 2,
                    "texture_key": "minecraft:entity/chest/normal",
                },
                "minecraft:entity/chest/normal_left": {
                    "chunk_id": 0,
                    "texture_id": 6,
                    "tile_column": 8,
                    "tile_row": 2,
                    "texture_key": "minecraft:entity/chest/normal_left",
                },
                "minecraft:entity/chest/normal_right": {
                    "chunk_id": 0,
                    "texture_id": 7,
                    "tile_column": 9,
                    "tile_row": 2,
                    "texture_key": "minecraft:entity/chest/normal_right",
                },
                # Intentionally present in raw mapping to verify blacklist filtering
                "minecraft:entity/spider/spider": {
                    "chunk_id": 0,
                    "texture_id": 5,
                    "tile_column": 7,
                    "tile_row": 2,
                    "texture_key": "minecraft:entity/spider/spider",
                },
            },
            "animations": [
                {
                    "name": "water_still",
                    "texture_key": "minecraft:block/water_still",
                    "chunk_id": 1,
                    "texture_id": 0,
                    "pixel_x": 32.0,
                    "frame_width": 16.0,
                    "frame_height": 16.0,
                    "frame_count": 32,
                    "frametime": 2,
                    "interpolate": True,
                }
            ],
            "block_states": {
                "minecraft:observer[facing=north]": {
                    "is_cube": True,
                    "faces": {
                        "-Z": {
                            "chunk_id": 0,
                            "texture_id": 10,
                            "tile_column": 8,
                            "tile_row": 2,
                            "uv_rotation": 180.0,
                            "tint_index": -1,
                            "texture_key": "minecraft:block/observer_front",
                        }
                    }
                }
            }
        }
        self.resolver = AtlasAddressResolver(self.mock_mapping)

    def test_lookup_texture_canonical_and_aliases(self):
        """Verify candidate resolution by exact key, short name, and block aliases."""
        # 1. Exact canonical key
        loc_stone = self.resolver.lookup_texture("minecraft:block/stone")
        self.assertIsNotNone(loc_stone)
        self.assertEqual(loc_stone["chunk_id"], 0)
        self.assertEqual(loc_stone["tile_column"], 4)

        # 2. Short name
        loc_furnace = self.resolver.lookup_texture("furnace_front")
        self.assertIsNotNone(loc_furnace)
        self.assertEqual(loc_furnace["tile_column"], 3)

        # 3. Custom namespace model texture
        loc_cog = self.resolver.lookup_texture("custom_mod:block/cogwheel")
        self.assertIsNotNone(loc_cog)
        self.assertEqual(loc_cog["texture_key"], "custom_mod:block/cogwheel")

        # 4. Allowed placeable entity
        loc_chest = self.resolver.lookup_texture("chest")
        self.assertIsNotNone(loc_chest)
        self.assertEqual(loc_chest["texture_key"], "minecraft:entity/chest/normal")

    def test_double_chest_addressing(self):
        """Verify that double chest left and right textures resolve distinctly from normal single chest."""
        loc_left = self.resolver.lookup_texture("entity/chest/normal_left")
        self.assertIsNotNone(loc_left)
        self.assertEqual(loc_left["texture_key"], "minecraft:entity/chest/normal_left")

        loc_right = self.resolver.lookup_texture("entity/chest/normal_right")
        self.assertIsNotNone(loc_right)
        self.assertEqual(loc_right["texture_key"], "minecraft:entity/chest/normal_right")

        # Verify alias lookups
        self.assertEqual(self.resolver.lookup_texture("chest_left")["texture_key"], "minecraft:entity/chest/normal_left")
        self.assertEqual(self.resolver.lookup_texture("chest_right")["texture_key"], "minecraft:entity/chest/normal_right")
        self.assertEqual(self.resolver.lookup_texture("double_chest_left")["texture_key"], "minecraft:entity/chest/normal_left")
        self.assertEqual(self.resolver.lookup_texture("double_chest_right")["texture_key"], "minecraft:entity/chest/normal_right")

    def test_lookup_texture_rejects_blacklisted_items(self):
        """Verify that blacklisted mobs, UI, and maps return None during lookup."""
        self.assertIsNone(self.resolver.lookup_texture("minecraft:entity/spider/spider"))
        self.assertIsNone(self.resolver.lookup_texture("entity/cow/cow"))
        self.assertIsNone(self.resolver.lookup_texture("gui/widgets"))
        self.assertIsNone(self.resolver.lookup_texture("map/map_icons"))

    def test_remap_uv_math(self):
        """Verify mathematically accurate UV projection from local [0..1] to Atlas [0..1]."""
        loc_stone = self.resolver.lookup_texture("minecraft:block/stone")
        chunk_0 = self.mock_mapping["chunks"][0]

        # col=4, row=2, tile_size=16, width=1024, height=512
        # (0, 0) -> U = 4 * 16 / 1024 = 64 / 1024 = 0.0625; V = 1.0 - 3 * 16 / 512 = 1.0 - 48/512 = 0.90625
        u0, v0 = self.resolver.remap_uv(0.0, 0.0, location=loc_stone, chunk=chunk_0)
        self.assertAlmostEqual(u0, 0.0625, places=5)
        self.assertAlmostEqual(v0, 0.90625, places=5)

        # (1, 1) -> U = 5 * 16 / 1024 = 80 / 1024 = 0.078125; V = 1.0 - 2 * 16 / 512 = 1.0 - 32/512 = 0.9375
        u1, v1 = self.resolver.remap_uv(1.0, 1.0, location=loc_stone, chunk=chunk_0)
        self.assertAlmostEqual(u1, 0.078125, places=5)
        self.assertAlmostEqual(v1, 0.9375, places=5)

    def test_dynamic_face_patch_resolution(self):
        """Verify dynamic voxel mesh patch resolves block states, animation timing, and source keys."""
        parsed_stone = parse_and_classify("minecraft:stone")
        res_stone = self.resolver.resolve_dynamic_face(parsed_stone, "east", 0)

        self.assertIsInstance(res_stone, ResolvedAtlasAddress)
        self.assertEqual(res_stone.chunk_id, 0)
        self.assertEqual(res_stone.source_texture_key, "minecraft:block/stone")
        self.assertFalse(res_stone.is_animated)

        # Animated fluid face
        parsed_water = parse_and_classify("minecraft:water")
        res_water = self.resolver.resolve_dynamic_face(parsed_water, "top", 2)
        self.assertEqual(res_water.chunk_id, 1)
        self.assertTrue(res_water.is_animated)
        self.assertEqual(res_water.anim_timing[0], 32.0)  # 32 frames
        self.assertEqual(res_water.anim_timing[1], 2.0)   # frametime 2

        # Pre-baked blockstate with face rotation
        parsed_obs = parse_and_classify("minecraft:observer[facing=north]")
        res_obs = self.resolver.resolve_dynamic_face(parsed_obs, "north", 5)
        self.assertEqual(res_obs.uv_rot, 180.0)
        self.assertEqual(res_obs.source_texture_key, "minecraft:block/observer_front")

    def test_live_sync_material_manager_integration(self):
        """Verify LiveSyncMaterialManager delegates to AtlasAddressResolver cleanly."""
        mesh = bpy.data.meshes.new("TestDynMesh")
        obj = bpy.data.objects.new("TestDynObj", mesh)
        bpy.context.collection.objects.link(obj)

        mat_manager = LiveSyncMaterialManager(world_obj=obj, atlas_params={"mapping": self.mock_mapping})
        parsed_stone = parse_and_classify("minecraft:stone")
        f_res = mat_manager.resolve_block_face(parsed_stone, "east", 0)

        self.assertIsInstance(f_res, ResolvedFaceTexture)
        self.assertEqual(f_res.chunk_id, 0)
        self.assertEqual(f_res.slot_index, 0)
        u, v = f_res.calc_uv_fn(0.0, 1.0)
        self.assertAlmostEqual(u, 0.0625, places=4)
        self.assertAlmostEqual(v, 0.9375, places=4)


class TestCustomModelBakerConvention(unittest.TestCase):
    """Verify convention and namespace handling between mc_baker and Atlas addressing."""

    def test_model_parser_preserves_custom_namespaces(self):
        """ModelParser must not overwrite custom namespaces with minecraft:."""
        parser = ModelParser()

        # Custom mod model IDs
        self.assertEqual(
            parser._normalize_id("create:block/cogwheel"),
            "create:block/cogwheel",
        )
        self.assertEqual(
            parser._normalize_id("create:cogwheel"),
            "create:block/cogwheel",
        )
        self.assertEqual(
            parser._normalize_id("custom_pack:item/wrench"),
            "custom_pack:item/wrench",
        )

        # Vanilla model IDs without namespace default to minecraft:
        self.assertEqual(
            parser._normalize_id("stone"),
            "minecraft:block/stone",
        )
        self.assertEqual(
            parser._normalize_id("block/furnace"),
            "minecraft:block/furnace",
        )

        # Texture variable normalization
        self.assertEqual(
            parser._normalize_texture("custom_mod:block/cog_side"),
            "custom_mod:block/cog_side",
        )
        self.assertEqual(
            parser._normalize_texture("custom_mod:cog_side"),
            "custom_mod:block/cog_side",
        )
        self.assertEqual(
            parser._normalize_texture("#texture_var"),
            "#texture_var",
        )
        self.assertEqual(
            parser._normalize_texture("stone"),
            "minecraft:block/stone",
        )

    def test_atlas_bridge_with_custom_namespaces(self):
        """AtlasBridge must correctly map BakedFace with custom namespace to Atlas."""
        mapping = {
            "chunks": [
                {
                    "chunk_id": 0,
                    "kind": "static",
                    "width": 1024,
                    "height": 1024,
                    "tile_size": 16,
                }
            ],
            "textures": {
                "custom_mod:block/cogwheel": {
                    "chunk_id": 0,
                    "texture_id": 42,
                    "tile_column": 10,
                    "tile_row": 5,
                    "texture_key": "custom_mod:block/cogwheel",
                }
            }
        }

        bridge = AtlasBridge(mapping)
        face = BakedFace(
            direction="east",
            texture="custom_mod:block/cogwheel",
            uv_rot=0.0,
            uv_bounds=(0.0, 0.0, 1.0, 1.0),
            tint_index=-1,
        )

        res_face: ResolvedAtlasFace = bridge.resolve_face(face)
        self.assertEqual(res_face.chunk_id, 0)
        self.assertEqual(res_face.texture_id, 42)
        self.assertEqual(res_face.tile_col, 10)
        self.assertEqual(res_face.tile_row, 5)
        self.assertEqual(res_face.source_texture_key, "custom_mod:block/cogwheel")
        self.assertIsNotNone(res_face.calc_uv_fn)

        u, v = res_face.calc_uv_fn(0.0, 0.0)
        self.assertAlmostEqual(u, 10 * 16 / 1024, places=5)

    def test_unknown_block_fallback_slot(self):
        """Unknown or missing blocks must map to the reserved fallback tile slot without stretching across full atlas."""
        mapping = {
            "chunks": [
                {
                    "chunk_id": 0,
                    "kind": "static",
                    "width": 1024,
                    "height": 512,
                    "tile_size": 16,
                    "tiles_per_row": 64,
                }
            ],
            "textures": {
                FALLBACK_TEXTURE_KEY: {
                    "chunk_id": 0,
                    "texture_id": 0,
                    "tile_column": 0,
                    "tile_row": 0,
                    "pixel_x": 0,
                    "pixel_y": 0,
                    "tile_size": 16,
                    "frame_width": 16,
                    "frame_height": 16,
                    "texture_key": FALLBACK_TEXTURE_KEY,
                }
            }
        }
        resolver = AtlasAddressResolver(mapping)

        # 1. Remap UV with location=None should map to fallback tile
        u0, v0 = resolver.remap_uv(0.0, 0.0, location=None)
        u1, v1 = resolver.remap_uv(1.0, 1.0, location=None)
        self.assertAlmostEqual(u0, 0.0, places=5)
        self.assertAlmostEqual(u1, 16.0 / 1024.0, places=5)
        self.assertAlmostEqual(v0, 1.0 - 16.0 / 512.0, places=5)
        self.assertAlmostEqual(v1, 1.0, places=5)

        # 2. Dynamic face resolution for an unknown block
        from MoziToolKit.utils.live_sync.classifier import parse_and_classify
        parsed = parse_and_classify("unknown_mod:alien_crystal")
        res = resolver.resolve_dynamic_face(parsed, "north", 0)
        self.assertEqual(res.chunk_id, 0)
        self.assertEqual(res.texture_id, 0)

        # Calc UV should map strictly inside the 16x16 fallback tile
        calc_u0, calc_v0 = res.calc_uv_fn(0.0, 0.0)
        calc_u1, calc_v1 = res.calc_uv_fn(1.0, 1.0)
        self.assertAlmostEqual(calc_u0, 0.0, places=5)
        self.assertAlmostEqual(calc_u1, 16.0 / 1024.0, places=5)
        self.assertAlmostEqual(calc_v0, 1.0 - 16.0 / 512.0, places=5)
        self.assertAlmostEqual(calc_v1, 1.0, places=5)


if __name__ == "__main__":
    unittest.main()

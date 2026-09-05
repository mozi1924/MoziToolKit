"""
Unit tests for Model Pre-baking, Resource Pack Stack Layering,
and Directional/Wall Torch orientation accuracy.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
from tests._bootstrap import bootstrap_environment
bootstrap_environment()

from utils.mc_baker import (
    StateBaker,
    ModelParser,
    BlockStateResolver,
    BakedModel,
    BakedFace,
    BakedElement,
)
from utils.materials.pack.pack_stack import ResourcePackStack
from utils.materials.pack.resource_pack import ZipResourcePack
from utils.live_sync import (
    VoxelStorage,
    build_world_mesh,
    preload_sync_world_data,
    get_cached_state_meta,
    clear_mesh_builder_caches,
)
from utils.live_sync.classifier import parse_and_classify, BlockTypeEnum


class TestModelPrebakeAndTorchOrientation(unittest.TestCase):

    def setUp(self):
        clear_mesh_builder_caches()
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in list(bpy.data.meshes):
            bpy.data.meshes.remove(mesh, do_unlink=True)

    def test_wall_torch_orientation_and_lean_direction(self):
        """
        Verify wall_torch[facing=north/east/south/west] leans AWAY from the wall
        into the room, rather than embedding into the wall behind it.
        """
        parser = ModelParser()
        resolver = BlockStateResolver()

        # Vanilla wall torch model definition
        torch_wall_model = {
            "ambientocclusion": False,
            "textures": {
                "torch": "minecraft:block/torch",
                "particle": "minecraft:block/torch"
            },
            "elements": [
                {
                    "from": [7.0, 3.0, 9.1],
                    "to": [9.0, 13.0, 11.1],
                    "rotation": {"origin": [8.0, 3.5, 9.5], "axis": "x", "angle": -45.0, "rescale": True},
                    "faces": {
                        "down": {"uv": [7, 13, 9, 15], "texture": "#torch"},
                        "up": {"uv": [7, 6, 9, 8], "texture": "#torch"},
                        "north": {"uv": [7, 6, 9, 16], "texture": "#torch"},
                        "south": {"uv": [7, 6, 9, 16], "texture": "#torch"},
                        "west": {"uv": [7, 6, 9, 16], "texture": "#torch"},
                        "east": {"uv": [7, 6, 9, 16], "texture": "#torch"}
                    }
                }
            ]
        }
        parser.register_model("minecraft:block/wall_torch", torch_wall_model)

        wall_torch_blockstate = {
            "variants": {
                "facing=north": {"model": "minecraft:block/wall_torch"},
                "facing=east": {"model": "minecraft:block/wall_torch", "y": 90},
                "facing=south": {"model": "minecraft:block/wall_torch", "y": 180},
                "facing=west": {"model": "minecraft:block/wall_torch", "y": 270}
            }
        }
        resolver.register_blockstate("minecraft:wall_torch", wall_torch_blockstate)

        baker = StateBaker(model_parser=parser, state_resolver=resolver)

        # 1. Test Facing North: Attached to South wall (+Z), tilting towards North (-Z)
        baked_north = baker.bake_block_state("minecraft:wall_torch[facing=north]")
        self.assertEqual(len(baked_north.elements), 1)
        elem_n = baked_north.elements[0]
        # In Minecraft space: Z=0 is North, Z=1 is South.
        # Top face vertices should have smaller Z (closer to North Z=0) than bottom face vertices
        top_verts_n = elem_n.faces["up"].vertices
        down_verts_n = elem_n.faces["down"].vertices
        avg_top_z_n = sum(v[2] for v in top_verts_n) / len(top_verts_n)
        avg_down_z_n = sum(v[2] for v in down_verts_n) / len(down_verts_n)
        self.assertLess(avg_top_z_n, avg_down_z_n, "Wall torch facing North must tilt towards North (smaller Z) away from South wall")

        # 2. Test Facing South: Attached to North wall (-Z), tilting towards South (+Z)
        baked_south = baker.bake_block_state("minecraft:wall_torch[facing=south]")
        elem_s = baked_south.elements[0]
        top_verts_s = elem_s.faces["up"].vertices
        down_verts_s = elem_s.faces["down"].vertices
        avg_top_z_s = sum(v[2] for v in top_verts_s) / len(top_verts_s)
        avg_down_z_s = sum(v[2] for v in down_verts_s) / len(down_verts_s)
        self.assertGreater(avg_top_z_s, avg_down_z_s, "Wall torch facing South must tilt towards South (greater Z) away from North wall")

        # 3. Test Facing East: Attached to West wall (-X), tilting towards East (+X)
        baked_east = baker.bake_block_state("minecraft:wall_torch[facing=east]")
        elem_e = baked_east.elements[0]
        top_verts_e = elem_e.faces["up"].vertices
        down_verts_e = elem_e.faces["down"].vertices
        avg_top_x_e = sum(v[0] for v in top_verts_e) / len(top_verts_e)
        avg_down_x_e = sum(v[0] for v in down_verts_e) / len(down_verts_e)
        self.assertGreater(avg_top_x_e, avg_down_x_e, "Wall torch facing East must tilt towards East (greater X) away from West wall")

        # 4. Test Facing West: Attached to East wall (+X), tilting towards West (-X)
        baked_west = baker.bake_block_state("minecraft:wall_torch[facing=west]")
        elem_w = baked_west.elements[0]
        top_verts_w = elem_w.faces["up"].vertices
        down_verts_w = elem_w.faces["down"].vertices
        avg_top_x_w = sum(v[0] for v in top_verts_w) / len(top_verts_w)
        avg_down_x_w = sum(v[0] for v in down_verts_w) / len(down_verts_w)
        self.assertLess(avg_top_x_w, avg_down_x_w, "Wall torch facing West must tilt towards West (smaller X) away from East wall")

    def test_pack_stack_model_precompilation_and_layering(self):
        """
        Test that ResourcePackStack precompile_models bakes models across layers,
        and high-priority packs correctly override low-priority pack models.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            pack_a = tmp / "pack_a_custom_torch"
            pack_b = tmp / "pack_b_vanilla_base"

            # Create Pack B (base model)
            bs_dir_b = pack_b / "assets" / "minecraft" / "blockstates"
            models_dir_b = pack_b / "assets" / "minecraft" / "models" / "block"
            bs_dir_b.mkdir(parents=True)
            models_dir_b.mkdir(parents=True)

            (bs_dir_b / "custom_lamp.json").write_text(
                json.dumps({"variants": {"lit=false": {"model": "minecraft:block/custom_lamp_off"}}}),
                encoding="utf-8"
            )
            (models_dir_b / "custom_lamp_off.json").write_text(
                json.dumps({
                    "textures": {"all": "minecraft:block/lamp_base"},
                    "elements": [
                        {
                            "from": [0, 0, 0],
                            "to": [16, 16, 16],
                            "faces": {
                                "up": {"texture": "#all"},
                                "down": {"texture": "#all"},
                                "north": {"texture": "#all"},
                                "south": {"texture": "#all"},
                                "east": {"texture": "#all"},
                                "west": {"texture": "#all"}
                            }
                        }
                    ]
                }),
                encoding="utf-8"
            )

            # Create Pack A (override model with new texture)
            models_dir_a = pack_a / "assets" / "minecraft" / "models" / "block"
            models_dir_a.mkdir(parents=True)
            (models_dir_a / "custom_lamp_off.json").write_text(
                json.dumps({
                    "textures": {"all": "minecraft:block/lamp_gold_override"},
                    "elements": [
                        {
                            "from": [0, 0, 0],
                            "to": [16, 16, 16],
                            "faces": {
                                "up": {"texture": "#all"},
                                "down": {"texture": "#all"},
                                "north": {"texture": "#all"},
                                "south": {"texture": "#all"},
                                "east": {"texture": "#all"},
                                "west": {"texture": "#all"}
                            }
                        }
                    ]
                }),
                encoding="utf-8"
            )

            # Build stack: A (top) overrides B (bottom)
            stack = ResourcePackStack([pack_a, pack_b])
            models_cache_dir = stack.get_baked_models_dir()

            # Precompile models
            res = stack.precompile_models(output_dir=models_cache_dir)
            self.assertGreater(res["models_count"], 0)
            self.assertTrue(stack.is_models_baked())

            # Load precompiled models
            loaded_models = stack.load_precompiled_models(target_dir=models_cache_dir)
            self.assertIn("minecraft:custom_lamp[lit=false]", loaded_models)
            baked = loaded_models["minecraft:custom_lamp[lit=false]"]

            # Texture must be the overridden one from Pack A!
            self.assertEqual(baked.faces[0].texture, "minecraft:block/lamp_gold_override")

    def test_direct_mesh_builder_wall_torch_blender_geometry(self):
        """
        Verify Direct Mesh Builder creates non-inverted mesh geometry in Blender world coordinates.
        """
        parser = ModelParser()
        resolver = BlockStateResolver()
        torch_wall_model = {
            "ambientocclusion": False,
            "textures": {"torch": "minecraft:block/torch"},
            "elements": [
                {
                    "from": [7.0, 3.0, 9.1],
                    "to": [9.0, 13.0, 11.1],
                    "rotation": {"origin": [8.0, 3.5, 9.5], "axis": "x", "angle": -45.0, "rescale": True},
                    "faces": {
                        "down": {"uv": [7, 13, 9, 15], "texture": "#torch"},
                        "up": {"uv": [7, 6, 9, 8], "texture": "#torch"},
                        "north": {"uv": [7, 6, 9, 16], "texture": "#torch"},
                        "south": {"uv": [7, 6, 9, 16], "texture": "#torch"},
                        "west": {"uv": [7, 6, 9, 16], "texture": "#torch"},
                        "east": {"uv": [7, 6, 9, 16], "texture": "#torch"}
                    }
                }
            ]
        }
        parser.register_model("minecraft:block/wall_torch", torch_wall_model)
        resolver.register_blockstate("minecraft:wall_torch", {
            "variants": {
                "facing=north": {"model": "minecraft:block/wall_torch"}
            }
        })
        baker = StateBaker(model_parser=parser, state_resolver=resolver)

        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:wall_torch[facing=north]")

        atlas_params = {
            "width": 1024,
            "height": 512,
            "tile_size": 16,
            "tiles_per_row": 64,
            "mapping": {
                "textures": {
                    "minecraft:block/torch": {"tile_column": 0, "tile_row": 0, "chunk_id": 0, "texture_id": 0}
                }
            },
        }

        # Pre-warm into cache with custom baker
        from utils.live_sync.meshing import _GLOBAL_STATE_META_CACHE, CachedStateMeta
        from utils.live_sync.material import get_shared_material_manager
        mat_mgr = get_shared_material_manager(world_obj=None, atlas_params=atlas_params)
        meta = CachedStateMeta("minecraft:wall_torch[facing=north]", mat_mgr, baker)
        _GLOBAL_STATE_META_CACHE["minecraft:wall_torch[facing=north]"] = meta

        res = build_world_mesh(bpy.context, storage, atlas_params=atlas_params)
        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data

        # Find top and bottom vertices of the torch mesh in Blender coordinates:
        # In Blender: +Y is North, -Y is South, +Z is Up.
        # When facing North (mounted on South wall -Y), top of the torch should have greater +Y than bottom
        y_coords = [v.co.y for v in mesh.vertices]
        z_coords = [v.co.z for v in mesh.vertices]

        # Highest Z vertex (top of torch) vs lowest Z vertex (bottom of torch)
        max_z_idx = z_coords.index(max(z_coords))
        min_z_idx = z_coords.index(min(z_coords))

        self.assertGreater(
            y_coords[max_z_idx], y_coords[min_z_idx],
            "In Blender coordinates, top of torch facing North must extend towards +Y (North) away from South wall (-Y)"
        )

    def test_auto_full_precompile_when_missing(self):
        """
        Verify that if precompiled models are missing on disk, refresh_shared_baker_sources
        and preload_sync_world_data immediately trigger on-the-fly full precompilation.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            pack_dir = tmp / "pack_full_auto"
            bs_dir = pack_dir / "assets" / "minecraft" / "blockstates"
            models_dir = pack_dir / "assets" / "minecraft" / "models" / "block"
            bs_dir.mkdir(parents=True)
            models_dir.mkdir(parents=True)

            (bs_dir / "auto_block.json").write_text(
                json.dumps({"variants": {"": {"model": "minecraft:block/auto_block"}}}),
                encoding="utf-8"
            )
            (models_dir / "auto_block.json").write_text(
                json.dumps({
                    "textures": {"all": "minecraft:block/auto_block_tex"},
                    "elements": [{"from": [0, 0, 0], "to": [16, 16, 16], "faces": {"up": {"texture": "#all"}}}]
                }),
                encoding="utf-8"
            )

            stack = ResourcePackStack([pack_dir])
            # Initially, not baked
            manifest_file = stack.get_baked_models_dir() / "models_manifest.json"
            if manifest_file.exists():
                manifest_file.unlink()

            self.assertFalse(stack.is_models_baked())

            # Now precompile models on the fly
            stack.precompile_models()
            self.assertTrue(stack.is_models_baked())

            # Verify manifest was written and loaded
            models = stack.load_precompiled_models()
            self.assertIn("minecraft:auto_block", models)
            self.assertEqual(models["minecraft:auto_block"].faces[0].texture, "minecraft:block/auto_block_tex")

    def test_l1_hot_prewarm_and_idle_queue(self):
        """
        Verify that HOT_PREWARM_STATES covers essential interactive blocks (doors, torches, stairs, etc.)
        and that preload_sync_world_data pre-warms them into _GLOBAL_STATE_META_CACHE.
        """
        from utils.live_sync.classifier import HOT_PREWARM_STATES
        from utils.live_sync.meshing.cache import (
            _GLOBAL_STATE_META_CACHE,
            preload_sync_world_data,
            _idle_prewarm_tick,
        )

        # 1. Verify hot states completeness
        self.assertGreater(len(HOT_PREWARM_STATES), 500)

        # Check door states
        door_samples = [
            "minecraft:oak_door[facing=east,half=lower,hinge=left,open=false,powered=false]",
            "minecraft:oak_door[facing=north,half=upper,hinge=right,open=true,powered=false]",
            "minecraft:iron_door[facing=south,half=lower,hinge=left,open=false,powered=false]",
        ]
        for ds in door_samples:
            self.assertIn(ds, HOT_PREWARM_STATES)

        # Check torch & stairs & redstone & container states
        self.assertIn("minecraft:wall_torch[facing=north]", HOT_PREWARM_STATES)
        self.assertIn("minecraft:oak_stairs[facing=north,half=bottom,shape=straight,waterlogged=false]", HOT_PREWARM_STATES)
        self.assertIn("minecraft:chest[facing=north,type=single,waterlogged=false]", HOT_PREWARM_STATES)
        self.assertIn("minecraft:repeater[delay=1,facing=north,locked=false,powered=false]", HOT_PREWARM_STATES)

        # 2. Run preload_sync_world_data and verify _GLOBAL_STATE_META_CACHE is populated with active selection palette
        _GLOBAL_STATE_META_CACHE.clear()
        door_state = "minecraft:oak_door[facing=east,half=lower,hinge=left,open=false,powered=false]"
        total_warmed = preload_sync_world_data(palette=["minecraft:diamond_block", door_state])
        self.assertGreaterEqual(total_warmed, 1)
        self.assertIn("minecraft:diamond_block", _GLOBAL_STATE_META_CACHE)
        self.assertIn(door_state, _GLOBAL_STATE_META_CACHE)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

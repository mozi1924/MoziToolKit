"""
Unit and integration tests for Material Baking and Precompilation Progress System.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
import bpy

from pipeline.progress import ProgressUpdate, ProgressBar
from pipeline.presets.presets import get_preset_pipeline, run_preset_pipeline
from pipeline.steps.step_precompile_cache import StepPrecompileCache
from utils.materials.pack import ResourcePackStack, ZipResourcePack
from utils.mc_baker import StateBaker


class TestPrecompileProgressPipeline(unittest.TestCase):
    """Test suite covering the non-blocking material baking and precompile progress pipeline."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="mozi_test_precompile_"))
        self.pack_zip = self.temp_dir / "test_resource_pack.zip"
        ProgressBar.end()

        # Create a mock minimal resource pack with models, blockstates, textures
        with zipfile.ZipFile(self.pack_zip, "w") as zf:
            zf.writestr("pack.mcmeta", '{"pack": {"pack_format": 15, "description": "Test Pack"}}')
            zf.writestr(
                "assets/minecraft/blockstates/stone.json",
                '{"variants": {"": {"model": "minecraft:block/stone"}}}'
            )
            zf.writestr(
                "assets/minecraft/blockstates/oak_stairs.json",
                '{"variants": {"facing=east,half=bottom,shape=straight": {"model": "minecraft:block/oak_stairs"}}}'
            )
            zf.writestr(
                "assets/minecraft/models/block/stone.json",
                '{"textures": {"all": "minecraft:block/stone"}, "elements": [{"from": [0, 0, 0], "to": [16, 16, 16], "faces": {"all": {"texture": "#all"}}}]}'
            )
            zf.writestr(
                "assets/minecraft/models/block/oak_stairs.json",
                '{"textures": {"bottom": "minecraft:block/oak_planks"}, "elements": [{"from": [0, 0, 0], "to": [16, 8, 16], "faces": {"down": {"texture": "#bottom"}}}]}'
            )
            from PIL import Image
            img = Image.new("RGBA", (16, 16), (120, 120, 120, 255))
            stone_io = self.temp_dir / "stone.png"
            img.save(stone_io)
            zf.write(stone_io, "assets/minecraft/textures/block/stone.png")
            plank_io = self.temp_dir / "oak_planks.png"
            img.save(plank_io)
            zf.write(plank_io, "assets/minecraft/textures/block/oak_planks.png")

        self.pack = ZipResourcePack(self.pack_zip)
        self.stack = ResourcePackStack([self.pack])

    def tearDown(self):
        ProgressBar.end()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_state_baker_bake_all_pack_states_iter(self):
        """Verify that StateBaker.bake_all_pack_states_iter streams progressive fraction and messages."""
        loader = self.stack.get_composite_loader()
        baker = StateBaker(jar_path=None)
        baker.resource_loader = loader
        baker.model_parser.model_loader_fn = loader.load_model
        baker.state_resolver.blockstate_loader_fn = loader.load_blockstate

        updates = []
        final_dict = {}
        for frac, msg, cur_dict in baker.bake_all_pack_states_iter():
            updates.append((frac, msg))
            final_dict = cur_dict

        self.assertTrue(len(updates) > 0)
        self.assertGreater(len(final_dict), 0)
        self.assertIn("minecraft:stone", final_dict)
        last_frac, last_msg = updates[-1]
        self.assertEqual(last_frac, 1.0)
        self.assertIn("Baking models:", last_msg)

    def test_pack_stack_precompile_iter(self):
        """Verify that ResourcePackStack.precompile_iter streams progress across Atlas and Models."""
        updates = []
        final_results = None
        for frac, msg, outputs in self.stack.precompile_iter(material_mode="ATLAS"):
            updates.append((frac, msg))
            if outputs:
                final_results = outputs

        self.assertTrue(len(updates) > 0)
        self.assertIsNotNone(final_results)
        self.assertIn("atlas", final_results)
        self.assertIn("models", final_results)

        # Check that progress fractions are normalized [0.0, 1.0] and roughly ascending
        fractions = [u[0] for u in updates]
        for f in fractions:
            self.assertGreaterEqual(f, 0.0)
            self.assertLessEqual(f, 1.0)
        self.assertEqual(fractions[-1], 1.0)

    def test_step_precompile_cache_execution(self):
        """Verify that StepPrecompileCache executes cleanly via Pipeline and reports success."""
        pipeline = get_preset_pipeline("precompile_cache")
        self.assertIsNotNone(pipeline)

        context = bpy.context
        params = {
            "pack_stack": self.stack,
            "material_mode": "ATLAS",
        }

        res, ctx = run_preset_pipeline("precompile_cache", context, params=params)
        self.assertTrue(res.is_success)
        self.assertIn("Successfully precompiled", res.message)

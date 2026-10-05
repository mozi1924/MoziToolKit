"""
Unit and integration tests for asset precompilation physical progress reporting.
Validates stages (biome, atlas, standalone, models, manifest) emitted across Rust -> Python bridge -> Modal Operator.
"""

import json
import os
import shutil
import struct
import tempfile
import unittest
import zlib
from unittest.mock import MagicMock

from bridge.progress import ProgressReport
from bridge.assets import precompile_stack
from bridge.engine import get_libmtk
from utils.async_task import AsyncTask, ModalTaskRunner
from utils.progress import BlenderProgressReporter


def create_tiny_png(width: int = 16, height: int = 16) -> bytes:
    """Creates a valid 16x16 red PNG using pure Python standard library."""
    raw_data = bytearray()
    for _ in range(height):
        raw_data.append(0)  # Filter type 0: None
        raw_data.extend(b"\xff\x00\x00\xff" * width)
    compressed = zlib.compress(bytes(raw_data))

    def make_chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png += make_chunk(b"IHDR", ihdr)
    png += make_chunk(b"IDAT", compressed)
    png += make_chunk(b"IEND", b"")
    return png


class TestPrecompileProgress(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="mtk_precompile_test_")
        self.pack_dir = os.path.join(self.temp_dir, "test_pack")
        self.cache_dir = os.path.join(self.temp_dir, "cache")
        os.makedirs(self.cache_dir, exist_ok=True)

        # Setup standard pack structure
        tex_dir = os.path.join(self.pack_dir, "assets", "minecraft", "textures", "block")
        models_dir = os.path.join(self.pack_dir, "assets", "minecraft", "models", "block")
        bs_dir = os.path.join(self.pack_dir, "assets", "minecraft", "blockstates")
        os.makedirs(tex_dir, exist_ok=True)
        os.makedirs(models_dir, exist_ok=True)
        os.makedirs(bs_dir, exist_ok=True)

        # 1. Texture
        with open(os.path.join(tex_dir, "stone.png"), "wb") as f:
            f.write(create_tiny_png())

        # 2. Model JSON
        model_json = {
            "textures": {"all": "minecraft:block/stone"},
            "elements": [
                {
                    "from": [0, 0, 0],
                    "to": [16, 16, 16],
                    "faces": {
                        "up": {"texture": "#all", "cullface": "up"},
                        "down": {"texture": "#all", "cullface": "down"},
                        "north": {"texture": "#all", "cullface": "north"},
                        "south": {"texture": "#all", "cullface": "south"},
                        "west": {"texture": "#all", "cullface": "west"},
                        "east": {"texture": "#all", "cullface": "east"},
                    },
                }
            ],
        }
        with open(os.path.join(models_dir, "stone.json"), "w", encoding="utf-8") as f:
            json.dump(model_json, f)

        # 3. Blockstate JSON
        bs_json = {"variants": {"": {"model": "minecraft:block/stone"}}}
        with open(os.path.join(bs_dir, "stone.json"), "w", encoding="utf-8") as f:
            json.dump(bs_json, f)

        # 4. pack.mcmeta
        with open(os.path.join(self.pack_dir, "pack.mcmeta"), "w", encoding="utf-8") as f:
            json.dump({"pack": {"pack_format": 15, "description": "Test Pack"}}, f)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_direct_libmtk_py_precompile_with_callback(self):
        mtk = get_libmtk()
        if mtk is None:
            self.skipTest("libmtk_py not available")

        stack = mtk.ResourcePackStack()
        stack.add_directory_pack(self.pack_dir, "test_pack")
        self.assertEqual(stack.get_pack_count(), 1)

        reports = []

        def on_progress(payload):
            reports.append(payload)

        res = mtk.precompile_all_assets(
            stack,
            self.cache_dir,
            atlas_category="blocks",
            max_atlas_width=1024,
            max_atlas_height=1024,
            compile_atlas=True,
            compile_standalone=True,
            compile_models=True,
            callback=on_progress,
        )

        self.assertTrue(res.success)
        self.assertEqual(res.pack_count, 1)
        self.assertGreaterEqual(res.atlas_chunks, 1)
        self.assertEqual(res.standalone_textures, 1)
        self.assertGreaterEqual(res.baked_models, 1)

        # Verify progress reports were received
        self.assertGreater(len(reports), 0, "No progress reports received")

        stages = [r.get("stage") for r in reports]
        self.assertIn("prebake_biome", stages)
        self.assertIn("prebake_atlas", stages)
        self.assertIn("prebake_standalone", stages)
        self.assertIn("prebake_models", stages)
        self.assertIn("prebake_manifest", stages)

        # Verify last report completed
        last = reports[-1]
        self.assertEqual(last.get("stage"), "prebake_manifest")
        self.assertEqual(last.get("percent"), 100.0)

    def test_bridge_precompile_stack_with_progress_callback(self):
        # Create a mock prefs object with resource_packs pointing to self.pack_dir
        mock_entry = MagicMock()
        mock_entry.enabled = True
        mock_entry.path = self.pack_dir
        mock_entry.name = "test_pack"

        mock_prefs = MagicMock()
        mock_prefs.resource_packs = [mock_entry]
        mock_prefs.cache_dir = self.cache_dir
        mock_prefs.thread_count = 1

        reports = []

        def on_prog(r: ProgressReport):
            self.assertIsInstance(r, ProgressReport)
            reports.append(r)

        res = precompile_stack(
            prefs=mock_prefs,
            num_threads=1,
            progress_callback=on_prog,
        )

        self.assertTrue(res["success"])
        self.assertEqual(res["pack_count"], 1)
        self.assertGreaterEqual(res["atlas_chunks"], 1)
        self.assertEqual(res["standalone_textures"], 1)
        self.assertGreaterEqual(res["baked_models"], 1)

        self.assertGreater(len(reports), 0)
        stages = [r.stage for r in reports]
        self.assertIn("prebake_biome", stages)
        self.assertIn("prebake_atlas", stages)
        self.assertIn("prebake_standalone", stages)
        self.assertIn("prebake_models", stages)
        self.assertIn("prebake_manifest", stages)

    def test_modal_task_runner_precompile_lifecycle(self):
        mock_entry = MagicMock()
        mock_entry.enabled = True
        mock_entry.path = self.pack_dir
        mock_entry.name = "test_pack"

        mock_prefs = MagicMock()
        mock_prefs.resource_packs = [mock_entry]
        mock_prefs.cache_dir = self.cache_dir
        mock_prefs.thread_count = 1

        mock_op = MagicMock()
        mock_ctx = MagicMock()
        mock_wm = MagicMock()
        mock_ws = MagicMock()
        mock_ctx.window_manager = mock_wm
        mock_ctx.workspace = mock_ws

        task = AsyncTask(
            target=precompile_stack,
            kwargs={"prefs": mock_prefs},
        )

        success_result = []

        def on_success(res):
            success_result.append(res)

        reporter = BlenderProgressReporter(context=mock_ctx, total=100, title="Precompile")
        runner = ModalTaskRunner(
            operator=mock_op,
            context=mock_ctx,
            task=task,
            reporter=reporter,
            on_success=on_success,
            title="Precompile",
            force_modal=True,
        )

        ret = runner.start()
        self.assertEqual(ret, {"RUNNING_MODAL"})

        # Pump modal loop until worker finishes
        timer_event = MagicMock()
        timer_event.type = "TIMER"

        status = {"RUNNING_MODAL"}
        iterations = 0
        while status == {"RUNNING_MODAL"} and iterations < 100:
            import time
            time.sleep(0.02)
            status = runner.modal(timer_event)
            iterations += 1

        self.assertEqual(status, {"FINISHED"})
        self.assertEqual(len(success_result), 1)
        self.assertTrue(success_result[0]["success"])
        # Reporter should be closed
        mock_wm.progress_end.assert_called()


if __name__ == "__main__":
    unittest.main()

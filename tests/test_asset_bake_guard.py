"""
Unit and integration tests for intelligent material precompile gating and asset fingerprint matching.
Verifies automated precompilation when asset caches are missing or stale before meshing or material replacement.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import tempfile
import types
import unittest
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

from bridge.assets import (
    get_cache_fingerprint,
    invalidate_asset_cache_memory,
    precompile_stack,
)
from utils.assets import (
    check_asset_cache_status,
    clear_cache,
    ensure_pipeline_assets_ready_sync,
    get_cache_dir,
    run_task_with_asset_guard,
)
from bridge.engine import has_libmtk
from bridge.progress import ProgressReport


def create_tiny_png(width: int = 16, height: int = 16, color: tuple[int, int, int, int] = (255, 0, 0, 255)) -> bytes:
    """Creates a valid 16x16 PNG using pure Python standard library."""
    raw_data = bytearray()
    r, g, b, a = color
    pixel = bytes([r, g, b, a])
    for _ in range(height):
        raw_data.append(0)  # Filter type 0: None
        raw_data.extend(pixel * width)
    compressed = zlib.compress(bytes(raw_data))

    def make_chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png += make_chunk(b"IHDR", ihdr)
    png += make_chunk(b"IDAT", compressed)
    png += make_chunk(b"IEND", b"")
    return png


def setup_mock_pack(pack_dir: str, block_name: str = "stone", color: tuple[int, int, int, int] = (255, 0, 0, 255)) -> None:
    tex_dir = os.path.join(pack_dir, "assets", "minecraft", "textures", "block")
    models_dir = os.path.join(pack_dir, "assets", "minecraft", "models", "block")
    bs_dir = os.path.join(pack_dir, "assets", "minecraft", "blockstates")
    os.makedirs(tex_dir, exist_ok=True)
    os.makedirs(models_dir, exist_ok=True)
    os.makedirs(bs_dir, exist_ok=True)

    with open(os.path.join(tex_dir, f"{block_name}.png"), "wb") as f:
        f.write(create_tiny_png(color=color))

    model_json = {
        "textures": {"all": f"minecraft:block/{block_name}"},
        "elements": [
            {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "faces": {
                    "up": {"texture": "#all"},
                    "down": {"texture": "#all"},
                    "north": {"texture": "#all"},
                    "south": {"texture": "#all"},
                    "west": {"texture": "#all"},
                    "east": {"texture": "#all"},
                },
            }
        ],
    }
    with open(os.path.join(models_dir, f"{block_name}.json"), "w", encoding="utf-8") as f:
        json.dump(model_json, f)

    bs_json = {"variants": {"": {"model": f"minecraft:block/{block_name}"}}}
    with open(os.path.join(bs_dir, f"{block_name}.json"), "w", encoding="utf-8") as f:
        json.dump(bs_json, f)

    with open(os.path.join(pack_dir, "pack.mcmeta"), "w", encoding="utf-8") as f:
        json.dump({"pack": {"pack_format": 15, "description": "Mock Pack"}}, f)


class TestAssetBakeGuard(unittest.TestCase):
    def setUp(self):
        if not has_libmtk():
            self.skipTest("libmtk_py is required for asset bake guard tests")

        self.temp_dir = tempfile.mkdtemp(prefix="mtk_bake_guard_test_")
        self.cache_dir = os.path.join(self.temp_dir, "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        os.environ["MOZI_CACHE_DIR"] = self.cache_dir

        self.pack_a = os.path.join(self.temp_dir, "pack_a")
        self.pack_b = os.path.join(self.temp_dir, "pack_b")
        setup_mock_pack(self.pack_a, block_name="stone", color=(255, 0, 0, 255))
        setup_mock_pack(self.pack_b, block_name="dirt", color=(0, 255, 0, 255))

        invalidate_asset_cache_memory()

    def tearDown(self):
        invalidate_asset_cache_memory()
        os.environ.pop("MOZI_CACHE_DIR", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_prefs(self, pack_paths: list[str]) -> types.SimpleNamespace:
        packs = []
        for p in pack_paths:
            packs.append(types.SimpleNamespace(path=p, enabled=True, name=os.path.basename(p)))
        return types.SimpleNamespace(
            resource_packs=packs,
            cache_dir=self.cache_dir,
            thread_count=0,
        )

    def test_status_no_packs(self):
        """Verifies check_asset_cache_status returns NO_PACKS when no packs are enabled and no cache exists."""
        empty_prefs = types.SimpleNamespace(resource_packs=[], cache_dir=self.cache_dir)
        status = check_asset_cache_status(empty_prefs)
        self.assertEqual(status, "NO_PACKS")

    def test_status_missing_when_not_precompiled(self):
        """Verifies check_asset_cache_status returns MISSING when pack is configured but no .mtkcache exists."""
        prefs_a = self._make_prefs([self.pack_a])
        status = check_asset_cache_status(prefs_a)
        self.assertEqual(status, "MISSING")

    def test_status_ready_after_precompilation(self):
        """Verifies check_asset_cache_status transitions from MISSING to READY after precompile_stack."""
        prefs_a = self._make_prefs([self.pack_a])
        self.assertEqual(check_asset_cache_status(prefs_a), "MISSING")

        # Compile Pack A
        res = precompile_stack(prefs_a)
        self.assertTrue(res["success"])

        # Should now be READY
        status = check_asset_cache_status(prefs_a)
        self.assertEqual(status, "READY")

    def test_status_stale_when_pack_stack_changes(self):
        """Verifies check_asset_cache_status returns STALE when cache exists but resource pack configuration changes."""
        prefs_a = self._make_prefs([self.pack_a])
        precompile_stack(prefs_a)
        self.assertEqual(check_asset_cache_status(prefs_a), "READY")

        # Switch active configuration to Pack B (different content/path -> different fingerprint)
        prefs_b = self._make_prefs([self.pack_b])
        status_b = check_asset_cache_status(prefs_b)
        self.assertEqual(status_b, "STALE")

        # Switch to combined stack [Pack A, Pack B]
        prefs_ab = self._make_prefs([self.pack_a, self.pack_b])
        status_ab = check_asset_cache_status(prefs_ab)
        self.assertEqual(status_ab, "STALE")

    def test_ensure_pipeline_assets_ready_sync(self):
        """Verifies ensure_pipeline_assets_ready_sync automatically bakes MISSING or STALE caches."""
        prefs_a = self._make_prefs([self.pack_a])
        self.assertEqual(check_asset_cache_status(prefs_a), "MISSING")

        # 1. Trigger sync guard on MISSING
        success, old_status = ensure_pipeline_assets_ready_sync(prefs_a)
        self.assertTrue(success)
        self.assertEqual(old_status, "MISSING")
        self.assertEqual(check_asset_cache_status(prefs_a), "READY")

        # 2. Repeated call when READY should return quickly without baking
        success, old_status = ensure_pipeline_assets_ready_sync(prefs_a)
        self.assertTrue(success)
        self.assertEqual(old_status, "READY")

        # 3. Switch to Pack B -> STALE -> automatically bakes and becomes READY
        prefs_b = self._make_prefs([self.pack_b])
        self.assertEqual(check_asset_cache_status(prefs_b), "STALE")
        success, old_status = ensure_pipeline_assets_ready_sync(prefs_b)
        self.assertTrue(success)
        self.assertEqual(old_status, "STALE")
        self.assertEqual(check_asset_cache_status(prefs_b), "READY")

    def test_run_task_with_asset_guard_two_stage_pipeline(self):
        """Verifies run_task_with_asset_guard coordinates 2-stage execution with progress callbacks."""
        prefs_a = self._make_prefs([self.pack_a])
        self.assertEqual(check_asset_cache_status(prefs_a), "MISSING")

        reports: list[ProgressReport] = []

        def target_worker(data_val: int, progress_callback=None):
            if progress_callback:
                progress_callback(ProgressReport(stage="target", message="Target Task", current=1, total=1, percent=100.0))
            return data_val * 42

        # 1. First run: cache is MISSING -> Stage 1 precompile + Stage 2 target
        result, did_precompile = run_task_with_asset_guard(
            target_func=target_worker,
            target_kwargs={"data_val": 2},
            prefs=prefs_a,
            progress_callback=lambda r: reports.append(r),
            task_title="Test Meshing",
        )

        self.assertEqual(result, 84)
        self.assertTrue(did_precompile)
        self.assertEqual(check_asset_cache_status(prefs_a), "READY")

        # Verify progress reports were emitted with [1/2 Precompile] and [2/2 Test Meshing]
        messages = [r.message for r in reports]
        self.assertTrue(any("[1/2 Precompile]" in msg for msg in messages), f"Missing Stage 1 reports: {messages}")
        self.assertTrue(any("[2/2 Test Meshing]" in msg for msg in messages), f"Missing Stage 2 reports: {messages}")

        # 2. Second run: cache is now READY -> did_precompile is False, executes directly
        reports.clear()
        result_fast, did_precompile_fast = run_task_with_asset_guard(
            target_func=target_worker,
            target_kwargs={"data_val": 3},
            prefs=prefs_a,
            progress_callback=lambda r: reports.append(r),
            task_title="Test Meshing",
        )
        self.assertEqual(result_fast, 126)
        self.assertFalse(did_precompile_fast)
        messages_fast = [r.message for r in reports]
        self.assertFalse(any("[1/2 Precompile]" in msg for msg in messages_fast))

    def test_material_pipeline_ensure_stack_precompiled(self):
        """Verifies ensure_stack_precompiled in material pipeline triggers precompilation when STALE."""
        from utils.materials.pipeline import ensure_stack_precompiled

        prefs_a = self._make_prefs([self.pack_a])
        self.assertEqual(check_asset_cache_status(prefs_a), "MISSING")

        # Call ensure_stack_precompiled
        base_dir = ensure_stack_precompiled(prefs_a)
        self.assertEqual(Path(base_dir).resolve(), Path(self.cache_dir).resolve())
        self.assertEqual(check_asset_cache_status(prefs_a), "READY")

        # Now switch to Pack B: ensure_stack_precompiled auto-rebakes for Pack B
        prefs_b = self._make_prefs([self.pack_b])
        self.assertEqual(check_asset_cache_status(prefs_b), "STALE")
        ensure_stack_precompiled(prefs_b)
        self.assertEqual(check_asset_cache_status(prefs_b), "READY")

    def test_replace_material_operator_auto_bakes_when_missing(self):
        """Verifies mozi.replace_material operator auto-bakes when asset cache is MISSING."""
        from operators.op_materials import MOZI_OT_replace_material

        prefs_a = self._make_prefs([self.pack_a])
        self.assertEqual(check_asset_cache_status(prefs_a), "MISSING")

        mock_obj = MagicMock()
        mock_obj.type = "MESH"
        mock_mesh = MagicMock()
        mock_mesh.attributes = {}
        mock_obj.data = mock_mesh

        context = types.SimpleNamespace(
            active_object=mock_obj,
            preferences=types.SimpleNamespace(addons={"MoziToolKit": types.SimpleNamespace(preferences=prefs_a)}),
        )

        class DummyReplaceOp:
            def __init__(self):
                self.report = MagicMock()
                self.reuse_atlas_uvs = True
                self.mode = "ATLAS"
                self.biome_preset = "PLAINS"
                self.origin = "AUTO"

            def execute(self, ctx):
                return MOZI_OT_replace_material.execute(self, ctx)

        op = DummyReplaceOp()

        with patch("operators.op_materials.get_prefs", return_value=prefs_a), \
             patch("operators.op_materials.replace_materials", return_value={"success": True, "face_count": 10, "materials_count": 1}):
            res = op.execute(context)
            self.assertEqual(res, {"FINISHED"})

        # Verifies that asset cache was automatically precompiled and is now READY
        self.assertEqual(check_asset_cache_status(prefs_a), "READY")



if __name__ == "__main__":
    unittest.main()

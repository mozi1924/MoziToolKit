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
    can_execute_asset_pipeline,
    check_asset_cache_status,
    clear_cache,
    ensure_pipeline_assets_ready_sync,
    get_cache_dir,
    has_valid_vanilla_pack,
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

    def test_status_no_vanilla_when_only_resource_pack_or_mod(self):
        """Verifies that configuring ONLY a resource pack or mod JAR returns NO_VANILLA and blocks execution."""
        custom_pack_dir = os.path.join(self.temp_dir, "custom_rp")
        os.makedirs(os.path.join(custom_pack_dir, "assets", "custom_mod", "textures"), exist_ok=True)
        with open(os.path.join(custom_pack_dir, "pack.mcmeta"), "w") as f:
            json.dump({"pack": {"pack_format": 15, "description": "Resource Pack Only"}}, f)

        prefs_only_rp = types.SimpleNamespace(
            resource_packs=[
                types.SimpleNamespace(
                    path=custom_pack_dir,
                    enabled=True,
                    pack_type="RESOURCE_PACK",
                    detected_kind="RESOURCE_PACK",
                    name="CustomRP",
                )
            ],
            cache_dir=self.cache_dir,
            thread_count=0,
        )

        self.assertFalse(has_valid_vanilla_pack(prefs_only_rp))
        can_run, reason = can_execute_asset_pipeline(prefs_only_rp)
        self.assertFalse(can_run)
        self.assertIn("Vanilla Client", reason)
        self.assertEqual(check_asset_cache_status(prefs_only_rp), "NO_VANILLA")

    def test_status_no_vanilla_when_server_jar(self):
        """Verifies that configuring a server JAR (which lacks textures/models) returns NO_VANILLA."""
        server_jar_path = os.path.join(self.temp_dir, "server.jar")
        import zipfile
        with zipfile.ZipFile(server_jar_path, "w") as zf:
            zf.writestr("net/minecraft/bundler/Main.class", b"fake class")
            zf.writestr("META-INF/versions.list", b"1.21")

        prefs_server = types.SimpleNamespace(
            resource_packs=[
                types.SimpleNamespace(
                    path=server_jar_path,
                    enabled=True,
                    pack_type="VANILLA",
                    detected_kind="VANILLA_SERVER",
                    name="ServerJAR",
                )
            ],
            cache_dir=self.cache_dir,
            thread_count=0,
        )

        self.assertFalse(has_valid_vanilla_pack(prefs_server))
        self.assertEqual(check_asset_cache_status(prefs_server), "NO_VANILLA")

    def test_stale_cache_does_not_mask_no_packs_or_no_vanilla(self):
        """Verifies the critical fix: existing .mtkcache files NEVER cause NO_PACKS or NO_VANILLA to return READY."""
        # 1. Precompile a cache with Pack A
        prefs_a = self._make_prefs([self.pack_a])
        ensure_pipeline_assets_ready_sync(prefs_a)
        self.assertEqual(check_asset_cache_status(prefs_a), "READY")

        # 2. Now user removes all packs: must return NO_PACKS, NOT READY!
        empty_prefs = types.SimpleNamespace(resource_packs=[], cache_dir=self.cache_dir, thread_count=0)
        self.assertEqual(check_asset_cache_status(empty_prefs), "NO_PACKS")
        can_run, _ = can_execute_asset_pipeline(empty_prefs)
        self.assertFalse(can_run)

        # 3. A pack stays configured but no longer provides client assets: NO_VANILLA, NOT READY!
        mod_only = os.path.join(self.temp_dir, "mod_only")
        os.makedirs(os.path.join(mod_only, "assets", "mymod", "textures"), exist_ok=True)
        prefs_mod_only = self._make_prefs([mod_only])
        self.assertEqual(check_asset_cache_status(prefs_mod_only), "NO_VANILLA")
        self.assertFalse(has_valid_vanilla_pack(prefs_mod_only))

    def test_gate_rejects_partial_or_mislabeled_vanilla_entries(self):
        """The gate must be content-based: metadata and partial asset trees are not evidence."""
        import zipfile

        # Partial tree: textures only (no models/blockstates) cannot back the bake pipeline.
        partial_dir = os.path.join(self.temp_dir, "partial")
        os.makedirs(os.path.join(partial_dir, "assets", "minecraft", "textures", "block"), exist_ok=True)
        self.assertFalse(has_valid_vanilla_pack(self._make_prefs([partial_dir])))

        # Empty directory merely tagged VANILLA must be rejected.
        empty_dir = os.path.join(self.temp_dir, "empty_vanilla")
        os.makedirs(empty_dir, exist_ok=True)
        empty_entry = types.SimpleNamespace(
            path=empty_dir, enabled=True, pack_type="VANILLA", detected_kind="", name="Empty"
        )
        self.assertFalse(has_valid_vanilla_pack(types.SimpleNamespace(resource_packs=[empty_entry])))

        # A mod JAR tagged VANILLA must be rejected by content classification.
        mod_jar = os.path.join(self.temp_dir, "mod.jar")
        with zipfile.ZipFile(mod_jar, "w") as zf:
            zf.writestr("fabric.mod.json", b"{}")
            zf.writestr("assets/mymod/textures/block.png", b"x")
        mod_entry = types.SimpleNamespace(
            path=mod_jar, enabled=True, pack_type="VANILLA", detected_kind="", name="ModJAR"
        )
        self.assertFalse(has_valid_vanilla_pack(types.SimpleNamespace(resource_packs=[mod_entry])))

    def test_gate_accepts_full_asset_tree_and_client_jar(self):
        """A complete unpacked asset tree or a content-classified client JAR is a valid base."""
        import zipfile

        # Complete unpacked tree (pack.mcmeta is irrelevant; content is what counts).
        self.assertTrue(has_valid_vanilla_pack(self._make_prefs([self.pack_a])))

        client_jar = os.path.join(self.temp_dir, "client.jar")
        with zipfile.ZipFile(client_jar, "w") as zf:
            zf.writestr("version.json", json.dumps({"id": "1.21.1"}))
            zf.writestr("assets/.mcassetsroot", b"")
            zf.writestr("net/minecraft/client/Main.class", b"class")
            for sub in ("blockstates", "models", "textures"):
                zf.writestr(f"assets/minecraft/{sub}/x.json", b"{}")
        client_entry = types.SimpleNamespace(
            path=client_jar, enabled=True, pack_type="VANILLA", detected_kind="", name="ClientJAR"
        )
        self.assertTrue(has_valid_vanilla_pack(types.SimpleNamespace(resource_packs=[client_entry])))

    def test_gate_ignores_environment_when_a_stack_is_configured(self):
        """Environment variables are a CLI fallback, never a rescue for a configured wrong stack."""
        partial_dir = os.path.join(self.temp_dir, "partial_env")
        os.makedirs(os.path.join(partial_dir, "assets", "minecraft", "textures"), exist_ok=True)
        prefs = self._make_prefs([partial_dir])
        with patch.dict(os.environ, {"MC_DIR": self.pack_a, "MTK_TEST_ASSETS": self.pack_a}):
            self.assertFalse(has_valid_vanilla_pack(prefs))

    def test_operators_poll_blocked_when_no_vanilla(self):
        """Verifies operator poll returns False / execute returns CANCELLED without a vanilla base pack."""
        from operators.op_materials import MOZI_OT_replace_material
        from operators.op_precompile import MOZI_OT_precompile_cache

        empty_prefs = types.SimpleNamespace(resource_packs=[], cache_dir=self.cache_dir, thread_count=0)

        # Context mock with empty prefs
        mock_obj = MagicMock()
        mock_obj.type = "MESH"
        mock_mesh = MagicMock()
        mock_mesh.attributes = {}
        mock_obj.data = mock_mesh

        context = types.SimpleNamespace(
            active_object=mock_obj,
            preferences=types.SimpleNamespace(addons={"MoziToolKit": types.SimpleNamespace(preferences=empty_prefs)}),
        )

        with patch("operators.op_materials.get_prefs", return_value=empty_prefs), \
             patch("operators.op_materials.is_external_mesh", return_value=True):
            self.assertFalse(MOZI_OT_replace_material.poll(context))

        with patch("operators.op_precompile.get_prefs", return_value=empty_prefs):
            self.assertFalse(MOZI_OT_precompile_cache.poll(context))

        class _DummyOp:
            def report(self, level, message):
                self.reported = (level, message)

        op = _DummyOp()
        with patch("operators.op_precompile.get_prefs", return_value=empty_prefs):
            self.assertEqual(MOZI_OT_precompile_cache.execute(op, context), {"CANCELLED"})
        self.assertEqual(op.reported[0], {"WARNING"})



if __name__ == "__main__":
    unittest.main()

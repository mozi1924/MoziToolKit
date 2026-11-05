"""
Tests for animated texture routing gates across Save import, refresh, mesh rebuild, and sync.
Verifies that unchecking animated textures correctly forwards enable_animated_textures=False
and addresses the pure static atlas.
"""

from __future__ import annotations

import types
import unittest
from pathlib import Path
from unittest.mock import patch

from MoziToolKit.bridge.world import prepare_world_mesh_context
from MoziToolKit.utils.materials.builder.world_binding import ensure_world_materials


class TestSaveAnimationRouting(unittest.TestCase):
    def test_prepare_world_mesh_context_respects_explicit_override(self):
        """prepare_world_mesh_context must honour explicit enable_animated_textures=False."""
        prefs = types.SimpleNamespace(
            thread_count=4,
            enable_animated_textures=True,  # Global pref is True
        )
        with patch("MoziToolKit.bridge.world.get_world_pipeline_assets", return_value=(object(), object(), object())), \
             patch("MoziToolKit.bridge.world.get_active_cache_package_path", return_value=None), \
             patch("MoziToolKit.bridge.world.get_configured_ctm_solver", return_value=None), \
             patch("MoziToolKit.bridge.world.get_cache_fingerprint", return_value="fp"), \
             patch("MoziToolKit.bridge.world.get_cache_timestamp", return_value=123):

            # Explicit False overrides pref True
            ctx_off = prepare_world_mesh_context(prefs, enable_animated_textures=False)
            self.assertFalse(ctx_off["enable_animated_textures"])

            # Explicit True overrides pref False
            prefs_off = types.SimpleNamespace(thread_count=4, enable_animated_textures=False)
            ctx_on = prepare_world_mesh_context(prefs_off, enable_animated_textures=True)
            self.assertTrue(ctx_on["enable_animated_textures"])

            # Default None falls back to prefs
            ctx_default = prepare_world_mesh_context(prefs)
            self.assertTrue(ctx_default["enable_animated_textures"])

    def test_import_save_async_forwards_animation_disabled(self):
        """op_import_save must forward self.enable_animated_textures=False into the AsyncTask kwargs."""
        from MoziToolKit.operators.save.op_import_save import MTK_OT_import_minecraft_save
        import bpy

        class DummyImportOp:
            def __init__(self):
                self.dimension = "overworld"
                self.min_coord = (-10, 0, -10)
                self.max_coord = (10, 50, 10)
                self.use_yefira_selection = False
                self.enable_ao = True
                self.mesh_fluids = True
                self.weld_vertices = True
                self.origin_centered = True
                self.enable_ctm = False
                self.enable_animated_textures = False  # User unchecked it!
                self.run_async = True
                self.reports = []
                self.report = lambda *args: self.reports.append(args)
                self._runner = None

            def execute(self, ctx):
                return MTK_OT_import_minecraft_save.execute(self, ctx)

        op = DummyImportOp()
        ctx = bpy.context

        mock_path = types.SimpleNamespace(
            is_file=lambda: False,
            exists=lambda: True,
            resolve=lambda: Path("/fake/world"),
        )

        prefs = types.SimpleNamespace(
            thread_count=2,
            enable_animated_textures=True,  # Global pref is True
        )

        captured_task = None

        def fake_runner_init(self_runner, operator, context, task, reporter, on_success, title):
            nonlocal captured_task
            captured_task = task
            self_runner.start = lambda: {"RUNNING_MODAL"}

        with patch("MoziToolKit.operators.save.op_import_save.resolve_operator_world_dir", return_value=mock_path), \
             patch("MoziToolKit.utils.system.dependencies.get_prefs", return_value=prefs), \
             patch("MoziToolKit.operators.save.op_import_save.can_execute_asset_pipeline", return_value=(True, "")), \
             patch("MoziToolKit.operators.save.op_import_save.check_asset_cache_status", return_value="READY"), \
             patch("MoziToolKit.operators.save.op_import_save.prepare_asset_context", return_value={}), \
             patch("MoziToolKit.operators.save.op_import_save.prepare_world_mesh_context", return_value={
                 "model_db": object(),
                 "atlas": object(),
                 "biome_resolver": object(),
                 "ctm_solver": None,
                 "num_threads": 2,
                 "enable_animated_textures": False,
                 "skin_cache_dir": None,
                 "cache_package_path": None,
             }), \
             patch("MoziToolKit.operators.save.op_import_save.ModalTaskRunner.__init__", fake_runner_init):

            res = op.execute(ctx)
            self.assertEqual(res, {"RUNNING_MODAL"})
            self.assertIsNotNone(captured_task)
            task_kwargs = captured_task.kwargs["target_kwargs"]
            # Must be False, NOT prefs' True
            self.assertFalse(task_kwargs["enable_animated_textures"])

    def test_refresh_save_async_forwards_animation_disabled(self):
        """op_refresh_save must forward enable_animated_textures=False into the AsyncTask kwargs."""
        from MoziToolKit.operators.save.op_refresh_save import MOZI_OT_refresh_save_mesh
        import bpy

        save_root = bpy.data.objects.new("Save_World_overworld", None)
        save_root["mtk:is_container"] = True
        save_root["mtk:container_type"] = "SAVE"
        save_root["mozi_save_uuid"] = "test-uuid"
        save_root["mtk_dimension"] = "overworld"
        save_root["mtk_min_coord"] = (-10, 0, -10)
        save_root["mtk_max_coord"] = (10, 50, 10)
        save_root["mtk_enable_ao"] = True
        save_root["mtk_mesh_fluids"] = True
        save_root["mtk_weld_vertices"] = True
        save_root["mtk_origin_centered"] = True
        save_root["mtk_enable_ctm"] = True
        save_root["mtk_enable_animated_textures"] = False  # Save was imported with False
        save_root["mtk_world_name"] = "TestWorld"
        bpy.context.collection.objects.link(save_root)
        bpy.context.view_layer.objects.active = save_root

        class DummyRefreshOp:
            def __init__(self):
                self.reports = []
                self.report = lambda *args: self.reports.append(args)
                self.run_async = True
                self._runner = None

            def execute(self, ctx):
                return MOZI_OT_refresh_save_mesh.execute(self, ctx)

        op = DummyRefreshOp()
        ctx = bpy.context

        prefs = types.SimpleNamespace(
            thread_count=2,
            enable_animated_textures=True,  # Global pref is True
        )

        captured_task = None

        def fake_runner_init(self_runner, operator, context, task, reporter, on_success, title):
            nonlocal captured_task
            captured_task = task
            self_runner.start = lambda: {"RUNNING_MODAL"}

        mock_world_dir = types.SimpleNamespace(exists=lambda: True, resolve=lambda: Path("/fake/world"))
        mock_reg = types.SimpleNamespace(get_world_dir=lambda *args: mock_world_dir)

        try:
            with patch("MoziToolKit.operators.save.op_refresh_save.get_save_registry", return_value=mock_reg), \
                 patch("MoziToolKit.operators.save.op_refresh_save.get_save_properties", return_value=None), \
                 patch("MoziToolKit.operators.save.op_refresh_save.get_prefs", return_value=prefs), \
                 patch("MoziToolKit.operators.save.op_refresh_save.can_execute_asset_pipeline", return_value=(True, "")), \
                 patch("MoziToolKit.operators.save.op_refresh_save.check_asset_cache_status", return_value="READY"), \
                 patch("MoziToolKit.operators.save.op_refresh_save.prepare_asset_context", return_value={}), \
                 patch("MoziToolKit.operators.save.op_refresh_save.prepare_world_mesh_context", return_value={
                     "model_db": object(),
                     "atlas": object(),
                     "biome_resolver": object(),
                     "ctm_solver": None,
                     "num_threads": 2,
                     "enable_animated_textures": False,
                     "skin_cache_dir": None,
                     "cache_package_path": None,
                 }), \
                 patch("MoziToolKit.operators.save.op_refresh_save.ModalTaskRunner.__init__", fake_runner_init):

                res = op.execute(ctx)
                self.assertEqual(res, {"RUNNING_MODAL"})
                self.assertIsNotNone(captured_task)
                task_kwargs = captured_task.kwargs["target_kwargs"]
                self.assertFalse(task_kwargs["enable_animated_textures"])
        finally:
            bpy.data.objects.remove(save_root)

    def test_sync_client_forwards_enable_animated_textures(self):
        """SyncBridgeSession start and start_with_cache must forward enable_animated_textures to MesherConfig."""
        from MoziToolKit.bridge.sync import SyncBridgeSession

        client = SyncBridgeSession()
        config_calls = []

        def fake_config(**kwargs):
            config_calls.append(kwargs)
            return types.SimpleNamespace(**kwargs)

        mock_session = types.SimpleNamespace(
            set_error_callback=lambda cb: None,
            set_progress_callback=lambda cb: None,
            connect=lambda url: None,
        )

        mock_mtk = types.SimpleNamespace(
            LiveSyncSession=lambda *args, **kwargs: mock_session,
            MesherConfig=fake_config,
        )

        with patch("MoziToolKit.bridge.sync.get_libmtk", return_value=mock_mtk), \
             patch("MoziToolKit.utils.system.get_prefs", return_value=types.SimpleNamespace(thread_count=1, enable_animated_textures=False)):

            client.start(url="ws://127.0.0.1:8765", enable_animated_textures=False)
            self.assertTrue(len(config_calls) > 0)
            cfg_kwargs = config_calls[-1]
            self.assertIn("enable_animated_textures", cfg_kwargs)
            self.assertFalse(cfg_kwargs["enable_animated_textures"])

    def test_ensure_world_materials_cleans_unused_slots_when_requested(self):
        """ensure_world_materials with clean_unused_slots=True prunes unreferenced material slots."""
        import bpy

        test_mesh = bpy.data.meshes.new("test_clean_slots_mesh")
        verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (2, 0, 0), (3, 0, 0), (3, 1, 0), (2, 1, 0)]
        faces = [(0, 1, 2, 3), (4, 5, 6, 7)]
        test_mesh.from_pydata(verts, [], faces)
        test_mesh.update()

        mat0 = bpy.data.materials.new("MTK:Atlas:blocks:001")
        mat0["mtk_atlas_chunk_id"] = 0
        mat1_anim = bpy.data.materials.new("MTK:Atlas:blocks:anim:001")
        mat1_anim["mtk_atlas_chunk_id"] = 1

        test_mesh.materials.append(mat0)
        test_mesh.materials.append(mat1_anim)

        test_obj = bpy.data.objects.new("test_clean_slots_obj", test_mesh)
        bpy.context.collection.objects.link(test_obj)

        # When used_chunk_ids is [0] (only static chunk), and clean_unused_slots=True:
        # It must not use the subset fast-path that leaves mat1_anim in test_mesh.materials.
        try:
            fake_dir = Path("/nonexistent/atlas/dir")
            fake_atlas = types.SimpleNamespace(
                get_chunk_info=lambda cid: {
                    "chunk_id": cid,
                    "category": "blocks",
                    "category_chunk_index": cid + 1,
                    "is_animated": False,
                }
            )
            with patch("MoziToolKit.utils.materials.builder.world_binding.ensure_atlas_textures_extracted", return_value=fake_dir), \
                 patch("MoziToolKit.utils.materials.builder.world_binding.load_baked_atlas_from_cache", return_value=fake_atlas):

                ensure_world_materials(test_obj, used_chunk_ids=[0], clean_unused_slots=True)

                # test_mesh.materials must now contain ONLY 1 slot (mat0) and mat1_anim removed!
                self.assertEqual(len(test_mesh.materials), 1)
                self.assertNotIn(mat1_anim, [s.material for s in test_obj.material_slots if s.material])
        finally:
            bpy.data.objects.remove(test_obj)
            bpy.data.meshes.remove(test_mesh)
            bpy.data.materials.remove(mat0)
            bpy.data.materials.remove(mat1_anim)


if __name__ == "__main__":
    unittest.main()

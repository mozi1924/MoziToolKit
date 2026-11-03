"""
Tests for animated texture routing gates across Save import, refresh, mesh rebuild, and sync.
Verifies that unchecking animated textures correctly forwards enable_animated_textures=False
and addresses the pure static atlas.
"""

from __future__ import annotations

import types
import unittest
from unittest.mock import MagicMock, patch

from MoziToolKit.bridge.world import prepare_world_mesh_context
from MoziToolKit.utils.materials.builder.world_binding import ensure_world_materials


class TestSaveAnimationRouting(unittest.TestCase):
    def test_prepare_world_mesh_context_respects_explicit_override(self):
        """prepare_world_mesh_context must honour explicit enable_animated_textures=False."""
        prefs = types.SimpleNamespace(
            thread_count=4,
            enable_animated_textures=True,  # Global pref is True
        )
        with patch("MoziToolKit.bridge.world.get_world_pipeline_assets", return_value=(MagicMock(), MagicMock(), MagicMock())), \
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
                self.report = MagicMock()
                self._runner = None

            def execute(self, ctx):
                return MTK_OT_import_minecraft_save.execute(self, ctx)

        op = DummyImportOp()
        ctx = types.SimpleNamespace(
            collection=MagicMock(),
            scene=types.SimpleNamespace(),
        )

        mock_path = MagicMock()
        mock_path.is_file.return_value = False
        mock_path.exists.return_value = True

        prefs = types.SimpleNamespace(
            thread_count=2,
            enable_animated_textures=True,  # Global pref is True
        )

        captured_task = None

        def fake_runner_init(self_runner, operator, context, task, reporter, on_success, title):
            nonlocal captured_task
            captured_task = task
            self_runner.start = MagicMock(return_value={"RUNNING_MODAL"})

        with patch("MoziToolKit.operators.save.op_import_save.resolve_operator_world_dir", return_value=mock_path), \
             patch("MoziToolKit.utils.system.dependencies.get_prefs", return_value=prefs), \
             patch("MoziToolKit.operators.save.op_import_save.can_execute_asset_pipeline", return_value=(True, "")), \
             patch("MoziToolKit.operators.save.op_import_save.check_asset_cache_status", return_value="READY"), \
             patch("MoziToolKit.operators.save.op_import_save.prepare_asset_context", return_value={}), \
             patch("MoziToolKit.operators.save.op_import_save.prepare_world_mesh_context", return_value={
                 "model_db": MagicMock(),
                 "atlas": MagicMock(),
                 "biome_resolver": MagicMock(),
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

        save_root = MagicMock()
        save_root.name = "Save_World_overworld"
        save_root.get = lambda k, d=None: {
            "mtk:is_container": True,
            "mtk:container_type": "SAVE",
            "mozi_save_uuid": "test-uuid",
            "mtk_dimension": "overworld",
            "mtk_min_coord": (-10, 0, -10),
            "mtk_max_coord": (10, 50, 10),
            "mtk_enable_ao": True,
            "mtk_mesh_fluids": True,
            "mtk_weld_vertices": True,
            "mtk_origin_centered": True,
            "mtk_enable_ctm": True,
            "mtk_enable_animated_textures": False,  # Save was imported with False
            "mtk_world_name": "TestWorld",
        }.get(k, d)

        class DummyRefreshOp:
            def __init__(self):
                self.report = MagicMock()
                self.run_async = True
                self._runner = None

            def execute(self, ctx):
                return MOZI_OT_refresh_save_mesh.execute(self, ctx)

        op = DummyRefreshOp()
        ctx = types.SimpleNamespace(
            active_object=save_root,
            selected_objects=[save_root],
            collection=MagicMock(),
            view_layer=types.SimpleNamespace(objects=types.SimpleNamespace(active=save_root)),
            mode="OBJECT",
        )

        prefs = types.SimpleNamespace(
            thread_count=2,
            enable_animated_textures=True,  # Global pref is True
        )

        captured_task = None

        def fake_runner_init(self_runner, operator, context, task, reporter, on_success, title):
            nonlocal captured_task
            captured_task = task
            self_runner.start = MagicMock(return_value={"RUNNING_MODAL"})

        mock_reg = MagicMock()
        mock_world_dir = MagicMock()
        mock_world_dir.exists.return_value = True
        mock_reg.get_world_dir.return_value = mock_world_dir

        with patch("MoziToolKit.operators.save.op_refresh_save.get_save_registry", return_value=mock_reg), \
             patch("MoziToolKit.operators.save.op_refresh_save.get_save_properties", return_value=None), \
             patch("MoziToolKit.operators.save.op_refresh_save.get_prefs", return_value=prefs), \
             patch("MoziToolKit.operators.save.op_refresh_save.can_execute_asset_pipeline", return_value=(True, "")), \
             patch("MoziToolKit.operators.save.op_refresh_save.check_asset_cache_status", return_value="READY"), \
             patch("MoziToolKit.operators.save.op_refresh_save.prepare_asset_context", return_value={}), \
             patch("MoziToolKit.operators.save.op_refresh_save.prepare_world_mesh_context", return_value={
                 "model_db": MagicMock(),
                 "atlas": MagicMock(),
                 "biome_resolver": MagicMock(),
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
            # Must be False, NOT prefs' True
            self.assertFalse(task_kwargs["enable_animated_textures"])

    def test_sync_client_forwards_enable_animated_textures(self):
        """SyncBridgeSession start and start_with_cache must forward enable_animated_textures to MesherConfig."""
        from MoziToolKit.bridge.sync import SyncBridgeSession

        client = SyncBridgeSession()
        mock_mtk = MagicMock()
        mock_session = MagicMock()
        mock_mtk.LiveSyncSession.return_value = mock_session

        mock_config = MagicMock()
        mock_mtk.MesherConfig.return_value = mock_config

        with patch("MoziToolKit.bridge.sync.get_libmtk", return_value=mock_mtk), \
             patch("MoziToolKit.utils.system.get_prefs", return_value=types.SimpleNamespace(thread_count=1, enable_animated_textures=False)):

            client.start(url="ws://127.0.0.1:8765", enable_animated_textures=False)
            self.assertTrue(mock_mtk.MesherConfig.called)
            cfg_kwargs = mock_mtk.MesherConfig.call_args.kwargs
            self.assertIn("enable_animated_textures", cfg_kwargs)
            self.assertFalse(cfg_kwargs["enable_animated_textures"])

    def test_ensure_world_materials_cleans_unused_slots_when_requested(self):
        """ensure_world_materials with clean_unused_slots=True prunes unreferenced material slots."""
        test_mesh = MagicMock()
        test_mesh.polygons = [MagicMock(), MagicMock()]
        test_mesh.attributes = {}

        mat0 = MagicMock()
        mat0.name = "MTK:Atlas:blocks:001"
        mat0.get = lambda k, d=None: 0 if k == "mtk_atlas_chunk_id" else None
        mat0.node_tree = MagicMock()
        mat0.node_tree.nodes = [MagicMock()]

        mat1_anim = MagicMock()
        mat1_anim.name = "MTK:Atlas:blocks:anim:001"
        mat1_anim.get = lambda k, d=None: 1 if k == "mtk_atlas_chunk_id" else None
        mat1_anim.node_tree = MagicMock()
        mat1_anim.node_tree.nodes = [MagicMock()]

        test_mesh.materials = [mat0, mat1_anim]

        test_obj = MagicMock()
        test_obj.type = "MESH"
        test_obj.data = test_mesh

        # When used_chunk_ids is [0] (only static chunk), and clean_unused_slots=True:
        # It must not use the subset fast-path that leaves mat1_anim in test_mesh.materials.
        with patch("MoziToolKit.utils.materials.builder.world_binding.ensure_atlas_textures_extracted") as mock_dir, \
             patch("MoziToolKit.utils.materials.builder.world_binding.load_baked_atlas_from_cache") as mock_atlas:
            mock_dir.return_value = MagicMock()
            mock_dir.return_value.__truediv__.return_value.exists.return_value = False
            mock_atlas_obj = MagicMock()
            mock_atlas_obj.get_chunk_info.side_effect = lambda cid: {
                "chunk_id": cid,
                "category": "blocks",
                "category_chunk_index": cid + 1,
                "is_animated": False,
            }
            mock_atlas.return_value = mock_atlas_obj

            ensure_world_materials(test_obj, used_chunk_ids=[0], clean_unused_slots=True)

            # test_mesh.materials must now contain ONLY 1 slot (mat0) and mat1_anim removed!
            self.assertEqual(len(test_mesh.materials), 1)
            self.assertNotIn(mat1_anim, test_mesh.materials)


if __name__ == "__main__":
    unittest.main()

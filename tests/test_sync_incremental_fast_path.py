"""
Unit tests for Live Sync incremental update fast-paths and cache bypass optimizations.
Verifies:
1. Incremental mesh updates (WORLD_MESH_READY) bypass session.get_storage().
2. Active Live Sync session passes session.atlas directly down to update_world_mesh.
3. op_sync_rebuild bypasses expensive check_asset_cache_status when session is active and not dirty.
4. load_baked_atlas_from_cache and load_baked_model_database memoize results in memory.
"""

from __future__ import annotations

import types
import unittest
from unittest.mock import patch

import bpy

from MoziToolKit.bridge.sync import SyncBridgeSession, get_sync_bridge_session
from MoziToolKit.bridge.assets.cache import (
    load_baked_atlas_from_cache,
    load_baked_model_database,
    invalidate_asset_cache_memory,
)


class TestSyncIncrementalFastPath(unittest.TestCase):
    def setUp(self):
        invalidate_asset_cache_memory()

    def tearDown(self):
        invalidate_asset_cache_memory()

    def test_atlas_and_model_db_in_memory_memoization(self):
        """Verify load_baked_atlas_from_cache and load_baked_model_database reuse in-memory objects."""
        mock_atlas = object()
        mock_model_db = object()
        load_atlas_calls = []
        load_models_calls = []
        mock_cache = types.SimpleNamespace(
            load_atlas=lambda: (load_atlas_calls.append(True), mock_atlas)[1],
            load_models=lambda: (load_models_calls.append(True), mock_model_db)[1],
        )

        with patch("MoziToolKit.bridge.assets.cache.open_active_asset_cache", return_value=mock_cache), \
             patch("MoziToolKit.bridge.assets.cache.get_libmtk", return_value=types.SimpleNamespace()):

            # First load -> calls cache.load_atlas
            atlas1 = load_baked_atlas_from_cache()
            self.assertIs(atlas1, mock_atlas)
            self.assertEqual(len(load_atlas_calls), 1)

            # Second load -> returns cached instance with 0 cache.load_atlas calls
            atlas2 = load_baked_atlas_from_cache()
            self.assertIs(atlas2, mock_atlas)
            self.assertEqual(len(load_atlas_calls), 1)

            # Model DB first load
            mdb1 = load_baked_model_database()
            self.assertIs(mdb1, mock_model_db)
            self.assertEqual(len(load_models_calls), 1)

            # Model DB second load -> returns cached instance
            mdb2 = load_baked_model_database()
            self.assertIs(mdb2, mock_model_db)
            self.assertEqual(len(load_models_calls), 1)

            # Invalidate clears memory
            invalidate_asset_cache_memory()
            atlas3 = load_baked_atlas_from_cache()
            self.assertIs(atlas3, mock_atlas)
            self.assertEqual(len(load_atlas_calls), 2)

    def test_sync_timer_tick_avoids_get_storage_on_delta(self):
        """Verify _sync_timer_tick does NOT call session.get_storage() during delta updates."""
        from MoziToolKit.operators.sync.op_sync_connect import _sync_timer_tick

        storage_calls = []
        mock_atlas = object()
        mock_mesh = types.SimpleNamespace(vertex_count=100, used_materials=lambda: [0])
        mock_session = types.SimpleNamespace(
            is_active=True,
            atlas=mock_atlas,
            poll_events=lambda: [
                {"type": "DELTA_APPLIED", "change_count": 1},
                {"type": "WORLD_MESH_READY", "mesh": mock_mesh},
            ],
            get_storage=lambda: storage_calls.append(True),
        )

        test_root = bpy.data.objects.new("Sync_Root_Test", None)
        test_mesh_obj = bpy.data.objects.new("Sync_Mesh_Test", None)
        bpy.context.collection.objects.link(test_root)
        bpy.context.collection.objects.link(test_mesh_obj)

        update_calls = []

        try:
            with patch("MoziToolKit.operators.sync.op_sync_connect.get_sync_bridge_session", return_value=mock_session), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.get_active_sync_container", return_value=test_root), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.get_or_create_world_mesh_object", return_value=test_mesh_obj), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.update_world_mesh", lambda *args, **kwargs: (update_calls.append((args, kwargs)), (100, 50))[1]):

                _sync_timer_tick()

                # Critical assertion: get_storage must NOT be called for delta updates
                self.assertEqual(len(storage_calls), 0)

                # update_world_mesh must receive storage=None and atlas=mock_session.atlas
                self.assertEqual(len(update_calls), 1)
                args, kwargs = update_calls[0]
                self.assertIsNone(kwargs.get("storage"))
                self.assertFalse(kwargs.get("sync_point_cloud"))
                self.assertIs(kwargs.get("atlas"), mock_atlas)
        finally:
            bpy.data.objects.remove(test_mesh_obj)
            bpy.data.objects.remove(test_root)

    def test_sync_timer_tick_calls_get_storage_on_stream_finished(self):
        """Verify _sync_timer_tick calls session.get_storage() only when needs_voxel_sync is True."""
        from MoziToolKit.operators.sync.op_sync_connect import _sync_timer_tick

        storage_calls = []
        mock_atlas = object()
        mock_storage = object()
        mock_mesh = types.SimpleNamespace(vertex_count=200, used_materials=lambda: [0])
        mock_session = types.SimpleNamespace(
            is_active=True,
            atlas=mock_atlas,
            poll_events=lambda: [
                {"type": "STREAM_FINISHED", "built_sections": 5},
                {"type": "WORLD_MESH_READY", "mesh": mock_mesh},
            ],
            get_storage=lambda: (storage_calls.append(True), mock_storage)[1],
        )

        test_root = bpy.data.objects.new("Sync_Root_Finished_Test", None)
        test_mesh_obj = bpy.data.objects.new("Sync_Mesh_Finished_Test", None)
        bpy.context.collection.objects.link(test_root)
        bpy.context.collection.objects.link(test_mesh_obj)

        update_calls = []

        try:
            with patch("MoziToolKit.operators.sync.op_sync_connect.get_sync_bridge_session", return_value=mock_session), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.get_active_sync_container", return_value=test_root), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.get_or_create_world_mesh_object", return_value=test_mesh_obj), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.update_world_mesh", lambda *args, **kwargs: (update_calls.append((args, kwargs)), (200, 100))[1]):

                _sync_timer_tick()

                # get_storage MUST be called when stream finishes to sync companion point cloud
                self.assertEqual(len(storage_calls), 1)
                self.assertEqual(len(update_calls), 1)
                args, kwargs = update_calls[0]
                self.assertIs(kwargs.get("storage"), mock_storage)
                self.assertTrue(kwargs.get("sync_point_cloud"))
                self.assertIs(kwargs.get("atlas"), mock_atlas)
        finally:
            bpy.data.objects.remove(test_mesh_obj)
            bpy.data.objects.remove(test_root)

    def test_sync_rebuild_bypasses_check_asset_cache_status_when_session_active(self):
        """Verify MOZI_OT_sync_rebuild_world bypasses check_asset_cache_status when session is active and clean."""
        from MoziToolKit.operators.sync.op_sync_rebuild import MOZI_OT_sync_rebuild_world

        mock_atlas = object()
        mock_mesh = types.SimpleNamespace(vertex_count=50)
        mock_session = types.SimpleNamespace(
            is_active=True,
            atlas=mock_atlas,
            check_and_reload_dirty_cache=lambda *args, **kwargs: False,
            get_world_mesh=lambda: mock_mesh,
            get_storage=lambda: object(),
        )

        class DummyRebuildOp:
            def __init__(self):
                self.target_container = ""
                self.run_async = False
                self.reports = []
                self.report = lambda *args: self.reports.append(args)

            def execute(self, ctx):
                return MOZI_OT_sync_rebuild_world.execute(self, ctx)

        op = DummyRebuildOp()
        mock_context = bpy.context

        check_status_calls = []
        update_calls = []

        with patch("MoziToolKit.operators.sync.op_sync_rebuild.get_sync_bridge_session", return_value=mock_session), \
             patch("MoziToolKit.operators.sync.op_sync_rebuild.can_execute_asset_pipeline", return_value=(True, "")), \
             patch("MoziToolKit.operators.sync.op_sync_rebuild.check_asset_cache_status", lambda *args, **kwargs: check_status_calls.append(True)), \
             patch("MoziToolKit.operators.sync.op_sync_rebuild.get_or_create_world_mesh_object"), \
             patch("MoziToolKit.operators.sync.op_sync_rebuild.update_world_mesh", lambda *args, **kwargs: (update_calls.append((args, kwargs)), (50, 25))[1]):

            res = op.execute(mock_context)
            self.assertEqual(res, {'FINISHED'})

            # check_asset_cache_status must NOT be called because session is active, has atlas, and is clean!
            self.assertEqual(len(check_status_calls), 0)

            self.assertEqual(len(update_calls), 1)
            args, kwargs = update_calls[0]
            self.assertIs(kwargs.get("atlas"), mock_atlas)

    def test_sync_clear_history_operator(self):
        """Verify MOZI_OT_sync_clear_history defines target_container and clears delta history."""
        from MoziToolKit.operators.sync.op_sync_clear_history import MOZI_OT_sync_clear_history

        class DummyClearOp:
            def __init__(self):
                self.target_container = "World_Container_Test"
                self.reports = []
                self.report = lambda *args: self.reports.append(args)

            def execute(self, ctx):
                return MOZI_OT_sync_clear_history.execute(self, ctx)

        test_empty = bpy.data.objects.new("World_Container_Test", None)
        bpy.context.scene.collection.objects.link(test_empty)
        try:
            if hasattr(test_empty, "mozi_sync"):
                item = test_empty.mozi_sync.delta_history.add()
                item.pos_str = "Delta #1"
                self.assertGreaterEqual(len(test_empty.mozi_sync.delta_history), 1)

            op = DummyClearOp()
            res = op.execute(bpy.context)
            self.assertEqual(res, {'FINISHED'})

            if hasattr(test_empty, "mozi_sync"):
                self.assertEqual(len(test_empty.mozi_sync.delta_history), 0)
        finally:
            bpy.data.objects.remove(test_empty)

    def test_delta_applied_schedules_debounced_point_cloud_update(self):
        """Verify DELTA_APPLIED schedules debounced point cloud synchronization."""
        import time
        from MoziToolKit.operators.sync import op_sync_connect
        from MoziToolKit.operators.sync.op_sync_connect import _sync_timer_tick

        mock_atlas = object()
        mock_session = types.SimpleNamespace(
            is_active=True,
            atlas=mock_atlas,
            poll_events=lambda: [
                {"type": "DELTA_APPLIED", "change_count": 3},
            ],
        )

        test_root = bpy.data.objects.new("Sync_Debounce_Root", None)
        bpy.context.collection.objects.link(test_root)

        try:
            with patch("MoziToolKit.operators.sync.op_sync_connect.get_sync_bridge_session", return_value=mock_session), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.get_active_sync_container", return_value=test_root):

                op_sync_connect._pending_cloud_sync_time = None
                _sync_timer_tick()

                # Must have set a debounced timestamp in future
                self.assertIsNotNone(op_sync_connect._pending_cloud_sync_time)
                self.assertGreater(op_sync_connect._pending_cloud_sync_time, time.time())
        finally:
            bpy.data.objects.remove(test_root)

    def test_stored_manifest_imported_on_connect(self):
        """Verify MOZI_OT_sync_connect restores persistent sync manifest into native session."""
        from MoziToolKit.operators.sync import op_sync_connect
        from MoziToolKit.operators.sync.op_sync_connect import MOZI_OT_sync_connect

        start_calls = []
        mock_session = types.SimpleNamespace(
            is_active=False,
            start=lambda **kwargs: (start_calls.append(kwargs), True)[1],
        )

        import json
        state_json = json.dumps({
            "server_uuid": "12345678123456781234567812345678",
            "epoch": 42,
            "sequence": 105,
            "min": [0, 64, 0],
            "size": [16, 16, 16],
            "dimension": "minecraft:overworld",
            "state_hash": 0x1234567890ABCDEF,
            "user_modified": False,
        })
        props = {
            "mtk_sync_state_json": state_json,
            "mtk_sync_user_modified": False,
        }

        class DummyConnectOp:
            def __init__(self):
                self.target_container = "Yefira_World"
                self.reports = []
                self.report = lambda *args: self.reports.append(args)

            def execute(self, ctx):
                return MOZI_OT_sync_connect.execute(self, ctx)

        op = DummyConnectOp()

        real_obj = bpy.data.objects.new("Yefira_World", None)
        for k, v in props.items():
            real_obj[k] = v
        bpy.context.collection.objects.link(real_obj)

        mesh = bpy.data.meshes.new("Yefira_World_Mesh")
        mesh.from_pydata([(0.0, 0.0, 0.0)], [], [])
        real_mesh_obj = bpy.data.objects.new("Yefira_World_Mesh", mesh)
        real_mesh_obj["mtk:is_yefira_mesh"] = True
        real_mesh_obj.parent = real_obj
        bpy.context.collection.objects.link(real_mesh_obj)

        try:
            with patch("MoziToolKit.operators.sync.op_sync_connect.get_sync_bridge_session", return_value=mock_session), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.can_execute_asset_pipeline", return_value=(True, "")), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.is_sync_available", return_value=True), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.check_asset_cache_status", return_value="READY"), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.load_model_database_from_cache", return_value=None), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.load_atlas_from_cache", return_value=None), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.load_biome_resolver_from_cache", return_value=None), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.start_sync_timer"):

                res = op.execute(bpy.context)
                self.assertEqual(res, {'FINISHED'})
                self.assertEqual(len(start_calls), 1)
                kwargs = start_calls[0]
                self.assertIn("url", kwargs)
        finally:
            bpy.data.objects.remove(real_mesh_obj, do_unlink=True)
            bpy.data.objects.remove(real_obj, do_unlink=True)


if __name__ == "__main__":
    unittest.main()


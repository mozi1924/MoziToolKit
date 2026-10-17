"""
Unit tests for Live Sync incremental update fast-paths and cache bypass optimizations.
Verifies:
1. Incremental mesh updates (WORLD_MESH_READY) bypass session.get_storage().
2. Active Live Sync session passes session.atlas directly down to update_world_mesh.
3. op_sync_rebuild bypasses expensive check_asset_cache_status when session is active and not dirty.
4. load_baked_atlas_from_cache and load_baked_model_database memoize results in memory.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

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
        mock_cache = MagicMock()
        mock_atlas = MagicMock()
        mock_model_db = MagicMock()
        mock_cache.load_atlas.return_value = mock_atlas
        mock_cache.load_models.return_value = mock_model_db

        with patch("MoziToolKit.bridge.assets.cache.open_active_asset_cache", return_value=mock_cache), \
             patch("MoziToolKit.bridge.assets.cache.get_libmtk") as mock_mtk:
            mock_mtk.return_value = MagicMock()

            # First load -> calls cache.load_atlas
            atlas1 = load_baked_atlas_from_cache()
            self.assertIs(atlas1, mock_atlas)
            self.assertEqual(mock_cache.load_atlas.call_count, 1)

            # Second load -> returns cached instance with 0 cache.load_atlas calls
            atlas2 = load_baked_atlas_from_cache()
            self.assertIs(atlas2, mock_atlas)
            self.assertEqual(mock_cache.load_atlas.call_count, 1)

            # Model DB first load
            mdb1 = load_baked_model_database()
            self.assertIs(mdb1, mock_model_db)
            self.assertEqual(mock_cache.load_models.call_count, 1)

            # Model DB second load -> returns cached instance
            mdb2 = load_baked_model_database()
            self.assertIs(mdb2, mock_model_db)
            self.assertEqual(mock_cache.load_models.call_count, 1)

            # Invalidate clears memory
            invalidate_asset_cache_memory()
            atlas3 = load_baked_atlas_from_cache()
            self.assertIs(atlas3, mock_atlas)
            self.assertEqual(mock_cache.load_atlas.call_count, 2)

    def test_sync_timer_tick_avoids_get_storage_on_delta(self):
        """Verify _sync_timer_tick does NOT call session.get_storage() during delta updates."""
        from MoziToolKit.operators.sync.op_sync_connect import _sync_timer_tick

        mock_session = MagicMock(spec=SyncBridgeSession)
        mock_session.is_active = True
        mock_session.atlas = MagicMock()
        mock_mesh = MagicMock()
        mock_mesh.vertex_count = 100
        mock_mesh.used_materials.return_value = [0]

        # Simulate receiving WORLD_MESH_READY without STREAM_FINISHED (i.e. Delta Update)
        mock_session.poll_events.return_value = [
            {"type": "DELTA_APPLIED", "change_count": 1},
            {"type": "WORLD_MESH_READY", "mesh": mock_mesh},
        ]

        with patch("MoziToolKit.operators.sync.op_sync_connect.get_sync_bridge_session", return_value=mock_session), \
             patch("MoziToolKit.operators.sync.op_sync_connect.get_active_sync_container", return_value=MagicMock()), \
             patch("MoziToolKit.operators.sync.op_sync_connect.get_or_create_world_mesh_object") as mock_get_obj, \
             patch("MoziToolKit.operators.sync.op_sync_connect.update_world_mesh", return_value=(100, 50)) as mock_update_mesh:

            mock_get_obj.return_value = MagicMock()
            _sync_timer_tick()

            # Critical assertion: get_storage must NOT be called for delta updates
            mock_session.get_storage.assert_not_called()

            # update_world_mesh must receive storage=None and atlas=mock_session.atlas
            mock_update_mesh.assert_called_once()
            _, kwargs = mock_update_mesh.call_args
            self.assertIsNone(kwargs.get("storage"))
            self.assertFalse(kwargs.get("sync_point_cloud"))
            self.assertIs(kwargs.get("atlas"), mock_session.atlas)

    def test_sync_timer_tick_calls_get_storage_on_stream_finished(self):
        """Verify _sync_timer_tick calls session.get_storage() only when needs_voxel_sync is True."""
        from MoziToolKit.operators.sync.op_sync_connect import _sync_timer_tick

        mock_session = MagicMock(spec=SyncBridgeSession)
        mock_session.is_active = True
        mock_session.atlas = MagicMock()
        mock_mesh = MagicMock()
        mock_mesh.vertex_count = 200
        mock_mesh.used_materials.return_value = [0]
        mock_storage = MagicMock()
        mock_session.get_storage.return_value = mock_storage

        # Simulate receiving STREAM_FINISHED and WORLD_MESH_READY
        mock_session.poll_events.return_value = [
            {"type": "STREAM_FINISHED", "built_sections": 5},
            {"type": "WORLD_MESH_READY", "mesh": mock_mesh},
        ]

        with patch("MoziToolKit.operators.sync.op_sync_connect.get_sync_bridge_session", return_value=mock_session), \
             patch("MoziToolKit.operators.sync.op_sync_connect.get_active_sync_container", return_value=MagicMock()), \
             patch("MoziToolKit.operators.sync.op_sync_connect.get_or_create_world_mesh_object") as mock_get_obj, \
             patch("MoziToolKit.operators.sync.op_sync_connect.update_world_mesh", return_value=(200, 100)) as mock_update_mesh:

            mock_get_obj.return_value = MagicMock()
            _sync_timer_tick()

            # get_storage MUST be called when stream finishes to sync companion point cloud
            mock_session.get_storage.assert_called_once()
            _, kwargs = mock_update_mesh.call_args
            self.assertIs(kwargs.get("storage"), mock_storage)
            self.assertTrue(kwargs.get("sync_point_cloud"))
            self.assertIs(kwargs.get("atlas"), mock_session.atlas)

    def test_sync_rebuild_bypasses_check_asset_cache_status_when_session_active(self):
        """Verify MOZI_OT_sync_rebuild_world bypasses check_asset_cache_status when session is active and clean."""
        from MoziToolKit.operators.sync.op_sync_rebuild import MOZI_OT_sync_rebuild_world

        mock_session = MagicMock(spec=SyncBridgeSession)
        mock_session.is_active = True
        mock_session.atlas = MagicMock()
        mock_session.check_and_reload_dirty_cache.return_value = False  # Not dirty
        mock_session.get_world_mesh.return_value = MagicMock(vertex_count=50)

        class DummyRebuildOp:
            def __init__(self):
                self.target_container = ""
                self.run_async = False
                self.report = MagicMock()

            def execute(self, ctx):
                return MOZI_OT_sync_rebuild_world.execute(self, ctx)

        op = DummyRebuildOp()
        mock_context = MagicMock()

        with patch("MoziToolKit.operators.sync.op_sync_rebuild.get_sync_bridge_session", return_value=mock_session), \
             patch("MoziToolKit.operators.sync.op_sync_rebuild.check_asset_cache_status") as mock_check_status, \
             patch("MoziToolKit.operators.sync.op_sync_rebuild.get_or_create_world_mesh_object"), \
             patch("MoziToolKit.operators.sync.op_sync_rebuild.update_world_mesh", return_value=(50, 25)) as mock_update_mesh:

            res = op.execute(mock_context)
            self.assertEqual(res, {'FINISHED'})

            # check_asset_cache_status must NOT be called because session is active, has atlas, and is clean!
            mock_check_status.assert_not_called()

            _, kwargs = mock_update_mesh.call_args
            self.assertIs(kwargs.get("atlas"), mock_session.atlas)

    def test_sync_clear_history_operator(self):
        """Verify MOZI_OT_sync_clear_history defines target_container and clears delta history."""
        from MoziToolKit.operators.sync.op_sync_clear_history import MOZI_OT_sync_clear_history

        class DummyClearOp:
            def __init__(self):
                self.target_container = "World_Container_Test"
                self.report = MagicMock()

            def execute(self, ctx):
                return MOZI_OT_sync_clear_history.execute(self, ctx)

        import bpy
        is_mock_bpy = isinstance(bpy, MagicMock) or "Mock" in type(bpy).__name__ or str(type(bpy)).endswith("MagicMock'>")
        if not is_mock_bpy:
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
        else:
            mock_obj = MagicMock()
            mock_obj.mozi_sync.delta_history = MagicMock()
            mock_context = MagicMock()
            mock_context.scene.mozi_sync.delta_history = MagicMock()
            op = DummyClearOp()
            orig_objects = getattr(bpy.data, "objects", None)
            try:
                bpy.data.objects = {"World_Container_Test": mock_obj}
                res = op.execute(mock_context)
                self.assertEqual(res, {'FINISHED'})
                mock_obj.mozi_sync.delta_history.clear.assert_called_once()
                mock_context.scene.mozi_sync.delta_history.clear.assert_called_once()
            finally:
                bpy.data.objects = orig_objects

    def test_delta_applied_schedules_debounced_point_cloud_update(self):
        """Verify DELTA_APPLIED schedules debounced point cloud synchronization."""
        import time
        from MoziToolKit.operators.sync import op_sync_connect
        from MoziToolKit.operators.sync.op_sync_connect import _sync_timer_tick

        mock_session = MagicMock(spec=SyncBridgeSession)
        mock_session.is_active = True
        mock_session.atlas = MagicMock()
        mock_session.poll_events.return_value = [
            {"type": "DELTA_APPLIED", "change_count": 3},
        ]

        with patch("MoziToolKit.operators.sync.op_sync_connect.get_sync_bridge_session", return_value=mock_session), \
             patch("MoziToolKit.operators.sync.op_sync_connect.get_active_sync_container", return_value=MagicMock()):

            op_sync_connect._pending_cloud_sync_time = None
            _sync_timer_tick()

            # Must have set a debounced timestamp in future
            self.assertIsNotNone(op_sync_connect._pending_cloud_sync_time)
            self.assertGreater(op_sync_connect._pending_cloud_sync_time, time.time())

    def test_stored_manifest_imported_on_connect(self):
        """Verify MOZI_OT_sync_connect restores persistent sync manifest into native session."""
        from MoziToolKit.operators.sync import op_sync_connect
        from MoziToolKit.operators.sync.op_sync_connect import MOZI_OT_sync_connect

        mock_session = MagicMock(spec=SyncBridgeSession)
        mock_session.is_active = False
        mock_session.start.return_value = True

        mock_container = MagicMock()
        mock_container.name = "Yefira_World"
        props = {
            "mtk_sync_server_uuid": "12345678123456781234567812345678",
            "mtk_sync_epoch": 42,
            "mtk_sync_sequence": 105,
            "mtk_sync_bounds": [0, 64, 0, 16, 16, 16],
            "mtk_sync_dimension": "minecraft:overworld",
            "mtk_sync_state_hash": "0x1234567890abcdef",
            "mtk_sync_user_modified": False,
        }
        mock_container.get.side_effect = lambda k, d=None: props.get(k, d)
        mock_mesh = MagicMock()
        mock_mesh.type = "MESH"
        mock_mesh.data.vertices = [object()]
        mock_container.children = [mock_mesh]

        class DummyConnectOp:
            def __init__(self):
                self.target_container = "Yefira_World"
                self.report = MagicMock()

            def execute(self, ctx):
                return MOZI_OT_sync_connect.execute(self, ctx)

        op = DummyConnectOp()
        mock_context = MagicMock()
        mock_context.scene.mozi_active_sync_container_name = "Yefira_World"

        import bpy
        has_real_bpy = hasattr(bpy, "data") and hasattr(bpy.data, "objects") and not isinstance(bpy, MagicMock)

        real_obj = None
        real_mesh_obj = None
        orig_objects = getattr(bpy.data, "objects", None)
        try:
            with patch("MoziToolKit.operators.sync.op_sync_connect.get_sync_bridge_session", return_value=mock_session), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.is_sync_available", return_value=True), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.check_asset_cache_status", return_value="READY"), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.load_model_database_from_cache", return_value=None), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.load_atlas_from_cache", return_value=None), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.load_biome_resolver_from_cache", return_value=None), \
                 patch("MoziToolKit.operators.sync.op_sync_connect.start_sync_timer"):

                if has_real_bpy:
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
                else:
                    bpy.data.objects = {"Yefira_World": mock_container}

                # Fast path plumbing: when explicitly enabled, persisted identity is
                # forwarded to HELLO.
                with patch.object(op_sync_connect, "_ZERO_REBUILD_FAST_PATH_ENABLED", True):
                    res = op.execute(mock_context)
                self.assertEqual(res, {'FINISHED'})
                mock_session.start.assert_called_once()
                kwargs = mock_session.start.call_args[1]
                self.assertEqual(kwargs.get("cached_epoch"), 42)
                self.assertEqual(kwargs.get("cached_seq"), 105)
                self.assertEqual(kwargs.get("cached_min"), (0, 64, 0))
                self.assertEqual(kwargs.get("cached_size"), (16, 16, 16))
                self.assertEqual(kwargs.get("cached_state_hash"), 0x1234567890abcdef)

                # Production default: zero-rebuild is disabled until native
                # VoxelStorage persistence lands, so HELLO always requests a full
                # baseline and the cached fields stay zeroed.
                mock_session.start.reset_mock()
                res = op.execute(mock_context)
                self.assertEqual(res, {'FINISHED'})
                kwargs = mock_session.start.call_args[1]
                self.assertEqual(kwargs.get("cached_epoch"), 0)
                self.assertEqual(kwargs.get("cached_seq"), 0)
                self.assertIsNone(kwargs.get("cached_uuid"))
                self.assertEqual(kwargs.get("cached_state_hash"), 0)
        finally:
            if has_real_bpy and real_obj is not None:
                if real_mesh_obj is not None:
                    bpy.data.objects.remove(real_mesh_obj, do_unlink=True)
                bpy.data.objects.remove(real_obj, do_unlink=True)
            elif not has_real_bpy:
                bpy.data.objects = orig_objects


if __name__ == "__main__":
    unittest.main()


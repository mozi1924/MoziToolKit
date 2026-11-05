"""
Unit and integration tests for Minecraft Save Containerization, Non-overwriting Auto-incrementing,
and Unified Mesh Rebuild Operator (mozi.rebuild_mesh) with Right-Click Context Menu.
Runs 100% inside real Blender host environment with native bpy data structures.
"""

from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import bpy
from MoziToolKit.utils.save.hierarchy import (
    apply_imported_save_to_blender,
    sanitize_save_privacy,
    _resolve_unique_save_container_name,
)
from MoziToolKit.operators.mesh import (
    MOZI_OT_rebuild_mesh,
    resolve_mesh_rebuild_targets,
)
from MoziToolKit.operators.save import (
    MOZI_OT_refresh_save_mesh,
    MOZI_OT_relink_save_folder,
    resolve_save_container,
)
from MoziToolKit.utils.system.menu_registry import CANONICAL_DEFAULT_PRESETS, CANONICAL_OPERATORS
from MoziToolKit.utils.system.save_registry import get_save_registry


class TestSaveContainerAndRebuildMesh(unittest.TestCase):
    def setUp(self):
        self._created_objects: list[bpy.types.Object] = []
        self._created_meshes: list[bpy.types.Mesh] = []

    def tearDown(self):
        for obj in reversed(self._created_objects):
            try:
                if obj.name in bpy.data.objects:
                    bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass
        for mesh in reversed(self._created_meshes):
            try:
                if mesh.name in bpy.data.meshes:
                    bpy.data.meshes.remove(mesh)
            except Exception:
                pass

    def _make_obj(self, name: str, obj_type: str = "EMPTY", mesh_data=None) -> bpy.types.Object:
        if name in bpy.data.objects:
            obj = bpy.data.objects[name]
        else:
            if obj_type == "MESH":
                mesh = mesh_data if isinstance(mesh_data, bpy.types.Mesh) else bpy.data.meshes.new(name)
                self._created_meshes.append(mesh)
                obj = bpy.data.objects.new(name, mesh)
            else:
                obj = bpy.data.objects.new(name, None)
            if hasattr(bpy.context, "scene") and hasattr(bpy.context.scene, "collection"):
                if obj.name not in bpy.context.scene.collection.objects:
                    bpy.context.scene.collection.objects.link(obj)
            self._created_objects.append(obj)
        return obj

    def test_save_container_hierarchy_and_incrementing(self):
        """Verifies save imports create isolated Empty containers without overwriting."""
        meta = {
            "level_name": "Skyblock",
            "version_name": "1.21.4",
            "data_version": 4189,
            "spawn": (0, 64, 0),
        }
        mesh_data = types.SimpleNamespace(used_materials=lambda: [])
        storage = object()

        context = bpy.context

        with patch("MoziToolKit.utils.save.hierarchy.inject_mesh_data"), patch("MoziToolKit.utils.save.hierarchy.ensure_world_materials"):
            # 1. First import
            root1, stats1 = apply_imported_save_to_blender(
                mesh_data=mesh_data,
                meta=meta,
                storage=storage,
                elapsed_ms=12.5,
                world_dir="/tmp/world",
                dimension="overworld",
                context=context,
                enable_ao=True,
                mesh_fluids=False,
                weld_vertices=True,
                origin_centered=True,
            )
            self._created_objects.append(root1)

            self.assertEqual(root1.name, "Save_Skyblock_overworld")
            self.assertEqual(root1.type, "EMPTY")
            self.assertTrue(root1["mtk:is_container"])
            self.assertEqual(root1["mtk:container_type"], "SAVE")
            self.assertEqual(root1["mtk_world_name"], "Skyblock")
            self.assertTrue(root1["mtk_enable_ao"])
            self.assertFalse(root1["mtk_mesh_fluids"])

            # Check child mesh
            mesh_name = f"{root1.name}_Mesh"
            self.assertIn(mesh_name, bpy.data.objects)
            mesh1 = bpy.data.objects[mesh_name]
            self._created_objects.append(mesh1)
            self.assertEqual(mesh1.parent, root1)
            self.assertTrue(mesh1["mtk:is_save_mesh"])
            self.assertEqual(mesh1["mtk:geometry_origin"], "SAVE")

            # 2. Second import of same world: must auto-increment to avoid overwriting!
            root2, stats2 = apply_imported_save_to_blender(
                mesh_data=mesh_data,
                meta=meta,
                storage=storage,
                elapsed_ms=15.0,
                world_dir="/tmp/world",
                dimension="overworld",
                context=context,
                reuse_existing=False,
            )
            self._created_objects.append(root2)

            self.assertEqual(root2.name, "Save_Skyblock_overworld_01")
            self.assertNotEqual(root1.name, root2.name)
            self.assertEqual(root2.type, "EMPTY")
            self.assertTrue(root2["mtk:is_container"])

            mesh2_name = f"{root2.name}_Mesh"
            self.assertIn(mesh2_name, bpy.data.objects)
            mesh2 = bpy.data.objects[mesh2_name]
            self._created_objects.append(mesh2)
            self.assertEqual(mesh2.parent, root2)

            # Both containers exist independently in the scene
            self.assertIn("Save_Skyblock_overworld", bpy.data.objects)
            self.assertIn("Save_Skyblock_overworld_01", bpy.data.objects)

    def test_resolve_mesh_rebuild_targets(self):
        """Verifies resolve_mesh_rebuild_targets properly categorizes SYNC, SAVE, and CLOUD targets."""
        # 1. Save container root
        save_root = self._make_obj("Save_Test_overworld", "EMPTY")
        save_root["mtk:is_container"] = True
        save_root["mtk:container_type"] = "SAVE"
        save_mesh = self._make_obj("Save_Test_overworld_Mesh", "MESH")
        save_mesh.parent = save_root
        save_cloud = self._make_obj("Save_Test_overworld_VoxelCloud", "MESH")
        save_cloud.parent = save_root
        save_cloud["mtk_is_voxel_cloud"] = True

        # Test selecting Save root
        ctx1 = types.SimpleNamespace(active_object=save_root, selected_objects=[save_root])
        r, m, c, st = resolve_mesh_rebuild_targets(ctx1)
        self.assertEqual(r, save_root)
        self.assertEqual(m, save_mesh)
        self.assertEqual(c, save_cloud)
        self.assertEqual(st, "SAVE")

        # Test selecting Save mesh
        ctx2 = types.SimpleNamespace(active_object=save_mesh, selected_objects=[save_mesh])
        r, m, c, st = resolve_mesh_rebuild_targets(ctx2)
        self.assertEqual(r, save_root)
        self.assertEqual(m, save_mesh)
        self.assertEqual(c, save_cloud)
        self.assertEqual(st, "SAVE")

        # 2. Live Sync container
        sync_root = self._make_obj("Yefira_World", "EMPTY")
        sync_root["mtk:is_container"] = True
        sync_root["mtk:container_type"] = "SYNC"
        sync_root["mtk:is_yefira_world"] = True
        sync_mesh = self._make_obj("Yefira_World_Mesh", "MESH")
        sync_mesh.parent = sync_root

        ctx3 = types.SimpleNamespace(active_object=sync_root, selected_objects=[sync_root])
        r, m, c, st = resolve_mesh_rebuild_targets(ctx3)
        self.assertEqual(r, sync_root)
        self.assertEqual(m, sync_mesh)
        self.assertEqual(st, "SYNC")

        # 3. Unrecognized object
        cube = self._make_obj("Cube", "MESH")
        ctx4 = types.SimpleNamespace(active_object=cube, selected_objects=[cube])
        r, m, c, st = resolve_mesh_rebuild_targets(ctx4)
        self.assertEqual(st, "NONE")

    def test_rebuild_mesh_poll_and_menus(self):
        """Verifies operator poll and presence in right-click context menu presets."""
        self.assertEqual(MOZI_OT_rebuild_mesh.bl_idname, "mozi.rebuild_mesh")

        # Context menu preset registration check
        self.assertIn("mozi.rebuild_mesh", CANONICAL_OPERATORS)
        self.assertTrue(any(item["operator"] == "mozi.rebuild_mesh" for item in CANONICAL_DEFAULT_PRESETS["object"]))
        self.assertTrue(any(item["operator"] == "mozi.rebuild_mesh" for item in CANONICAL_DEFAULT_PRESETS["mesh"]))

        # Poll with valid Save container
        save_root = self._make_obj("Save_Test_overworld", "EMPTY")
        save_root["mtk:is_container"] = True
        save_root["mtk:container_type"] = "SAVE"
        save_cloud = self._make_obj("Save_Test_overworld_VoxelCloud", "MESH")
        save_cloud.parent = save_root
        save_cloud["mtk_is_voxel_cloud"] = True

        ctx_valid = types.SimpleNamespace(active_object=save_root, selected_objects=[save_root])
        # Gating check: returns False when pipeline assets are not ready
        with patch("MoziToolKit.operators.mesh.op_rebuild_mesh.can_execute_asset_pipeline", return_value=(False, "No vanilla pack")):
            self.assertFalse(MOZI_OT_rebuild_mesh.poll(ctx_valid))
        # When assets ready: returns True
        with patch("MoziToolKit.operators.mesh.op_rebuild_mesh.can_execute_asset_pipeline", return_value=(True, "")):
            self.assertTrue(MOZI_OT_rebuild_mesh.poll(ctx_valid))

        # Poll with normal Cube: False even when pipeline is ready
        cube = self._make_obj("Cube", "MESH")
        ctx_invalid = types.SimpleNamespace(active_object=cube, selected_objects=[cube])
        with patch("MoziToolKit.operators.mesh.op_rebuild_mesh.can_execute_asset_pipeline", return_value=(True, "")):
            self.assertFalse(MOZI_OT_rebuild_mesh.poll(ctx_invalid))

    def test_rebuild_mesh_execution_with_companion_cloud(self):
        """Verifies executing mozi.rebuild_mesh on a Save container triggers remeshing from cloud."""
        save_root = self._make_obj("Save_Test_overworld", "EMPTY")
        save_root["mtk:is_container"] = True
        save_root["mtk:container_type"] = "SAVE"
        save_root["mtk_enable_ao"] = True
        save_root["mtk_mesh_fluids"] = True

        save_mesh = self._make_obj("Save_Test_overworld_Mesh", "MESH")
        save_mesh.parent = save_root

        save_cloud = self._make_obj("Save_Test_overworld_VoxelCloud", "MESH")
        save_cloud.parent = save_root
        save_cloud["mtk_is_voxel_cloud"] = True

        context = types.SimpleNamespace(
            active_object=save_root,
            selected_objects=[save_root],
            mode="OBJECT",
            collection=bpy.context.collection,
            scene=bpy.context.scene,
        )

        mock_storage = object()
        class DummyCloudData:
            def __len__(self):
                return 100
            def to_storage(self):
                return mock_storage

        mock_cloud_data = DummyCloudData()
        mock_new_mesh_data = types.SimpleNamespace(used_materials=lambda: [])

        class DummyRebuildOp:
            def __init__(self):
                self.reports = []
                self.report = lambda *args: self.reports.append(args)
                self.run_async = False
                self.enable_ao = True
                self.mesh_fluids = True
                self.weld_vertices = True
                self.origin_centered = True
                self._runner = None

            def execute(self, ctx):
                return MOZI_OT_rebuild_mesh.execute(self, ctx)

        op = DummyRebuildOp()
        mesh_fn_calls = []
        inject_calls = []

        def fake_mesh_voxel_storage(*args, **kwargs):
            mesh_fn_calls.append((args, kwargs))
            return mock_new_mesh_data, 10.5

        def fake_inject(*args, **kwargs):
            inject_calls.append((args, kwargs))

        with patch("MoziToolKit.operators.mesh.op_rebuild_mesh.can_execute_asset_pipeline", return_value=(True, "")), \
             patch("MoziToolKit.operators.mesh.op_rebuild_mesh.check_asset_cache_status", return_value="READY"), \
             patch("MoziToolKit.operators.mesh.op_rebuild_mesh.extract_voxel_point_cloud", return_value=mock_cloud_data), \
             patch("MoziToolKit.operators.mesh.op_rebuild_mesh.mesh_voxel_storage", fake_mesh_voxel_storage), \
             patch("MoziToolKit.operators.mesh.op_rebuild_mesh.inject_mesh_data", fake_inject), \
             patch("MoziToolKit.operators.mesh.op_rebuild_mesh.ensure_world_materials"):

            res = op.execute(context)
            self.assertEqual(res, {"FINISHED"})
            self.assertEqual(len(mesh_fn_calls), 1)
            kwargs = mesh_fn_calls[0][1]
            self.assertTrue(kwargs["enable_ao"])
            self.assertTrue(kwargs["mesh_fluids"])
            self.assertEqual(len(inject_calls), 1)

    def test_rebuild_mesh_execution_with_live_sync_session(self):
        """Verifies executing mozi.rebuild_mesh on active Live Sync container calls session.get_world_mesh."""
        sync_root = self._make_obj("Yefira_World", "EMPTY")
        sync_root["mtk:is_container"] = True
        sync_root["mtk:container_type"] = "SYNC"
        sync_root["mtk:is_yefira_world"] = True

        sync_mesh = self._make_obj("Yefira_World_Mesh", "MESH")
        sync_mesh.parent = sync_root

        context = types.SimpleNamespace(
            active_object=sync_root,
            selected_objects=[sync_root],
            mode="OBJECT",
            collection=bpy.context.collection,
            scene=types.SimpleNamespace(mozi_active_sync_container_name="Yefira_World"),
        )

        mock_mesh_data = types.SimpleNamespace(vertex_count=50)
        get_world_mesh_calls = []
        mock_session = types.SimpleNamespace(
            is_active=True,
            get_world_mesh=lambda: (get_world_mesh_calls.append(True), mock_mesh_data)[1],
            get_storage=lambda: object(),
        )

        class DummyRebuildOp:
            def __init__(self):
                self.reports = []
                self.report = lambda *args: self.reports.append(args)
                self.run_async = False
                self.enable_ao = True
                self.mesh_fluids = True
                self.weld_vertices = True
                self.origin_centered = True
                self._runner = None

            def execute(self, ctx):
                return MOZI_OT_rebuild_mesh.execute(self, ctx)

        op = DummyRebuildOp()
        update_calls = []

        with patch("MoziToolKit.operators.mesh.op_rebuild_mesh.can_execute_asset_pipeline", return_value=(True, "")), \
             patch("MoziToolKit.operators.mesh.op_rebuild_mesh.check_asset_cache_status", return_value="READY"), \
             patch("MoziToolKit.operators.mesh.op_rebuild_mesh.get_sync_bridge_session", return_value=mock_session), \
             patch("MoziToolKit.utils.world.sync_container.update_world_mesh", lambda *args, **kwargs: (update_calls.append(args), (50, 20))[1]):

            res = op.execute(context)
            self.assertEqual(res, {"FINISHED"})
            self.assertEqual(len(get_world_mesh_calls), 1)
            self.assertEqual(len(update_calls), 1)

    def test_rebuild_mesh_live_sync_async_path_resolves_async_task(self):
        """Regression: a later local import must not shadow module-level AsyncTask."""
        sync_root = self._make_obj("Yefira_World_Async", "EMPTY")
        sync_root["mtk:is_container"] = True
        sync_root["mtk:container_type"] = "SYNC"
        sync_root["mtk:is_yefira_world"] = True

        sync_mesh = self._make_obj("Yefira_World_Async_Mesh", "MESH")
        sync_mesh.parent = sync_root

        context = types.SimpleNamespace(
            active_object=sync_root,
            selected_objects=[sync_root],
            mode="OBJECT",
            collection=bpy.context.collection,
            scene=types.SimpleNamespace(mozi_active_sync_container_name="Yefira_World_Async"),
        )

        mock_session = types.SimpleNamespace(
            is_active=True,
            get_world_mesh=lambda: types.SimpleNamespace(),
            get_storage=lambda: object(),
        )

        class DummyRebuildOp:
            def __init__(self):
                self.reports = []
                self.report = lambda *args: self.reports.append(args)
                self.run_async = True
                self.enable_ao = True
                self.mesh_fluids = True
                self.weld_vertices = True
                self.origin_centered = True
                self._runner = None

            def execute(self, ctx):
                return MOZI_OT_rebuild_mesh.execute(self, ctx)

        op = DummyRebuildOp()
        task_calls = []
        runner_calls = []

        class DummyTask:
            def __init__(self, *args, **kwargs):
                task_calls.append((args, kwargs))

        class DummyRunner:
            def __init__(self, *args, **kwargs):
                runner_calls.append((args, kwargs))
            def start(self):
                return {"RUNNING_MODAL"}

        with patch("MoziToolKit.operators.mesh.op_rebuild_mesh.can_execute_asset_pipeline", return_value=(True, "")), \
             patch("MoziToolKit.operators.mesh.op_rebuild_mesh.check_asset_cache_status", return_value="READY"), \
             patch("MoziToolKit.operators.mesh.op_rebuild_mesh.get_sync_bridge_session", return_value=mock_session), \
             patch("MoziToolKit.operators.mesh.op_rebuild_mesh.AsyncTask", DummyTask), \
             patch("MoziToolKit.operators.mesh.op_rebuild_mesh.ModalTaskRunner", DummyRunner):
            self.assertEqual(op.execute(context), {"RUNNING_MODAL"})
            self.assertEqual(len(task_calls), 1)
            self.assertEqual(len(runner_calls), 1)

    def test_save_container_privacy_and_uuid_registry(self):
        """Verifies that local filesystem absolute paths are scrubbed and registered to privacy UUID registry."""
        meta = {
            "level_name": "SecretWorld",
            "version_name": "1.21.4",
            "data_version": 4189,
            "spawn": (10, 70, 10),
        }
        mesh_data = types.SimpleNamespace(used_materials=lambda: [])
        storage = object()

        context = bpy.context

        with patch("MoziToolKit.utils.save.hierarchy.inject_mesh_data"), patch("MoziToolKit.utils.save.hierarchy.ensure_world_materials"):
            root, stats = apply_imported_save_to_blender(
                mesh_data=mesh_data,
                meta=meta,
                storage=storage,
                elapsed_ms=10.0,
                world_dir="/Users/secret_user/Minecraft/saves/SecretWorld",
                dimension="overworld",
                context=context,
            )
            self._created_objects.append(root)

            # 1. UUID must be assigned
            self.assertIn("mozi_save_uuid", root)
            save_uuid = root["mozi_save_uuid"]
            self.assertTrue(bool(save_uuid))

            # 2. Sensitive path must NEVER be stored on the object
            self.assertNotIn("mtk_source_path", root)
            mesh_name = f"{root.name}_Mesh"
            self.assertIn(mesh_name, bpy.data.objects)
            mesh = bpy.data.objects[mesh_name]
            self._created_objects.append(mesh)
            self.assertNotIn("mtk_source_path", mesh)

            # 3. Privacy registry should record the mapping
            reg = get_save_registry()
            info = reg.get_save_info(save_uuid)
            self.assertIsNotNone(info)
            self.assertEqual(info["dimension"], "overworld")

            # 4. Legacy object scrubbing check
            old_obj = self._make_obj("Legacy_Save_Test", "EMPTY")
            old_obj["mtk_source_path"] = "/Users/secret_user/old_save"
            old_obj["mtk_world_name"] = "OldWorld"
            migrated_uuid = sanitize_save_privacy(old_obj)
            self.assertTrue(bool(migrated_uuid))
            self.assertNotIn("mtk_source_path", old_obj)

    def test_save_refresh_and_relink_operators(self):
        """Verifies resolve_save_container, relink operator, and in-place refresh operator."""
        save_root = self._make_obj("Save_TestRelink_overworld", "EMPTY")
        save_root["mtk:is_container"] = True
        save_root["mtk:container_type"] = "SAVE"
        save_root["mozi_save_uuid"] = "test-uuid-12345"
        save_root["mtk_world_name"] = "RelinkWorld"
        save_root["mtk_dimension"] = "overworld"
        save_root["mtk_min_coord"] = [-16, 0, -16]
        save_root["mtk_max_coord"] = [16, 64, 16]

        save_mesh = self._make_obj("Save_TestRelink_overworld_Mesh", "MESH")
        save_mesh.parent = save_root
        save_mesh["mtk:is_save_mesh"] = True
        save_mesh["mozi_save_uuid"] = "test-uuid-12345"

        # 1. Test resolve_save_container
        r, m, c = resolve_save_container(save_mesh)
        self.assertEqual(r, save_root)
        self.assertEqual(m, save_mesh)

        # 2. Relink operator
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "World"
            tmp_path.mkdir()
            (tmp_path / "level.dat").write_text("dummy")

            reg = get_save_registry()
            reg.relink_save("test-uuid-12345", tmp_path)
            self.assertTrue(reg.is_path_valid("test-uuid-12345"))

            # 3. Refresh operator in synchronous mode
            class DummyRefreshOp:
                def __init__(self):
                    self.reports = []
                    self.report = lambda *args: self.reports.append(args)
                    self.run_async = False
                    self._runner = None

                def execute(self, ctx):
                    return MOZI_OT_refresh_save_mesh.execute(self, ctx)

            op = DummyRefreshOp()
            ctx = types.SimpleNamespace(
                active_object=save_mesh,
                selected_objects=[save_mesh],
                collection=bpy.context.collection,
                view_layer=bpy.context.view_layer,
                mode="OBJECT",
            )

            mock_mesh = types.SimpleNamespace(used_materials=lambda: [])
            mock_meta = {
                "level_name": "RelinkWorld",
                "version_name": "1.21.4",
                "data_version": 4189,
                "spawn": (0, 64, 0),
            }
            with patch("MoziToolKit.operators.save.op_refresh_save.can_execute_asset_pipeline", return_value=(True, "")), \
                 patch("MoziToolKit.operators.save.op_refresh_save.check_asset_cache_status", return_value="READY"), \
                 patch("MoziToolKit.operators.save.op_refresh_save.load_and_mesh_minecraft_save", return_value=(mock_mesh, mock_meta, object(), 5.0)), \
                 patch("MoziToolKit.utils.save.hierarchy.inject_mesh_data"), patch("MoziToolKit.utils.save.hierarchy.ensure_world_materials"):
                res = op.execute(ctx)
                self.assertEqual(res, {"FINISHED"})
                self.assertIn("mtk_last_refreshed", save_root)


if __name__ == "__main__":
    unittest.main()

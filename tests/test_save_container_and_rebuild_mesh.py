"""
Unit and integration tests for Minecraft Save Containerization, Non-overwriting Auto-incrementing,
and Unified Mesh Rebuild Operator (mozi.rebuild_mesh) with Right-Click Context Menu.
"""

from __future__ import annotations

import types
import unittest
from unittest.mock import MagicMock, patch

import bpy
from bridge.save import apply_imported_save_to_blender, _resolve_unique_save_container_name
from operators.op_mesh import (
    MOZI_OT_rebuild_mesh,
    resolve_mesh_rebuild_targets,
)
from utils.system.menu_registry import CANONICAL_DEFAULT_PRESETS, CANONICAL_OPERATORS


class _MockObject:
    def __init__(self, name: str, obj_type: str = "EMPTY", data: Any = None):
        self.name = name
        self.type = obj_type
        self.data = data
        self.parent = None
        self.children = []
        self._props = {}
        self.users_collection = [MagicMock()]
        self.location = (0.0, 0.0, 0.0)

    def __getitem__(self, key):
        return self._props[key]

    def __setitem__(self, key, value):
        self._props[key] = value

    def __contains__(self, key):
        return key in self._props

    def get(self, key, default=None):
        return self._props.get(key, default)

    def select_set(self, val):
        pass


IS_REAL_BLENDER = (
    not isinstance(bpy, MagicMock)
    and hasattr(bpy, "app")
    and not isinstance(bpy.app, MagicMock)
    and hasattr(bpy.app, "version")
    and isinstance(bpy.app.version, tuple)
    and bpy.app.version[0] >= 4
    and hasattr(bpy, "data")
    and hasattr(bpy.data, "objects")
    and not isinstance(bpy.data.objects, MagicMock)
)


class TestSaveContainerAndRebuildMesh(unittest.TestCase):
    def setUp(self):
        self._created_names = []
        if not IS_REAL_BLENDER:
            self.orig_objects = getattr(bpy.data, "objects", {})
            self.orig_meshes = getattr(bpy.data, "meshes", {})

            class MockObjectsDict(dict):
                def new(self, name, data=None):
                    obj_type = "MESH" if data is not None else "EMPTY"
                    obj = _MockObject(name, obj_type=obj_type, data=data)
                    self[name] = obj
                    return obj

                def get(self, name, default=None):
                    return super().get(name, default)

            self.mock_objects = MockObjectsDict()
            bpy.data.objects = self.mock_objects

            class MockMeshesDict(dict):
                def new(self, name):
                    m = MagicMock()
                    m.name = name
                    m.vertices = [1, 2, 3]
                    m.polygons = [1]
                    self[name] = m
                    return m

                def get(self, name, default=None):
                    return super().get(name, default)

            self.mock_meshes = MockMeshesDict()
            bpy.data.meshes = self.mock_meshes

    def tearDown(self):
        if not IS_REAL_BLENDER:
            bpy.data.objects = self.orig_objects
            bpy.data.meshes = self.orig_meshes
        else:
            cleanup_names = [
                "Save_Skyblock_overworld", "Save_Skyblock_overworld_01",
                "Save_Skyblock_overworld_Mesh", "Save_Skyblock_overworld_01_Mesh",
                "Save_Test_overworld", "Save_Test_overworld_Mesh", "Save_Test_overworld_VoxelCloud",
                "Yefira_World", "Yefira_World_Mesh", "Cube"
            ]
            for name in cleanup_names:
                if hasattr(bpy.data, "objects") and name in bpy.data.objects:
                    try:
                        bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
                    except Exception:
                        pass
                mesh_name = name if name.endswith("_Mesh") else f"{name}_Mesh"
                if hasattr(bpy.data, "meshes") and mesh_name in bpy.data.meshes:
                    try:
                        bpy.data.meshes.remove(bpy.data.meshes[mesh_name], do_unlink=True)
                    except Exception:
                        pass

    def _make_obj(self, name: str, obj_type: str = "EMPTY", mesh_data=None):
        if IS_REAL_BLENDER:
            if name in bpy.data.objects:
                obj = bpy.data.objects[name]
            else:
                data = None
                if obj_type == "MESH":
                    if isinstance(mesh_data, getattr(bpy.types, "Mesh", (type(None),))):
                        data = mesh_data
                    else:
                        data = bpy.data.meshes.new(name)
                obj = bpy.data.objects.new(name, data)
                if hasattr(bpy.context, "scene") and hasattr(bpy.context.scene, "collection"):
                    if obj.name not in bpy.context.scene.collection.objects:
                        bpy.context.scene.collection.objects.link(obj)
            return obj
        else:
            obj = _MockObject(name, obj_type=obj_type, data=mesh_data)
            bpy.data.objects[name] = obj
            return obj

    def test_save_container_hierarchy_and_incrementing(self):
        """Verifies save imports create isolated Empty containers without overwriting."""
        meta = {
            "level_name": "Skyblock",
            "version_name": "1.21.4",
            "data_version": 4189,
            "spawn": (0, 64, 0),
        }
        mesh_data = MagicMock()
        mesh_data.used_materials.return_value = []
        storage = MagicMock()

        if IS_REAL_BLENDER:
            context = bpy.context
        else:
            context = types.SimpleNamespace(
                collection=MagicMock(),
                view_layer=types.SimpleNamespace(objects=types.SimpleNamespace(active=None)),
                mode="OBJECT",
            )

        with patch("bridge.save.inject_mesh_data"), patch("bridge.save.ensure_world_materials"):
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
            self.assertEqual(mesh1.parent, root1)
            self.assertTrue(mesh1["mtk:is_save_mesh"])

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

            self.assertEqual(root2.name, "Save_Skyblock_overworld_01")
            self.assertNotEqual(root1.name, root2.name)
            self.assertEqual(root2.type, "EMPTY")
            self.assertTrue(root2["mtk:is_container"])

            mesh2_name = f"{root2.name}_Mesh"
            self.assertIn(mesh2_name, bpy.data.objects)
            mesh2 = bpy.data.objects[mesh2_name]
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
        if isinstance(getattr(save_root, "children", None), list):
            save_root.children = [save_mesh, save_cloud]

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
        if isinstance(getattr(sync_root, "children", None), list):
            sync_root.children = [sync_mesh]

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
        if isinstance(getattr(save_root, "children", None), list):
            save_root.children = [save_cloud]

        ctx_valid = types.SimpleNamespace(active_object=save_root, selected_objects=[save_root])
        self.assertTrue(MOZI_OT_rebuild_mesh.poll(ctx_valid))

        # Poll with normal Cube: False
        cube = self._make_obj("Cube", "MESH")
        ctx_invalid = types.SimpleNamespace(active_object=cube, selected_objects=[cube])
        self.assertFalse(MOZI_OT_rebuild_mesh.poll(ctx_invalid))

    def test_rebuild_mesh_execution_with_companion_cloud(self):
        """Verifies executing mozi.rebuild_mesh on a Save container triggers remeshing from cloud."""
        save_root = self._make_obj("Save_Test_overworld", "EMPTY")
        save_root["mtk:is_container"] = True
        save_root["mtk:container_type"] = "SAVE"
        save_root["mtk_enable_ao"] = True
        save_root["mtk_mesh_fluids"] = True

        save_mesh_data = MagicMock()
        save_mesh_data.polygons = [1, 2]
        save_mesh = self._make_obj("Save_Test_overworld_Mesh", "MESH", mesh_data=save_mesh_data)
        save_mesh.parent = save_root

        save_cloud = self._make_obj("Save_Test_overworld_VoxelCloud", "MESH")
        save_cloud.parent = save_root
        save_cloud["mtk_is_voxel_cloud"] = True
        if isinstance(getattr(save_root, "children", None), list):
            save_root.children = [save_mesh, save_cloud]

        context = types.SimpleNamespace(
            active_object=save_root,
            selected_objects=[save_root],
            mode="OBJECT",
            collection=MagicMock(),
            scene=types.SimpleNamespace(),
        )

        mock_cloud_data = MagicMock()
        mock_cloud_data.__len__.return_value = 100
        mock_storage = MagicMock()
        mock_cloud_data.to_storage.return_value = mock_storage
        mock_new_mesh_data = MagicMock()
        mock_new_mesh_data.used_materials.return_value = []

        class DummyRebuildOp:
            def __init__(self):
                self.report = MagicMock()
                self.run_async = False
                self.enable_ao = True
                self.mesh_fluids = True
                self.weld_vertices = True
                self.origin_centered = True
                self._runner = None

            def execute(self, ctx):
                return MOZI_OT_rebuild_mesh.execute(self, ctx)

        op = DummyRebuildOp()

        with patch("operators.op_mesh.extract_voxel_point_cloud", return_value=mock_cloud_data), \
             patch("operators.op_mesh.mesh_voxel_storage", return_value=(mock_new_mesh_data, 10.5)) as mock_mesh_fn, \
             patch("operators.op_mesh.inject_mesh_data") as mock_inject, \
             patch("operators.op_mesh.ensure_world_materials"):

            res = op.execute(context)
            self.assertEqual(res, {"FINISHED"})
            mock_mesh_fn.assert_called_once()
            # Assert inherited settings from root container were passed
            kwargs = mock_mesh_fn.call_args[1]
            self.assertTrue(kwargs["enable_ao"])
            self.assertTrue(kwargs["mesh_fluids"])
            mock_inject.assert_called_once()

    def test_rebuild_mesh_execution_with_live_sync_session(self):
        """Verifies executing mozi.rebuild_mesh on active Live Sync container calls session.get_world_mesh."""
        sync_root = self._make_obj("Yefira_World", "EMPTY")
        sync_root["mtk:is_container"] = True
        sync_root["mtk:container_type"] = "SYNC"
        sync_root["mtk:is_yefira_world"] = True

        sync_mesh_data = MagicMock()
        sync_mesh = self._make_obj("Yefira_World_Mesh", "MESH", mesh_data=sync_mesh_data)
        sync_mesh.parent = sync_root
        if isinstance(getattr(sync_root, "children", None), list):
            sync_root.children = [sync_mesh]

        context = types.SimpleNamespace(
            active_object=sync_root,
            selected_objects=[sync_root],
            mode="OBJECT",
            collection=MagicMock(),
            scene=types.SimpleNamespace(mozi_active_sync_container_name="Yefira_World"),
        )

        mock_session = MagicMock()
        mock_session.is_active = True
        mock_mesh_data = MagicMock()
        mock_mesh_data.vertex_count = 50
        mock_session.get_world_mesh.return_value = mock_mesh_data
        mock_session.get_storage.return_value = MagicMock()

        class DummyRebuildOp:
            def __init__(self):
                self.report = MagicMock()
                self.run_async = False
                self.enable_ao = True
                self.mesh_fluids = True
                self.weld_vertices = True
                self.origin_centered = True
                self._runner = None

            def execute(self, ctx):
                return MOZI_OT_rebuild_mesh.execute(self, ctx)

        op = DummyRebuildOp()

        with patch("operators.op_mesh.get_sync_bridge_session", return_value=mock_session), \
             patch("operators.sync.hierarchy.update_world_mesh", return_value=(50, 20)) as mock_update_fn:

            res = op.execute(context)
            self.assertEqual(res, {"FINISHED"})
            mock_session.get_world_mesh.assert_called_once()
            mock_update_fn.assert_called_once()


"""
Unit tests for Yefira Live Sync Empty Root Container hierarchy,
multi-container isolation, single active session exclusivity, and Data/Object panel poll logic.
Runs 100% inside real Blender host environment with native bpy data structures.
"""

from __future__ import annotations

import types
import unittest

import bpy
from MoziToolKit.utils.world.sync_container import (
    DEFAULT_WORLD_OBJECT_NAME,
    get_or_create_world_container,
    get_or_create_world_mesh_object,
    resolve_world_root_object,
    is_yefira_root_object,
    is_yefira_world_object,
    find_world_mesh_child,
)
from MoziToolKit.operators.sync.properties import (
    get_active_sync_container,
    set_active_sync_container,
)
from MoziToolKit.ui.panel_sync import (
    MOZI_PT_live_sync_data,
    MOZI_PT_live_sync,
)


class TestSyncContainerHierarchyAndExclusivity(unittest.TestCase):
    def setUp(self):
        from MoziToolKit.operators.sync.properties import register as register_sync_props
        try:
            register_sync_props()
        except Exception:
            pass
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

    def _make_obj(self, name: str, obj_type: str = "EMPTY") -> bpy.types.Object:
        if name in bpy.data.objects:
            obj = bpy.data.objects[name]
        else:
            if obj_type == "MESH":
                mesh = bpy.data.meshes.new(name)
                self._created_meshes.append(mesh)
                obj = bpy.data.objects.new(name, mesh)
            else:
                obj = bpy.data.objects.new(name, None)
            if hasattr(bpy.context, "scene") and hasattr(bpy.context.scene, "collection"):
                if obj.name not in bpy.context.scene.collection.objects:
                    bpy.context.scene.collection.objects.link(obj)
            self._created_objects.append(obj)
        return obj

    def test_empty_container_root_and_child_mesh_hierarchy(self):
        """Verifies that creating a world container generates an Empty root and nested child Mesh."""
        context = types.SimpleNamespace(
            active_object=None,
            scene=bpy.context.scene,
            collection=bpy.context.collection,
        )

        root_container = get_or_create_world_container(context, "TestWorld_01")
        self._created_objects.append(root_container)
        self.assertEqual(root_container.type, "EMPTY")
        self.assertTrue(root_container["mtk:is_container"])
        self.assertTrue(root_container["mtk:is_yefira_world"])
        self.assertTrue(is_yefira_root_object(root_container))

        # Create child mesh under this container
        child_mesh = get_or_create_world_mesh_object(context, root_container=root_container)
        self._created_objects.append(child_mesh)
        self.assertEqual(child_mesh.type, "MESH")
        self.assertEqual(child_mesh.parent, root_container)
        self.assertEqual(child_mesh["mtk:geometry_origin"], "SYNC_WORLD")

        # Verify child mesh can climb up and resolve to root container
        resolved = resolve_world_root_object(child_mesh)
        self.assertEqual(resolved, root_container)
        self.assertTrue(is_yefira_world_object(child_mesh))

        # Verify find_world_mesh_child locates child_mesh
        found = find_world_mesh_child(root_container)
        self.assertEqual(found, child_mesh)

    def test_multi_container_properties_and_active_session_binding(self):
        """Verifies that multiple containers have isolated properties and scene tracks active session."""
        scene = bpy.context.scene

        c1 = self._make_obj("Container_A", "EMPTY")
        c1["mtk:is_container"] = True
        c1["mtk:is_yefira_world"] = True
        c1.mozi_sync.url = "ws://127.0.0.1:8765"
        c1.mozi_sync.is_connected = True
        c1.mozi_sync.connection_status = "CONNECTED"

        c2 = self._make_obj("Container_B", "EMPTY")
        c2["mtk:is_container"] = True
        c2["mtk:is_yefira_world"] = True
        c2.mozi_sync.url = "ws://127.0.0.1:9000"
        c2.mozi_sync.is_connected = False
        c2.mozi_sync.connection_status = "DISCONNECTED"

        # 1. Bind Container A as active
        set_active_sync_container(scene, c1)
        self.assertEqual(get_active_sync_container(scene), c1)
        self.assertEqual(c1.mozi_sync.url, "ws://127.0.0.1:8765")
        self.assertEqual(c2.mozi_sync.url, "ws://127.0.0.1:9000")

        # 2. Switch to Container B
        c1.mozi_sync.is_connected = False
        c1.mozi_sync.connection_status = "DISCONNECTED"
        c2.mozi_sync.is_connected = True
        c2.mozi_sync.connection_status = "CONNECTED"
        set_active_sync_container(scene, c2)

        self.assertEqual(get_active_sync_container(scene), c2)
        self.assertFalse(c1.mozi_sync.is_connected)
        self.assertTrue(c2.mozi_sync.is_connected)

    def test_panel_poll_distinguishes_empty_and_mesh(self):
        """Verifies that MOZI_PT_live_sync_data polls for EMPTY and MOZI_PT_live_sync polls for child MESH."""
        container = self._make_obj("MyContainer", "EMPTY")
        container["mtk:is_container"] = True
        container["mtk:is_yefira_world"] = True

        child_mesh = self._make_obj("MyContainer_Mesh", "MESH")
        child_mesh.parent = container
        child_mesh["mtk:is_yefira_mesh"] = True
        child_mesh["mtk:is_yefira_world"] = True

        # When active object is container (EMPTY):
        ctx_container = types.SimpleNamespace(object=container)
        self.assertTrue(MOZI_PT_live_sync_data.poll(ctx_container))
        self.assertFalse(MOZI_PT_live_sync.poll(ctx_container))

        # When active object is child mesh (MESH):
        ctx_mesh = types.SimpleNamespace(object=child_mesh)
        self.assertFalse(MOZI_PT_live_sync_data.poll(ctx_mesh))
        self.assertTrue(MOZI_PT_live_sync.poll(ctx_mesh))

    def test_sync_container_rename_cascades_to_children(self):
        """Verifies that renaming Empty container propagates new prefix to child mesh and point cloud."""
        from MoziToolKit.utils.world.sync_container import sync_container_child_names

        root = self._make_obj("OldWorld", "EMPTY")
        root["mtk:is_container"] = True
        root["mtk:is_yefira_world"] = True
        root["mtk:last_name"] = "OldWorld"

        mesh_obj = self._make_obj("OldWorld_Mesh", "MESH")
        mesh_obj["mtk:is_yefira_mesh"] = True
        mesh_obj.parent = root
        mesh_obj.data.name = "Mesh_OldWorld"

        cloud_obj = self._make_obj("OldWorld_VoxelCloud", "MESH")
        cloud_obj["mtk_is_voxel_cloud"] = True
        cloud_obj.parent = root

        # 1. User renames root container in Outliner
        root.name = "NewWorld"

        # 2. Direct cascade call
        sync_container_child_names(root)
        self.assertEqual(mesh_obj.name, "NewWorld_Mesh")
        self.assertEqual(mesh_obj.data.name, "Mesh_NewWorld")
        self.assertEqual(cloud_obj.name, "NewWorld_VoxelCloud")
        self.assertEqual(root["mtk:last_name"], "NewWorld")

    def test_watcher_depsgraph_listener_triggers_deferred_rename(self):
        """Verifies that watcher catches rename in depsgraph updates and queues deferred sync."""
        from MoziToolKit.operators.sync.watcher import on_sync_depsgraph_update_post, _deferred_sync_renamed_roots, _get_pending_rename_roots

        scene = bpy.context.scene
        scene.mozi_active_sync_container_name = "City_A"
        root = self._make_obj("City_A", "EMPTY")
        root["mtk:is_container"] = True
        root["mtk:is_yefira_world"] = True
        root["mtk:last_name"] = "City_A"

        child_mesh = self._make_obj("City_A_Mesh", "MESH")
        child_mesh["mtk:is_yefira_mesh"] = True
        child_mesh.parent = root
        child_mesh.data.name = "Mesh_City_A"

        # Rename
        root.name = "Metropolis"

        # Depsgraph update event
        mock_update = types.SimpleNamespace(id=root)
        mock_depsgraph = types.SimpleNamespace(updates=[mock_update])

        on_sync_depsgraph_update_post(scene, mock_depsgraph)
        self.assertIn("Metropolis", _get_pending_rename_roots())

        # Execute deferred task
        _deferred_sync_renamed_roots(scene)
        self.assertEqual(child_mesh.name, "Metropolis_Mesh")
        self.assertEqual(scene.mozi_active_sync_container_name, "Metropolis")


if __name__ == "__main__":
    unittest.main()

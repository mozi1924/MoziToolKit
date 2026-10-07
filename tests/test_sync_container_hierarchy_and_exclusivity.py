"""
Unit tests for Yefira Live Sync Empty Root Container hierarchy,
multi-container isolation, single active session exclusivity, and Data/Object panel poll logic.
"""

import unittest
from unittest.mock import MagicMock
import types

import bpy
from operators.sync.hierarchy import (
    DEFAULT_WORLD_OBJECT_NAME,
    get_or_create_world_container,
    get_or_create_world_mesh_object,
    resolve_world_root_object,
    is_yefira_root_object,
    is_yefira_world_object,
    find_world_mesh_child,
)
from operators.sync.properties import (
    get_active_sync_container,
    set_active_sync_container,
)
from ui.panel_sync import (
    MOZI_PT_live_sync_data,
    MOZI_PT_live_sync,
)


class _MockBpyObject:
    def __init__(self, name: str, obj_type: str = "EMPTY"):
        self.name = name
        self.type = obj_type
        self.parent = None
        self.children = []
        self._props = {}
        self.users_collection = [MagicMock()]
        self.location = (0.0, 0.0, 0.0)

    def __getitem__(self, key):
        return self._props[key]

    def __setitem__(self, key, value):
        self._props[key] = value

    def get(self, key, default=None):
        return self._props.get(key, default)


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


class TestSyncContainerHierarchyAndExclusivity(unittest.TestCase):
    def setUp(self):
        if IS_REAL_BLENDER:
            from operators.sync.properties import register as register_sync_props
            try:
                register_sync_props()
            except Exception:
                pass
        else:
            self.orig_objects = getattr(bpy.data, "objects", {})
            self.objects_store = {}

            class MockObjectsDict(dict):
                def new(self, name, data=None):
                    obj_type = "MESH" if data is not None else "EMPTY"
                    obj = _MockBpyObject(name, obj_type=obj_type)
                    self[name] = obj
                    return obj

                def get(self, name, default=None):
                    return super().get(name, default)

            bpy.data.objects = MockObjectsDict()

            class MockMeshesDict(dict):
                def new(self, name):
                    m = MagicMock()
                    m.name = name
                    m.vertices = []
                    m.polygons = []
                    self[name] = m
                    return m

            bpy.data.meshes = MockMeshesDict()

    def tearDown(self):
        if not IS_REAL_BLENDER:
            bpy.data.objects = self.orig_objects
        else:
            cleanup_names = [
                "TestWorld_01", "TestWorld_01_Mesh", "Container_Alpha", "Container_Beta", "Container_Gamma",
                "Yefira_World", "Yefira_World_Mesh", "Yefira_World_VoxelCloud",
                "Container_A", "Container_B", "MyContainer", "MyContainer_Mesh",
                "OldWorld", "OldWorld_Mesh", "OldWorld_VoxelCloud", "NewWorld", "NewWorld_Mesh", "NewWorld_VoxelCloud",
                "City_A", "City_A_Mesh", "Metropolis", "Metropolis_Mesh", "TestWorld_01", "TestWorld_01_Mesh",
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

    def _make_obj(self, name: str, obj_type: str = "EMPTY"):
        if IS_REAL_BLENDER:
            if name in bpy.data.objects:
                obj = bpy.data.objects[name]
            else:
                data = bpy.data.meshes.new(name) if obj_type == "MESH" else None
                obj = bpy.data.objects.new(name, data)
                if hasattr(bpy.context, "scene") and hasattr(bpy.context.scene, "collection"):
                    if obj.name not in bpy.context.scene.collection.objects:
                        bpy.context.scene.collection.objects.link(obj)
            return obj
        else:
            obj = _MockBpyObject(name, obj_type=obj_type)
            bpy.data.objects[name] = obj
            return obj

    def test_empty_container_root_and_child_mesh_hierarchy(self):
        """Verifies that creating a world container generates an Empty root and nested child Mesh."""
        context = types.SimpleNamespace(
            active_object=None,
            scene=types.SimpleNamespace(
                collection=MagicMock(),
                mozi_sync=types.SimpleNamespace(url="ws://127.0.0.1:8765"),
            ),
            collection=MagicMock(),
        )

        root_container = get_or_create_world_container(context, "TestWorld_01")
        self.assertEqual(root_container.type, "EMPTY")
        self.assertTrue(root_container["mtk:is_container"])
        self.assertTrue(root_container["mtk:is_yefira_world"])
        self.assertTrue(is_yefira_root_object(root_container))

        # Create child mesh under this container
        child_mesh = get_or_create_world_mesh_object(context, root_container=root_container)
        self.assertEqual(child_mesh.type, "MESH")
        self.assertEqual(child_mesh.parent, root_container)
        if isinstance(getattr(root_container, "children", None), list):
            root_container.children.append(child_mesh)

        # Verify child mesh can climb up and resolve to root container
        resolved = resolve_world_root_object(child_mesh)
        self.assertEqual(resolved, root_container)
        self.assertTrue(is_yefira_world_object(child_mesh))

        # Verify find_world_mesh_child locates child_mesh
        found = find_world_mesh_child(root_container)
        self.assertEqual(found, child_mesh)

    def test_multi_container_properties_and_active_session_binding(self):
        """Verifies that multiple containers have isolated properties and scene tracks active session."""
        scene = types.SimpleNamespace(mozi_active_sync_container_name="")

        c1 = self._make_obj("Container_A", "EMPTY")
        c1["mtk:is_container"] = True
        c1["mtk:is_yefira_world"] = True
        if hasattr(c1, "mozi_sync") and hasattr(c1.mozi_sync, "url"):
            c1.mozi_sync.url = "ws://127.0.0.1:8765"
            c1.mozi_sync.is_connected = True
            c1.mozi_sync.connection_status = "CONNECTED"
        else:
            c1.mozi_sync = types.SimpleNamespace(url="ws://127.0.0.1:8765", is_connected=True, connection_status="CONNECTED")

        c2 = self._make_obj("Container_B", "EMPTY")
        c2["mtk:is_container"] = True
        c2["mtk:is_yefira_world"] = True
        if hasattr(c2, "mozi_sync") and hasattr(c2.mozi_sync, "url"):
            c2.mozi_sync.url = "ws://127.0.0.1:9000"
            c2.mozi_sync.is_connected = False
            c2.mozi_sync.connection_status = "DISCONNECTED"
        else:
            c2.mozi_sync = types.SimpleNamespace(url="ws://127.0.0.1:9000", is_connected=False, connection_status="DISCONNECTED")

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
        if isinstance(getattr(container, "children", None), list):
            container.children.append(child_mesh)

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
        from operators.sync.hierarchy import sync_container_child_names

        root = self._make_obj("OldWorld", "EMPTY")
        root["mtk:is_container"] = True
        root["mtk:is_yefira_world"] = True
        root["mtk:last_name"] = "OldWorld"

        mesh_obj = self._make_obj("OldWorld_Mesh", "MESH")
        mesh_obj["mtk:is_yefira_mesh"] = True
        mesh_obj.parent = root
        if IS_REAL_BLENDER:
            mesh_obj.data.name = "Mesh_OldWorld"
        else:
            mesh_obj.data = types.SimpleNamespace(name="Mesh_OldWorld")
        if isinstance(getattr(root, "children", None), list):
            root.children.append(mesh_obj)

        cloud_obj = self._make_obj("OldWorld_VoxelCloud", "MESH")
        cloud_obj["mtk_is_voxel_cloud"] = True
        cloud_obj.parent = root
        if isinstance(getattr(root, "children", None), list):
            root.children.append(cloud_obj)

        # 1. User renames root container in Outliner
        root.name = "NewWorld"
        if not IS_REAL_BLENDER:
            bpy.data.objects["NewWorld"] = root

        # 2. Direct cascade call
        sync_container_child_names(root)
        self.assertEqual(mesh_obj.name, "NewWorld_Mesh")
        self.assertEqual(mesh_obj.data.name, "Mesh_NewWorld")
        self.assertEqual(cloud_obj.name, "NewWorld_VoxelCloud")
        self.assertEqual(root["mtk:last_name"], "NewWorld")

    def test_watcher_depsgraph_listener_triggers_deferred_rename(self):
        """Verifies that watcher catches rename in depsgraph updates and queues deferred sync."""
        from operators.sync.watcher import on_sync_depsgraph_update_post, _deferred_sync_renamed_roots, _get_pending_rename_roots

        scene = types.SimpleNamespace(mozi_active_sync_container_name="City_A")
        root = self._make_obj("City_A", "EMPTY")
        root["mtk:is_container"] = True
        root["mtk:is_yefira_world"] = True
        root["mtk:last_name"] = "City_A"

        child_mesh = self._make_obj("City_A_Mesh", "MESH")
        child_mesh["mtk:is_yefira_mesh"] = True
        child_mesh.parent = root
        if IS_REAL_BLENDER:
            child_mesh.data.name = "Mesh_City_A"
        else:
            child_mesh.data = types.SimpleNamespace(name="Mesh_City_A")
        if isinstance(getattr(root, "children", None), list):
            root.children.append(child_mesh)

        # Rename
        root.name = "Metropolis"
        if not IS_REAL_BLENDER:
            bpy.data.objects["Metropolis"] = root

        # Mock depsgraph update event
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

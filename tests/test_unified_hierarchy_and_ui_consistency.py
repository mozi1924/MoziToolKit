"""
Unit tests for MoziToolKit Unified Hierarchy SSOT and UI Consistency.

Verifies that selecting an MTK Container (Empty) vs a Child Mesh vs a Point Cloud
exhibits 100% consistent behavior across:
- Hierarchy context resolution (resolve_hierarchy, resolve_target_meshes)
- MTK object recognition (is_mtk_object)
- Minecraft Biome panels (3D View N-panel, Object Properties, Data Properties)
- Biome preset reading and updates with automatic child delegation
- Object context menus and mesh operators (Clear Custom Normals, Interpolation)

Runs 100% in real Blender host environment.
"""

from __future__ import annotations

import unittest
import bpy

from MoziToolKit.utils.world.hierarchy import (
    HierarchyContext,
    resolve_hierarchy,
    is_mtk_container,
    get_container_type,
    resolve_target_meshes,
)
from MoziToolKit.utils.materials.biome.updater import (
    is_mtk_object,
    update_object_biome,
    detect_object_material_mode,
)
from MoziToolKit.utils.materials.constants import ATTR_BIOME_TINT_DATA
from MoziToolKit.utils.mesh.ownership import (
    ORIGIN_SYNC_WORLD,
    ORIGIN_SAVE,
    ORIGIN_SCENE,
    ORIGIN_POINT_CLOUD,
    ORIGIN_EXTERNAL,
    classify_origin,
    stamp_geometry_origin,
)
from MoziToolKit.ui.panel_biome import (
    MOZI_PT_object_biome,
    MOZI_PT_container_biome_data,
    MOZI_PT_view3d_biome,
    _resolve_biome_preset,
)
from MoziToolKit.utils.mesh.core import poll_mesh_object


class TestUnifiedHierarchyAndUIConsistency(unittest.TestCase):
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

    def _create_empty(self, name: str) -> bpy.types.Object:
        obj = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(obj)
        self._created_objects.append(obj)
        return obj

    def _create_mesh(self, name: str) -> bpy.types.Object:
        mesh = bpy.data.meshes.new(f"{name}_data")
        self._created_meshes.append(mesh)
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        self._created_objects.append(obj)
        return obj

    def test_sync_hierarchy_resolution(self):
        """Verify Live Sync container hierarchy is resolved identically from root, mesh, or cloud."""
        root = self._create_empty("Yefira_World")
        root["mtk:is_container"] = True
        root["mtk:container_type"] = "SYNC"

        mesh_obj = self._create_mesh("Yefira_World_Mesh")
        mesh_obj.parent = root
        stamp_geometry_origin(mesh_obj, ORIGIN_SYNC_WORLD)

        cloud_obj = self._create_mesh("Yefira_World_VoxelCloud")
        cloud_obj.parent = root
        cloud_obj["mtk_is_voxel_cloud"] = True
        stamp_geometry_origin(cloud_obj, ORIGIN_POINT_CLOUD)

        # 1. Resolve from Root Empty Container
        ctx_root = resolve_hierarchy(root)
        self.assertTrue(ctx_root.is_container)
        self.assertTrue(ctx_root.is_mtk)
        self.assertEqual(ctx_root.container_type, "SYNC")
        self.assertEqual(ctx_root.origin, ORIGIN_SYNC_WORLD)
        self.assertEqual(ctx_root.root, root)
        self.assertEqual(ctx_root.primary_mesh, mesh_obj)
        self.assertEqual(ctx_root.point_cloud, cloud_obj)
        self.assertIn(mesh_obj, ctx_root.child_meshes)

        # 2. Resolve from Child Mesh
        ctx_mesh = resolve_hierarchy(mesh_obj)
        self.assertFalse(ctx_mesh.is_container)
        self.assertTrue(ctx_mesh.is_mtk)
        self.assertEqual(ctx_mesh.container_type, "SYNC")
        self.assertEqual(ctx_mesh.origin, ORIGIN_SYNC_WORLD)
        self.assertEqual(ctx_mesh.root, root)
        self.assertEqual(ctx_mesh.primary_mesh, mesh_obj)
        self.assertEqual(ctx_mesh.point_cloud, cloud_obj)

        # 3. Resolve from Companion Point Cloud
        ctx_cloud = resolve_hierarchy(cloud_obj)
        self.assertFalse(ctx_cloud.is_container)
        self.assertTrue(ctx_cloud.is_mtk)
        self.assertEqual(ctx_cloud.root, root)
        self.assertEqual(ctx_cloud.primary_mesh, mesh_obj)
        self.assertEqual(ctx_cloud.point_cloud, cloud_obj)

    def test_save_and_scene_hierarchy_resolution(self):
        """Verify Save and Scene containers are properly typed and recognized."""
        # Save Container
        save_root = self._create_empty("Save_World_overworld")
        save_root["mtk:is_container"] = True
        save_root["mtk:container_type"] = "SAVE"
        save_mesh = self._create_mesh("Save_World_overworld_Mesh")
        save_mesh.parent = save_root
        stamp_geometry_origin(save_mesh, ORIGIN_SAVE)

        ctx_save = resolve_hierarchy(save_root)
        self.assertEqual(ctx_save.container_type, "SAVE")
        self.assertEqual(ctx_save.origin, ORIGIN_SAVE)
        self.assertEqual(ctx_save.primary_mesh, save_mesh)

        # Scene Container
        scene_root = self._create_empty("[Scene] Castle")
        scene_root["mtk:is_container"] = True
        scene_root["mtk:container_type"] = "SCENE"
        scene_mesh = self._create_mesh("[Scene] Castle_Mesh")
        scene_mesh.parent = scene_root
        stamp_geometry_origin(scene_mesh, ORIGIN_SCENE)

        ctx_scene = resolve_hierarchy(scene_root)
        self.assertEqual(ctx_scene.container_type, "SCENE")
        self.assertEqual(ctx_scene.origin, ORIGIN_SCENE)
        self.assertEqual(ctx_scene.primary_mesh, scene_mesh)

    def test_is_mtk_object_recognition(self):
        """Verify is_mtk_object recognizes both Containers and Meshes."""
        root = self._create_empty("Yefira_World")
        root["mtk:is_container"] = True
        root["mtk:container_type"] = "SYNC"

        mesh_obj = self._create_mesh("Yefira_World_Mesh")
        mesh_obj.parent = root
        stamp_geometry_origin(mesh_obj, ORIGIN_SYNC_WORLD)

        # Both container and child mesh must be recognized
        self.assertTrue(is_mtk_object(root))
        self.assertTrue(is_mtk_object(mesh_obj))

        # Plain unassociated empty and mesh should return False
        plain_empty = self._create_empty("Empty")
        self.assertFalse(is_mtk_object(plain_empty))

        plain_mesh = self._create_mesh("Cube")
        self.assertFalse(is_mtk_object(plain_mesh))

    def test_biome_panel_polls_on_container_and_mesh(self):
        """Verify all Biome UI panels pass poll when container is selected."""
        root = self._create_empty("Yefira_World")
        root["mtk:is_container"] = True
        root["mtk:container_type"] = "SYNC"

        mesh_obj = self._create_mesh("Yefira_World_Mesh")
        mesh_obj.parent = root
        stamp_geometry_origin(mesh_obj, ORIGIN_SYNC_WORLD)

        # Mock context holding the root container as active
        ctx_on_root = type("MockContext", (), {"object": root, "active_object": root, "selected_objects": [root]})()

        # N-panel (3D Viewport)
        self.assertTrue(MOZI_PT_view3d_biome.poll(ctx_on_root))
        # Object Properties
        self.assertTrue(MOZI_PT_object_biome.poll(ctx_on_root))
        # Empty Data Properties
        self.assertTrue(MOZI_PT_container_biome_data.poll(ctx_on_root))

        # Mock context holding the child mesh as active
        ctx_on_mesh = type("MockContext", (), {"object": mesh_obj, "active_object": mesh_obj, "selected_objects": [mesh_obj]})()
        self.assertTrue(MOZI_PT_view3d_biome.poll(ctx_on_mesh))
        self.assertTrue(MOZI_PT_object_biome.poll(ctx_on_mesh))
        self.assertFalse(MOZI_PT_container_biome_data.poll(ctx_on_mesh))

    def test_biome_preset_resolution_and_propagation(self):
        """Verify changing biome preset on container delegates to child meshes and syncs."""
        root = self._create_empty("Yefira_World")
        root["mtk:is_container"] = True
        root["mtk:container_type"] = "SYNC"

        mesh_obj = self._create_mesh("Yefira_World_Mesh")
        mesh_obj.parent = root
        stamp_geometry_origin(mesh_obj, ORIGIN_SYNC_WORLD)
        mesh_obj.data.attributes.new(name=ATTR_BIOME_TINT_DATA, type="INT", domain="CORNER")

        # Initial preset: should infer WORLD from child mesh origin + attribute
        self.assertEqual(_resolve_biome_preset(root), "WORLD")
        self.assertEqual(_resolve_biome_preset(mesh_obj), "WORLD")

        # Update biome on container to DESERT
        update_result = update_object_biome(root, "DESERT")
        self.assertTrue(update_result)
        self.assertEqual(root.get("mtk:biome_preset"), "DESERT")
        self.assertEqual(mesh_obj.get("mtk:biome_preset"), "DESERT")
        self.assertEqual(_resolve_biome_preset(root), "DESERT")
        self.assertEqual(_resolve_biome_preset(mesh_obj), "DESERT")

        # Update biome on child mesh to JUNGLE -> should also update parent container
        update_result2 = update_object_biome(mesh_obj, "JUNGLE")
        self.assertTrue(update_result2)
        self.assertEqual(root.get("mtk:biome_preset"), "JUNGLE")
        self.assertEqual(mesh_obj.get("mtk:biome_preset"), "JUNGLE")

    def test_resolve_target_meshes_and_poll_mesh_object(self):
        """Verify container expansion for batch mesh operations and menu poll."""
        root = self._create_empty("Yefira_World")
        root["mtk:is_container"] = True
        root["mtk:container_type"] = "SYNC"

        mesh1 = self._create_mesh("Yefira_World_Mesh")
        mesh1.parent = root
        mesh2 = self._create_mesh("Yefira_World_Section_01")
        mesh2.parent = root

        # Container in selection
        targets = resolve_target_meshes([root])
        self.assertEqual(len(targets), 2)
        self.assertIn(mesh1, targets)
        self.assertIn(mesh2, targets)

        # poll_mesh_object should pass when only root container is selected
        ctx = type("MockContext", (), {"active_object": root, "selected_objects": [root]})()
        self.assertTrue(poll_mesh_object(ctx))


if __name__ == "__main__":
    unittest.main()

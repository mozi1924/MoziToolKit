"""
Tests for mesh origin classification and the material / reconstruction boundary.

Covers:
* explicit ``mtk:geometry_origin`` stamping and legacy inference
* external meshes staying external after material provenance injection
* Replace Material poll restricted to external meshes
* Rebuild Mesh requiring a voxel source (cloud or active Live Sync session)
Runs 100% inside real Blender host environment with native bpy data structures.
"""

from __future__ import annotations

import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import bpy

from MoziToolKit.operators.op_materials import MOZI_OT_replace_material
from MoziToolKit.operators.mesh import MOZI_OT_rebuild_mesh, resolve_mesh_rebuild_targets
from MoziToolKit.utils.mesh.ownership import (
    ORIGIN_EXTERNAL,
    ORIGIN_POINT_CLOUD,
    ORIGIN_SAVE,
    ORIGIN_SYNC_SECTION,
    ORIGIN_SYNC_WORLD,
    classify_origin,
    find_voxel_cloud,
    has_voxel_source,
    is_external_mesh,
    stamp_geometry_origin,
)


class TestMeshOwnership(unittest.TestCase):
    def setUp(self):
        self._created: list[bpy.types.Object] = []

    def tearDown(self):
        for obj in reversed(self._created):
            try:
                mesh = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if mesh is not None and getattr(mesh, "users", 0) == 0:
                    bpy.data.meshes.remove(mesh)
            except Exception:
                pass

    def _make_obj(self, name: str, obj_type: str = "EMPTY", data=None) -> bpy.types.Object:
        if obj_type == "MESH":
            mesh = data if data is not None else bpy.data.meshes.new(name)
            obj = bpy.data.objects.new(name, mesh)
        else:
            obj = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(obj)
        self._created.append(obj)
        return obj

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def test_external_mesh_with_provenance_stays_external(self):
        """Replace Material writes provenance; it must not change ownership."""
        mesh = bpy.data.meshes.new("Character_Hair_Mesh")
        mesh.attributes.new(name="mtk_source_texture_key", type="INT", domain="CORNER")
        obj = self._make_obj("Character_Hair", "MESH", data=mesh)

        self.assertEqual(classify_origin(obj), ORIGIN_EXTERNAL)
        self.assertTrue(is_external_mesh(obj))

    def test_explicit_origin_wins(self):
        obj = self._make_obj("Save_Test_Mesh", "MESH")
        obj["mtk:geometry_origin"] = ORIGIN_SAVE
        self.assertEqual(classify_origin(obj), ORIGIN_SAVE)

    def test_legacy_markers(self):
        save_mesh = self._make_obj("AnyName", "MESH")
        save_mesh["mtk:is_save_mesh"] = True
        self.assertEqual(classify_origin(save_mesh), ORIGIN_SAVE)

        sync_mesh = self._make_obj("AnyName2", "MESH")
        sync_mesh["mtk:is_yefira_mesh"] = True
        self.assertEqual(classify_origin(sync_mesh), ORIGIN_SYNC_WORLD)

        section_mesh = self._make_obj("AnyName3", "MESH")
        section_mesh["mtk:is_section_mesh"] = True
        self.assertEqual(classify_origin(section_mesh), ORIGIN_SYNC_SECTION)

        cloud = self._make_obj("AnyName_VoxelCloud", "MESH")
        self.assertEqual(classify_origin(cloud), ORIGIN_POINT_CLOUD)

    def test_legacy_name_fallbacks_removed(self):
        save_mesh = self._make_obj("Save_World_overworld_Mesh", "MESH")
        self.assertEqual(classify_origin(save_mesh), ORIGIN_EXTERNAL)

        sync_mesh = self._make_obj("Yefira_World_Mesh", "MESH")
        self.assertEqual(classify_origin(sync_mesh), ORIGIN_EXTERNAL)

        voxel_mesh = self._make_obj("MTK_World", "MESH")
        self.assertEqual(classify_origin(voxel_mesh), ORIGIN_EXTERNAL)

    def test_container_roots(self):
        save_root = self._make_obj("Save_Test_overworld", "EMPTY")
        save_root["mtk:is_container"] = True
        save_root["mtk:container_type"] = "SAVE"
        self.assertEqual(classify_origin(save_root), ORIGIN_SAVE)

        sync_root = self._make_obj("Yefira_World", "EMPTY")
        sync_root["mtk:is_container"] = True
        sync_root["mtk:container_type"] = "SYNC"
        self.assertEqual(classify_origin(sync_root), ORIGIN_SYNC_WORLD)

    def test_stamp_is_idempotent_unless_overwritten(self):
        obj = self._make_obj("Mesh", "MESH")
        stamp_geometry_origin(obj, ORIGIN_SAVE)
        self.assertEqual(classify_origin(obj), ORIGIN_SAVE)

        stamp_geometry_origin(obj, ORIGIN_SYNC_WORLD)
        self.assertEqual(classify_origin(obj), ORIGIN_SAVE)

        stamp_geometry_origin(obj, ORIGIN_SYNC_WORLD, overwrite=True)
        self.assertEqual(classify_origin(obj), ORIGIN_SYNC_WORLD)

    def test_unknown_origin_is_ignored(self):
        obj = self._make_obj("Mesh", "MESH")
        stamp_geometry_origin(obj, "NOT_A_REAL_ORIGIN")
        self.assertEqual(classify_origin(obj), ORIGIN_EXTERNAL)

    # ------------------------------------------------------------------
    # Voxel source discovery
    # ------------------------------------------------------------------

    def test_find_voxel_cloud_via_children(self):
        root = self._make_obj("Save_Test_overworld", "EMPTY")
        cloud = self._make_obj("Save_Test_overworld_VoxelCloud", "MESH")
        cloud["mtk_is_voxel_cloud"] = True
        cloud.parent = root

        self.assertIs(find_voxel_cloud(root), cloud)
        self.assertTrue(has_voxel_source(root))

    def test_find_voxel_cloud_via_explicit_prop(self):
        mesh = self._make_obj("Save_Test_overworld_Mesh", "MESH")
        cloud = self._make_obj("Save_Test_overworld_VoxelCloud", "MESH")
        cloud["mtk_is_voxel_cloud"] = True
        mesh["mtk_voxel_cloud"] = cloud.name

        self.assertIs(find_voxel_cloud(mesh), cloud)

    def test_find_voxel_cloud_missing(self):
        mesh = self._make_obj("Lonely_Mesh", "MESH")
        self.assertIsNone(find_voxel_cloud(mesh))
        self.assertFalse(has_voxel_source(mesh))

    # ------------------------------------------------------------------
    # Replace Material poll
    # ------------------------------------------------------------------

    def test_replace_material_poll_external_only(self):
        external = self._make_obj("Cube", "MESH")
        with patch("MoziToolKit.operators.op_materials.can_execute_asset_pipeline", return_value=(True, "")):
            self.assertTrue(MOZI_OT_replace_material.poll(types.SimpleNamespace(active_object=external)))

        save_mesh = self._make_obj("Save_World_overworld_Mesh", "MESH")
        stamp_geometry_origin(save_mesh, ORIGIN_SAVE)
        with patch("MoziToolKit.operators.op_materials.can_execute_asset_pipeline", return_value=(True, "")):
            self.assertFalse(MOZI_OT_replace_material.poll(types.SimpleNamespace(active_object=save_mesh)))

        cloud = self._make_obj("Save_World_overworld_VoxelCloud", "MESH")
        with patch("MoziToolKit.operators.op_materials.can_execute_asset_pipeline", return_value=(True, "")):
            self.assertFalse(MOZI_OT_replace_material.poll(types.SimpleNamespace(active_object=cloud)))

        self.assertFalse(MOZI_OT_replace_material.poll(types.SimpleNamespace(active_object=None)))

    # ------------------------------------------------------------------
    # Rebuild Mesh poll
    # ------------------------------------------------------------------

    def _context(self, active, active_name=""):
        return types.SimpleNamespace(
            active_object=active,
            selected_objects=[active],
            scene=types.SimpleNamespace(mozi_active_sync_container_name=active_name),
        )

    def test_rebuild_poll_save_requires_cloud(self):
        root = self._make_obj("Save_WithCloud", "EMPTY")
        root["mtk:is_container"] = True
        root["mtk:container_type"] = "SAVE"
        mesh = self._make_obj("Save_WithCloud_Mesh", "MESH")
        mesh.parent = root
        mesh["mtk:is_save_mesh"] = True
        cloud = self._make_obj("Save_WithCloud_VoxelCloud", "MESH")
        cloud["mtk_is_voxel_cloud"] = True
        cloud.parent = root

        with patch("MoziToolKit.operators.mesh.op_rebuild_mesh.can_execute_asset_pipeline", return_value=(True, "")):
            self.assertTrue(MOZI_OT_rebuild_mesh.poll(self._context(root)))

        orphan_root = self._make_obj("Save_NoCloud", "EMPTY")
        orphan_root["mtk:is_container"] = True
        orphan_root["mtk:container_type"] = "SAVE"
        orphan_mesh = self._make_obj("Save_NoCloud_Mesh", "MESH")
        orphan_mesh.parent = orphan_root
        orphan_mesh["mtk:is_save_mesh"] = True

        with patch("MoziToolKit.operators.mesh.op_rebuild_mesh.can_execute_asset_pipeline", return_value=(True, "")):
            self.assertFalse(MOZI_OT_rebuild_mesh.poll(self._context(orphan_root)))

    def test_rebuild_poll_live_session_bypasses_cloud(self):
        root = self._make_obj("Yefira_World", "EMPTY")
        root["mtk:is_container"] = True
        root["mtk:container_type"] = "SYNC"
        root["mtk:is_yefira_world"] = True
        mesh = self._make_obj("Yefira_World_Mesh", "MESH")
        mesh.parent = root
        mesh["mtk:is_yefira_mesh"] = True

        context = self._context(root, active_name=root.name)

        active_session = SimpleNamespace(is_active=True)
        with patch("MoziToolKit.operators.mesh.op_rebuild_mesh.can_execute_asset_pipeline", return_value=(True, "")), \
             patch("MoziToolKit.operators.mesh.op_rebuild_mesh.get_sync_bridge_session", return_value=active_session):
            self.assertTrue(MOZI_OT_rebuild_mesh.poll(context))

        inactive_session = SimpleNamespace(is_active=False)
        with patch("MoziToolKit.operators.mesh.op_rebuild_mesh.can_execute_asset_pipeline", return_value=(True, "")), \
             patch("MoziToolKit.operators.mesh.op_rebuild_mesh.get_sync_bridge_session", return_value=inactive_session):
            self.assertFalse(MOZI_OT_rebuild_mesh.poll(context))

    def test_rebuild_poll_rejects_external_mesh_under_container(self):
        root = self._make_obj("Save_Container", "EMPTY")
        root["mtk:is_container"] = True
        root["mtk:container_type"] = "SAVE"
        external = self._make_obj("User_Import", "MESH")
        external.parent = root
        cloud = self._make_obj("Save_Container_VoxelCloud", "MESH")
        cloud["mtk_is_voxel_cloud"] = True
        cloud.parent = root

        self.assertFalse(MOZI_OT_rebuild_mesh.poll(self._context(root)))

    def test_resolve_prefers_mtk_mesh_over_external_sibling(self):
        root = self._make_obj("Save_Mixed", "EMPTY")
        root["mtk:is_container"] = True
        root["mtk:container_type"] = "SAVE"

        external = self._make_obj("User_Import", "MESH")
        external.parent = root

        save_mesh = self._make_obj("Save_Mixed_Mesh", "MESH")
        save_mesh.parent = root
        save_mesh["mtk:is_save_mesh"] = True

        cloud = self._make_obj("Save_Mixed_VoxelCloud", "MESH")
        cloud["mtk_is_voxel_cloud"] = True
        cloud.parent = root

        _, world, resolved_cloud, source_type = resolve_mesh_rebuild_targets(self._context(root))
        self.assertIs(world, save_mesh)
        self.assertIs(resolved_cloud, cloud)
        self.assertEqual(source_type, "SAVE")
        with patch("MoziToolKit.operators.mesh.op_rebuild_mesh.can_execute_asset_pipeline", return_value=(True, "")):
            self.assertTrue(MOZI_OT_rebuild_mesh.poll(self._context(root)))

    def test_rebuild_poll_rejects_provenance_only_external_mesh(self):
        mesh = bpy.data.meshes.new("Character_Hair_Mesh_2")
        mesh.attributes.new(name="mtk_source_texture_key", type="INT", domain="CORNER")
        external = self._make_obj("Character_Hair_2", "MESH", data=mesh)
        self.assertFalse(MOZI_OT_rebuild_mesh.poll(self._context(external)))


if __name__ == "__main__":
    unittest.main()

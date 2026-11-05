"""
Unit tests for Voxel Point Cloud Visibility and Carve Mode Operators & UI Panel.
Ensures no mutual exclusion bugs between visibility toggle and carve mode.
Runs 100% inside real Blender host environment with native bpy data structures.
"""

from __future__ import annotations

import types
import unittest
from unittest.mock import patch

import bpy
from MoziToolKit.operators.op_voxel_cloud import (
    MOZI_OT_carve_voxel_cloud,
    MOZI_OT_toggle_voxel_cloud,
    _resolve_world_and_cloud_objects,
)
from MoziToolKit.ui.panel_voxel_storage import MOZI_PT_view3d_voxel_tools


class _OperatorProxy:
    """Minimal proxy carrying operator properties into execute()."""
    def __init__(self, action: str = "TOGGLE"):
        self.action = action
        self.reports: list[tuple[str, str]] = []

    def report(self, level, message):
        self.reports.append((str(level), str(message)))


class TestVoxelCloudOperators(unittest.TestCase):
    def setUp(self):
        # Create real Blender mesh data blocks & objects
        self.mesh_w = bpy.data.meshes.new("Test_WorldMesh_Data")
        self.world_obj = bpy.data.objects.new("Test_WorldMesh", self.mesh_w)
        bpy.context.collection.objects.link(self.world_obj)

        self.mesh_c = bpy.data.meshes.new("Test_CloudMesh_Data")
        self.cloud_obj = bpy.data.objects.new("Test_WorldMesh_VoxelCloud", self.mesh_c)
        bpy.context.collection.objects.link(self.cloud_obj)

        self.cloud_obj.parent = self.world_obj
        self.cloud_obj["mtk_is_voxel_cloud"] = True
        self.cloud_obj["mtk_world_mesh"] = self.world_obj.name
        self.world_obj["mtk_voxel_cloud"] = self.cloud_obj.name

        # Create real Blender Mask modifier
        self.mask_mod = self.cloud_obj.modifiers.new(name="MTK_Voxel_Mask", type="MASK")
        self.mask_mod.invert_vertex_group = True

        bpy.context.view_layer.objects.active = self.world_obj
        self.world_obj.select_set(True)

    def tearDown(self):
        if bpy.context.mode != "OBJECT" and hasattr(bpy.ops.object, "mode_set"):
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass

        for obj in (self.cloud_obj, self.world_obj):
            if obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in (self.mesh_c, self.mesh_w):
            if mesh.name in bpy.data.meshes:
                bpy.data.meshes.remove(mesh)

    def test_resolve_world_and_cloud_objects(self):
        bpy.context.view_layer.objects.active = self.world_obj
        w, c = _resolve_world_and_cloud_objects(bpy.context)
        self.assertEqual(w, self.world_obj)
        self.assertEqual(c, self.cloud_obj)

        bpy.context.view_layer.objects.active = self.cloud_obj
        w, c = _resolve_world_and_cloud_objects(bpy.context)
        self.assertEqual(w, self.world_obj)
        self.assertEqual(c, self.cloud_obj)

        # Empty container root: container holds both meshes as children
        root = bpy.data.objects.new("Test_[Container]_World", None)
        bpy.context.collection.objects.link(root)
        self.world_obj.parent = root
        self.cloud_obj.parent = root
        bpy.context.view_layer.objects.active = root

        w, c = _resolve_world_and_cloud_objects(bpy.context)
        self.assertEqual(w, self.world_obj)
        self.assertEqual(c, self.cloud_obj)

        bpy.data.objects.remove(root, do_unlink=True)

    def test_toggle_visibility_explicit_actions(self):
        bpy.context.view_layer.objects.active = self.world_obj
        # Initial state: hidden (invert_vertex_group = True)
        self.assertTrue(self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group)

        # 1. Action: SHOW
        op1 = _OperatorProxy(action="SHOW")
        res1 = MOZI_OT_toggle_voxel_cloud.execute(op1, bpy.context)
        self.assertEqual(res1, {"FINISHED"})
        self.assertFalse(self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group)

        # 2. Action: HIDE
        op2 = _OperatorProxy(action="HIDE")
        res2 = MOZI_OT_toggle_voxel_cloud.execute(op2, bpy.context)
        self.assertEqual(res2, {"FINISHED"})
        self.assertTrue(self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group)

        # 3. Action: TOGGLE from hidden -> visible
        op3 = _OperatorProxy(action="TOGGLE")
        res3 = MOZI_OT_toggle_voxel_cloud.execute(op3, bpy.context)
        self.assertEqual(res3, {"FINISHED"})
        self.assertFalse(self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group)

    def test_toggle_hide_while_in_edit_mode_exits_cleanly(self):
        bpy.context.view_layer.objects.active = self.cloud_obj
        self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group = False
        bpy.ops.object.mode_set(mode="EDIT")
        self.assertEqual(bpy.context.mode, "EDIT_MESH")

        op = _OperatorProxy(action="HIDE")
        res = MOZI_OT_toggle_voxel_cloud.execute(op, bpy.context)
        self.assertEqual(res, {"FINISHED"})
        self.assertEqual(bpy.context.view_layer.objects.active, self.world_obj)
        self.assertTrue(self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group)
        self.assertEqual(bpy.context.mode, "OBJECT")

    def test_carve_mode_enter_when_cloud_already_visible_does_not_hide(self):
        bpy.context.view_layer.objects.active = self.world_obj
        self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group = False

        op = _OperatorProxy(action="ENTER")
        res = MOZI_OT_carve_voxel_cloud.execute(op, bpy.context)
        self.assertEqual(res, {"FINISHED"})

        # Cloud must STILL be visible (NOT inverted/hidden)
        self.assertFalse(self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group)
        self.assertEqual(bpy.context.view_layer.objects.active, self.cloud_obj)

    def test_carve_mode_exit_restores_world_mesh_and_keeps_cloud_visible(self):
        bpy.context.view_layer.objects.active = self.cloud_obj
        self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group = False
        bpy.ops.object.mode_set(mode="EDIT")

        op = _OperatorProxy(action="EXIT")
        res = MOZI_OT_carve_voxel_cloud.execute(op, bpy.context)
        self.assertEqual(res, {"FINISHED"})

        self.assertEqual(bpy.context.view_layer.objects.active, self.world_obj)
        self.assertFalse(self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group)
        self.assertEqual(bpy.context.mode, "OBJECT")


class TestVoxelToolsPanelUI(unittest.TestCase):
    def setUp(self):
        self.mesh_w = bpy.data.meshes.new("Test_UI_WorldMesh")
        self.world_obj = bpy.data.objects.new("Test_UI_WorldMesh", self.mesh_w)
        bpy.context.collection.objects.link(self.world_obj)

        self.mesh_c = bpy.data.meshes.new("Test_UI_VoxelCloud")
        self.cloud_obj = bpy.data.objects.new("Test_UI_VoxelCloud", self.mesh_c)
        bpy.context.collection.objects.link(self.cloud_obj)

        self.cloud_obj["mtk_is_voxel_cloud"] = True
        self.cloud_obj["mtk_world_mesh"] = self.world_obj.name
        self.world_obj["mtk_voxel_cloud"] = self.cloud_obj.name
        self.cloud_obj.modifiers.new(name="MTK_Voxel_Mask", type="MASK")

    def tearDown(self):
        for obj in (self.cloud_obj, self.world_obj):
            if obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in (self.mesh_c, self.mesh_w):
            if mesh.name in bpy.data.meshes:
                bpy.data.meshes.remove(mesh)

    def test_panel_draw_does_not_render_mask_threshold(self):
        bpy.context.view_layer.objects.active = self.world_obj

        class DummyLayout:
            def __init__(self):
                self.props = []

            def box(self):
                return self

            def row(self, **kwargs):
                return self

            def column(self, **kwargs):
                return self

            def prop(self, data, prop_name, **kwargs):
                self.props.append((prop_name, kwargs.get("text", "")))

            def label(self, **kwargs):
                pass

            def separator(self, **kwargs):
                pass

            def split(self, **kwargs):
                return self

            def operator(self, *args, **kwargs):
                return types.SimpleNamespace()

        dummy_layout = DummyLayout()
        mock_panel = types.SimpleNamespace(layout=dummy_layout)

        with patch("MoziToolKit.ui.panel_voxel_storage._resolve_target_cloud", return_value=(self.world_obj, self.cloud_obj)):
            MOZI_PT_view3d_voxel_tools.draw(mock_panel, bpy.context)

        for prop_name, text in dummy_layout.props:
            self.assertNotEqual(prop_name, "threshold")
            self.assertNotIn("Threshold", text)


if __name__ == "__main__":
    unittest.main()

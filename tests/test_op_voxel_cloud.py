"""
Unit tests for Voxel Point Cloud Visibility and Carve Mode Operators & UI Panel.
Ensures no mutual exclusion bugs between visibility toggle and carve mode.
Compatible with both headless mock pytest and full Blender host environments.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import bpy
from operators.op_voxel_cloud import (
    MOZI_OT_carve_voxel_cloud,
    MOZI_OT_toggle_voxel_cloud,
    _resolve_world_and_cloud_objects,
    _enter_carve_mode,
    _exit_carve_mode,
)
from ui.panel_voxel_storage import MOZI_PT_view3d_voxel_tools, _resolve_target_cloud


class MockModifier:
    def __init__(self, name: str, mod_type: str = "MASK"):
        self.name = name
        self.type = mod_type
        self.invert_vertex_group = False
        self.threshold = 0.5


class MockObject:
    def __init__(self, name: str, obj_type: str = "MESH"):
        self.name = name
        self.type = obj_type
        self.parent = None
        self.children = []
        self._props = {}
        self.modifiers = {}
        self.hide_viewport = False
        self._hidden = False
        self._selected = False
        self.data = MagicMock()
        self.data.vertices = [MagicMock() for _ in range(10)]

    def get(self, key, default=None):
        return self._props.get(key, default)

    def __getitem__(self, key):
        return self._props[key]

    def __setitem__(self, key, value):
        self._props[key] = value

    def hide_get(self):
        return self._hidden

    def hide_set(self, val):
        self._hidden = bool(val)

    def select_set(self, val):
        self._selected = bool(val)


class MockOperatorSelf:
    def __init__(self, action: str = "TOGGLE", enter_edit_mode: bool = False):
        self.action = action
        self.enter_edit_mode = enter_edit_mode
        self.reports = []

    def report(self, level, message):
        self.reports.append((level, message))


class TestVoxelCloudOperators(unittest.TestCase):
    def setUp(self):
        self.world_obj = MockObject("WorldMesh", "MESH")
        self.cloud_obj = MockObject("WorldMesh_VoxelCloud", "MESH")
        self.cloud_obj["mtk_is_voxel_cloud"] = True
        self.cloud_obj["mtk_world_mesh"] = self.world_obj.name
        self.world_obj["mtk_voxel_cloud"] = self.cloud_obj.name
        self.cloud_obj.parent = self.world_obj
        self.world_obj.children.append(self.cloud_obj)

        mask_mod = MockModifier("MTK_Voxel_Mask", "MASK")
        # Default: mask modifier hides all points initially
        mask_mod.invert_vertex_group = True
        self.cloud_obj.modifiers["MTK_Voxel_Mask"] = mask_mod

    def _make_context(self, active_obj, mode="OBJECT"):
        ctx = MagicMock()
        ctx.active_object = active_obj
        ctx.selected_objects = [active_obj]
        ctx.mode = mode
        ctx.view_layer = MagicMock()
        ctx.view_layer.objects.active = active_obj
        ctx.space_data = MagicMock()
        ctx.space_data.shading = MagicMock()
        ctx.tool_settings = MagicMock()
        ctx.tool_settings.mesh_select_mode = (False, False, True)
        return ctx

    def test_resolve_world_and_cloud_objects(self):
        ctx1 = self._make_context(self.world_obj)
        w, c = _resolve_world_and_cloud_objects(ctx1)
        self.assertEqual(w, self.world_obj)
        self.assertEqual(c, self.cloud_obj)

        ctx2 = self._make_context(self.cloud_obj)
        w, c = _resolve_world_and_cloud_objects(ctx2)
        self.assertEqual(w, self.world_obj)
        self.assertEqual(c, self.cloud_obj)

        # Empty container root
        root = MockObject("[Container] World", "EMPTY")
        root.children = [self.world_obj, self.cloud_obj]
        ctx3 = self._make_context(root)
        w, c = _resolve_world_and_cloud_objects(ctx3)
        self.assertEqual(w, self.world_obj)
        self.assertEqual(c, self.cloud_obj)

    def test_toggle_visibility_explicit_actions(self):
        ctx = self._make_context(self.world_obj)

        # Initial state: hidden (invert_vertex_group = True)
        self.assertTrue(self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group)

        # 1. Action: SHOW
        op1 = MockOperatorSelf(action="SHOW")
        res1 = MOZI_OT_toggle_voxel_cloud.execute(op1, ctx)
        self.assertEqual(res1, {"FINISHED"})
        self.assertFalse(self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group)

        # 2. Action: HIDE
        op2 = MockOperatorSelf(action="HIDE")
        res2 = MOZI_OT_toggle_voxel_cloud.execute(op2, ctx)
        self.assertEqual(res2, {"FINISHED"})
        self.assertTrue(self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group)

        # 3. Action: TOGGLE from hidden -> visible
        op3 = MockOperatorSelf(action="TOGGLE")
        res3 = MOZI_OT_toggle_voxel_cloud.execute(op3, ctx)
        self.assertEqual(res3, {"FINISHED"})
        self.assertFalse(self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group)

    def test_toggle_hide_while_in_edit_mode_exits_cleanly(self):
        # User is in EDIT_MESH mode on the cloud
        ctx = self._make_context(self.cloud_obj, mode="EDIT_MESH")
        self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group = False

        op = MockOperatorSelf(action="HIDE")
        res = MOZI_OT_toggle_voxel_cloud.execute(op, ctx)
        self.assertEqual(res, {"FINISHED"})
        # Must restore active to world_obj
        self.assertEqual(ctx.view_layer.objects.active, self.world_obj)
        # Cloud must be masked
        self.assertTrue(self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group)

    def test_carve_mode_enter_when_cloud_already_visible_does_not_hide(self):
        """
        Critical regression test:
        When cloud is ALREADY VISIBLE, clicking Carve Mode must NOT toggle/hide it!
        It must keep cloud visible and transition to Edit Mode.
        """
        ctx = self._make_context(self.world_obj, mode="OBJECT")

        # Make cloud already visible
        self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group = False

        op = MockOperatorSelf(action="ENTER")
        res = MOZI_OT_carve_voxel_cloud.execute(op, ctx)
        self.assertEqual(res, {"FINISHED"})

        # Cloud must STILL be visible (NOT inverted/hidden)
        self.assertFalse(self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group)
        # Cloud must be active in view layer
        self.assertEqual(ctx.view_layer.objects.active, self.cloud_obj)
        # X-Ray must be enabled
        self.assertTrue(ctx.space_data.shading.show_xray)
        # Mesh select mode must be Vertex only
        self.assertEqual(ctx.tool_settings.mesh_select_mode, (True, False, False))

    def test_carve_mode_exit_restores_world_mesh_and_keeps_cloud_visible(self):
        ctx = self._make_context(self.cloud_obj, mode="EDIT_MESH")
        self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group = False

        op = MockOperatorSelf(action="EXIT")
        res = MOZI_OT_carve_voxel_cloud.execute(op, ctx)
        self.assertEqual(res, {"FINISHED"})

        self.assertEqual(ctx.view_layer.objects.active, self.world_obj)
        # Point cloud must remain visible so user can inspect edited voxels
        self.assertFalse(self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group)

    def test_toggle_voxel_cloud_enter_edit_mode_backward_compat(self):
        op = MockOperatorSelf(enter_edit_mode=True)
        ctx = self._make_context(self.world_obj)

        res = MOZI_OT_toggle_voxel_cloud.execute(op, ctx)
        self.assertEqual(res, {"FINISHED"})
        # Should have unmasked cloud and set active to cloud_obj
        self.assertFalse(self.cloud_obj.modifiers["MTK_Voxel_Mask"].invert_vertex_group)
        self.assertEqual(ctx.view_layer.objects.active, self.cloud_obj)


class TestVoxelToolsPanelUI(unittest.TestCase):
    def setUp(self):
        self.world_obj = MockObject("WorldMesh", "MESH")
        self.cloud_obj = MockObject("WorldMesh_VoxelCloud", "MESH")
        self.cloud_obj["mtk_is_voxel_cloud"] = True
        self.cloud_obj["mtk_world_mesh"] = self.world_obj.name
        self.world_obj["mtk_voxel_cloud"] = self.cloud_obj.name
        mask_mod = MockModifier("MTK_Voxel_Mask", "MASK")
        self.cloud_obj.modifiers["MTK_Voxel_Mask"] = mask_mod

    def test_panel_draw_does_not_render_mask_threshold(self):
        ctx = MagicMock()
        ctx.active_object = self.world_obj
        ctx.mode = "OBJECT"

        mock_layout = MagicMock()
        mock_box = MagicMock()
        mock_layout.box.return_value = mock_box
        mock_row = MagicMock()
        mock_box.row.return_value = mock_row
        mock_col = MagicMock()
        mock_box.column.return_value = mock_col

        mock_panel = MagicMock()
        mock_panel.layout = mock_layout

        with patch("ui.panel_voxel_storage._resolve_target_cloud", return_value=(self.world_obj, self.cloud_obj)):
            MOZI_PT_view3d_voxel_tools.draw(mock_panel, ctx)

        # Verify prop() was never called with threshold
        for call in mock_row.prop.call_args_list:
            args, kwargs = call
            self.assertNotEqual(args[1] if len(args) > 1 else kwargs.get("property"), "threshold")
            self.assertNotIn("Threshold", kwargs.get("text", ""))


if __name__ == "__main__":
    unittest.main()

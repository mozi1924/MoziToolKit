"""
Voxel Point Cloud Storage & Carving Control Panel for 3D Viewport.
Provides UI for controlling Mask modifier visibility, weight thresholds,
direct vertex carving, and mesh/material reconstruction.
"""

from __future__ import annotations

import bpy
from bpy.props import FloatProperty

try:
    from ..bridge.point_cloud import (
        get_associated_voxel_cloud,
        is_voxel_cloud_visible,
        MASK_MODIFIER_NAME,
    )
    from ..i18n import tr
except (ImportError, ValueError):
    from bridge.point_cloud import (
        get_associated_voxel_cloud,
        is_voxel_cloud_visible,
        MASK_MODIFIER_NAME,
    )
    try:
        from i18n import tr
    except (ImportError, ValueError):
        def tr(msgid: str, msgctxt: str | None = None) -> str:
            return msgid


def _resolve_target_cloud(context) -> tuple[Optional[bpy.types.Object], Optional[bpy.types.Object]]:
    active = context.active_object
    if active is None or active.type != "MESH":
        return None, None
    if active.get("mtk_is_voxel_cloud"):
        world_name = active.get("mtk_world_mesh") or active.parent.name if active.parent else None
        world_obj = bpy.data.objects.get(world_name) if world_name else None
        return world_obj, active
    cloud_obj = get_associated_voxel_cloud(active)
    return active, cloud_obj


class MOZI_PT_view3d_voxel_storage(bpy.types.Panel):
    """Voxel Storage & Point Cloud Control Panel in 3D Viewport Sidebar."""

    bl_label = "Voxel Storage (Point Cloud)"
    bl_idname = "MOZI_PT_view3d_voxel_storage"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mozi"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        world_obj, cloud_obj = _resolve_target_cloud(context)
        return cloud_obj is not None

    def draw(self, context):
        layout = self.layout
        world_obj, cloud_obj = _resolve_target_cloud(context)
        if cloud_obj is None:
            layout.label(text=tr("No Voxel Cloud associated."), icon="INFO")
            return

        v_count = len(cloud_obj.data.vertices)
        visible = is_voxel_cloud_visible(cloud_obj)
        mask_mod = cloud_obj.modifiers.get(MASK_MODIFIER_NAME)

        # 1. Status Box
        box = layout.box()
        col = box.column(align=True)
        row1 = col.row(align=True)
        row1.label(text=f"{tr('Voxel Count')}: {v_count}", icon="POINTCLOUD_DATA")
        row1.label(text=f"{tr('Status')}: {tr('Visible') if visible else tr('Masked (Hidden)')}")

        if world_obj:
            row2 = col.row(align=True)
            row2.scale_y = 0.8
            row2.label(text=f"{tr('Target Mesh')}: {world_obj.name}", icon="MESH_DATA")

        if context.mode == "EDIT_MESH" and context.active_object == cloud_obj:
            tip_box = layout.box()
            tip_box.alert = True
            tip_box.label(text=tr("Carving Active: Delete vertices, then Remesh below"), icon="COLORSET_01_VEC")

        # 2. Mask Modifier Visibility & Threshold Controls
        box_mask = layout.box()
        box_mask.label(text=tr("Mask Modifier (Hide/Show Voxels)"), icon="MOD_MASK")
        
        row_btn = box_mask.row(align=True)
        if visible:
            row_btn.operator(
                "mozi.toggle_voxel_cloud",
                text=tr("Hide Voxel Cloud (Apply Mask)"),
                icon="HIDE_ON",
            )
        else:
            row_btn.operator(
                "mozi.toggle_voxel_cloud",
                text=tr("Show Voxel Cloud (Unmask)"),
                icon="HIDE_OFF",
            )

        row_edit = box_mask.row(align=True)
        op_edit = row_edit.operator(
            "mozi.toggle_voxel_cloud",
            text=tr("Enter Voxel Carving (Edit Mode)"),
            icon="EDITMODE_HLT",
        )
        op_edit.enter_edit_mode = True

        if mask_mod and mask_mod.type == "MASK":
            row_thresh = box_mask.row(align=True)
            row_thresh.prop(mask_mod, "threshold", text=tr("Mask Threshold"), slider=True)

        # 3. Actions: Remesh & Rematerialize
        col_actions = layout.column(align=True)
        col_actions.scale_y = 1.25
        col_actions.operator(
            "mozi.remesh_from_voxel_cloud",
            text=tr("Remesh from Voxel Cloud"),
            icon="MOD_REMESH",
        )
        col_actions.operator(
            "mozi.rematerialize_from_voxel_cloud",
            text=tr("Rematerialize from Voxel Cloud"),
            icon="MATERIAL",
        )


classes = (
    MOZI_PT_view3d_voxel_storage,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

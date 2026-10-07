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


class MOZI_PT_view3d_voxel_tools(bpy.types.Panel):
    """Comprehensive Voxel & Mesh Tools Panel in 3D Viewport Sidebar."""

    bl_label = "Voxel & Mesh Tools"
    bl_idname = "MOZI_PT_view3d_voxel_tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mozi"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def draw(self, context):
        layout = self.layout
        world_obj, cloud_obj = _resolve_target_cloud(context)

        # -------------------------------------------------------------
        # 1. Voxel Remesh & Point Cloud Section
        # -------------------------------------------------------------
        box_voxel = layout.box()
        b_head = box_voxel.row(align=True)
        b_head.label(text=tr("Voxel Remesh & Point Cloud:"), icon="MOD_REMESH")

        row_remesh = box_voxel.row(align=True)
        row_remesh.scale_y = 1.25
        row_remesh.operator(
            "mozi.rebuild_mesh",
            text=tr("Rebuild Voxel Mesh"),
            icon="MOD_REMESH",
        )

        if cloud_obj is not None:
            v_count = len(cloud_obj.data.vertices)
            visible = is_voxel_cloud_visible(cloud_obj)
            mask_mod = cloud_obj.modifiers.get(MASK_MODIFIER_NAME)

            col_cloud = box_voxel.column(align=True)
            r_st = col_cloud.row(align=True)
            r_st.label(text=f"{tr('Voxel Count')}: {v_count}", icon="POINTCLOUD_DATA")
            r_st.label(text=f"{tr('Status')}: {tr('Visible') if visible else tr('Masked (Hidden)')}")

            if context.mode == "EDIT_MESH" and context.active_object == cloud_obj:
                tip_box = box_voxel.box()
                tip_box.alert = True
                tip_box.label(text=tr("Carving Active: Delete vertices, then Remesh"), icon="COLORSET_01_VEC")

            r_toggle = box_voxel.row(align=True)
            if visible:
                r_toggle.operator(
                    "mozi.toggle_voxel_cloud",
                    text=tr("Hide Voxel Cloud (Mask)"),
                    icon="HIDE_ON",
                )
            else:
                r_toggle.operator(
                    "mozi.toggle_voxel_cloud",
                    text=tr("Show Voxel Cloud (Unmask)"),
                    icon="HIDE_OFF",
                )

            op_edit = r_toggle.operator(
                "mozi.toggle_voxel_cloud",
                text=tr("Carve Mode"),
                icon="EDITMODE_HLT",
            )
            op_edit.enter_edit_mode = True

            if mask_mod and mask_mod.type == "MASK":
                r_thresh = box_voxel.row(align=True)
                r_thresh.prop(mask_mod, "threshold", text=tr("Mask Threshold"), slider=True)
        else:
            r_cloud_gen = box_voxel.row(align=True)
            r_cloud_gen.operator(
                "mozi.toggle_voxel_cloud",
                text=tr("Toggle Voxel Point Cloud"),
                icon="POINTCLOUD_DATA",
            )

        layout.separator()

        # -------------------------------------------------------------
        # 2. Mesh Geometry & Topology Section
        # -------------------------------------------------------------
        box_mesh = layout.box()
        m_head = box_mesh.row(align=True)
        m_head.label(text=tr("Mesh Geometry & Topology:"), icon="MESH_DATA")

        row_geo = box_mesh.row(align=True)
        row_geo.operator("mozi.adaptive_pixel_split", text=tr("Adaptive Pixel Split"), icon="GRID")
        row_geo.operator("mozi.cull_mesh_faces", text=tr("Cull Occluded Faces"), icon="MOD_BOOLEAN")

        props_extrude = getattr(context.scene, "mozi_auto_extrude_repair", None)
        row_ext = box_mesh.row(align=True)
        if props_extrude:
            row_ext.prop(props_extrude, "enabled", text=tr("Auto Extrude Repair"), toggle=True, icon="NORMALS_FACE")
        row_ext.operator("mozi.random_extrude", text=tr("Random Extrude"), icon="MOD_EXPLODE")

        layout.separator()

        # -------------------------------------------------------------
        # 3. UV & Material Tools Section
        # -------------------------------------------------------------
        box_mat = layout.box()
        mat_head = box_mat.row(align=True)
        mat_head.label(text=tr("UV & Material Tools:"), icon="MATERIAL")

        col_mat_ops = box_mat.column(align=True)
        r_mat1 = col_mat_ops.row(align=True)
        r_mat1.operator("mozi.replace_material", text=tr("Replace Material"), icon="MATERIAL")
        r_mat1.operator("mozi.repair_fluid_uv", text=tr("Repair Fluid UV"), icon="UV_DATA")

        r_mat2 = col_mat_ops.row(align=True)
        r_mat2.operator("mozi.clear_custom_normals", text=tr("Clear Custom Normals"), icon="NORMALS_VERTEX")
        r_mat2.operator("mozi.set_texture_interpolation_closest", text=tr("Interpolation: Closest"), icon="IMAGE_DATA")


# Backward compatibility alias
MOZI_PT_view3d_voxel_storage = MOZI_PT_view3d_voxel_tools

classes = (
    MOZI_PT_view3d_voxel_tools,
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

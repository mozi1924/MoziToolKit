"""
Voxel Point Cloud Storage & Carving Control Panel for 3D Viewport.
Provides UI for controlling Mask modifier visibility, weight thresholds,
direct vertex carving, and mesh/material reconstruction.
"""

from __future__ import annotations

import bpy

from .ownership_hint import draw_mesh_origin_hint

from ..utils.point_cloud import (
    get_associated_voxel_cloud,
    is_voxel_cloud_visible,
    MASK_MODIFIER_NAME,
)
from ..i18n import tr
from ..utils.mesh.ownership import ORIGIN_SAVE, classify_origin
from ..utils.system import get_prefs
from .common import draw_vanilla_pack_warning


def _resolve_target_cloud(context) -> tuple[Optional[bpy.types.Object], Optional[bpy.types.Object]]:
    if context is None:
        return None, None
    active = getattr(context, "active_object", None)
    if active is None:
        selected = getattr(context, "selected_objects", [])
        active = selected[0] if selected else None
    if active is None:
        return None, None

    if getattr(active, "type", "") == "MESH":
        if active.get("mtk_is_voxel_cloud"):
            world_name = active.get("mtk_world_mesh") or (active.parent.name if active.parent else None)
            world_obj = bpy.data.objects.get(world_name) if world_name else None
            return world_obj, active
        cloud_obj = get_associated_voxel_cloud(active)
        return active, cloud_obj

    if getattr(active, "type", "") == "EMPTY":
        cloud_obj = get_associated_voxel_cloud(active)
        world_obj = None
        for child in getattr(active, "children", []):
            if getattr(child, "type", "") == "MESH" and not child.get("mtk_is_voxel_cloud"):
                world_obj = child
                break
        return world_obj, cloud_obj

    return None, None


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

        draw_vanilla_pack_warning(
            layout,
            get_prefs(context),
            "Configure a Vanilla Client JAR in Preferences to enable meshing and material replacement.",
        )

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

        if cloud_obj is None and classify_origin(getattr(context, "active_object", None)) == ORIGIN_SAVE:
            warn = box_voxel.column(align=True)
            warn.alert = True
            warn.label(
                text=tr("Voxel Cloud missing: re-import the save to enable Rebuild."),
                icon="ERROR",
            )

        if cloud_obj is not None:
            v_count = len(cloud_obj.data.vertices)
            visible = is_voxel_cloud_visible(cloud_obj)
            is_carving = (
                getattr(context, "mode", "OBJECT") == "EDIT_MESH"
                and getattr(context, "active_object", None) == cloud_obj
            )

            col_cloud = box_voxel.column(align=True)
            r_st = col_cloud.row(align=True)
            r_st.label(text=f"{tr('Voxel Count')}: {v_count}", icon="POINTCLOUD_DATA")
            if is_carving:
                r_st.label(text=f"{tr('Status')}: {tr('Carving (Edit Mode)')}")
            else:
                r_st.label(text=f"{tr('Status')}: {tr('Visible') if visible else tr('Masked (Hidden)')}")

            if is_carving:
                tip_box = box_voxel.box()
                tip_box.alert = True
                tip_box.label(text=tr("Carving Active: Delete vertices, then Remesh"), icon="COLORSET_01_VEC")

            r_toggle = box_voxel.row(align=True)
            # Visibility Button: toggles Mask modifier unmask/mask
            if visible:
                op_vis = r_toggle.operator(
                    "mozi.toggle_voxel_cloud",
                    text=tr("Hide Voxel Cloud (Mask)"),
                    icon="HIDE_ON",
                )
                op_vis.action = "HIDE"
            else:
                op_vis = r_toggle.operator(
                    "mozi.toggle_voxel_cloud",
                    text=tr("Show Voxel Cloud (Unmask)"),
                    icon="HIDE_OFF",
                )
                op_vis.action = "SHOW"

            # Carve Mode Button: switches to vertex edit mode or returns to object mode
            if is_carving:
                op_edit = r_toggle.operator(
                    "mozi.carve_voxel_cloud",
                    text=tr("Exit Carve Mode"),
                    icon="CHECKMARK",
                    depress=True,
                )
                op_edit.action = "EXIT"
            else:
                op_edit = r_toggle.operator(
                    "mozi.carve_voxel_cloud",
                    text=tr("Carve Mode"),
                    icon="EDITMODE_HLT",
                    depress=False,
                )
                op_edit.action = "ENTER"
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

        draw_mesh_origin_hint(box_mat, context)

        col_mat_ops = box_mat.column(align=True)
        r_mat1 = col_mat_ops.row(align=True)
        r_mat1.operator("mozi.replace_material", text=tr("Replace Material"), icon="MATERIAL")
        r_mat1.operator("mozi.repair_fluid_uv", text=tr("Repair Fluid UV"), icon="UV_DATA")

        r_mat2 = col_mat_ops.row(align=True)
        r_mat2.operator("mozi.clear_custom_normals", text=tr("Clear Custom Normals"), icon="NORMALS_VERTEX")
        r_mat2.operator("mozi.set_texture_interpolation_closest", text=tr("Interpolation: Closest"), icon="IMAGE_DATA")


classes = (
    MOZI_PT_view3d_voxel_tools,
)


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

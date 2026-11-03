"""
MoziToolKit UI Panels for Minecraft Save Containers.
Provides dedicated inspection and model refresh cards in 3D Viewport sidebar
and Object Properties tabs.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

try:
    import bpy
except ImportError:
    bpy = None

from ..i18n import tr

from ..operators.save.properties import get_save_properties
from ..operators.save.utils import (
    is_save_child_object,
    is_save_root_container,
    resolve_save_container,
)
from ..utils.system.save_registry import get_save_registry
from ..utils.system import get_prefs
from .common import draw_vanilla_pack_warning


def _draw_save_container_ui(layout: bpy.types.UILayout, context: bpy.types.Context):
    """Draws dedicated inspection and refresh UI for Minecraft Save containers."""
    draw_vanilla_pack_warning(
        layout,
        get_prefs(context),
        "Configure a Vanilla Client JAR in Preferences to enable save refresh.",
    )

    active_obj = getattr(context, "active_object", None)
    if not active_obj:
        layout.label(text=tr("No active object"), icon='INFO')
        return

    root_obj, mesh_obj, cloud_obj = resolve_save_container(active_obj)
    target = root_obj or mesh_obj
    if not target or not hasattr(target, "get"):
        layout.label(text=tr("No Minecraft Save container found"), icon='INFO')
        return

    save_uuid = str(target.get("mozi_save_uuid") or target.get("mtk:container_id") or "")
    world_name = str(target.get("mtk_world_name", "Minecraft World"))
    mc_version = str(target.get("mtk_mc_version", "Unknown"))
    dimension = str(target.get("mtk_dimension", "overworld"))
    min_coord = list(target.get("mtk_min_coord", [-64, -64, -64]))
    max_coord = list(target.get("mtk_max_coord", [64, 320, 64]))
    last_refreshed_ts = target.get("mtk_last_refreshed")
    props = get_save_properties(target)

    # 1. Container Hierarchy Card
    box_hier = layout.box()
    if root_obj and active_obj != root_obj:
        row = box_hier.row(align=True)
        child_icon = 'MESH_DATA' if getattr(active_obj, "type", "") == 'MESH' else 'POINTCLOUD_DATA'
        row.label(text=f"{tr('Child')}: {active_obj.name}", icon=child_icon)

        row_p = box_hier.row(align=True)
        row_p.label(text=f"{tr('Parent Container')}: {root_obj.name}", icon='EMPTY_AXIS')
        op_sel = row_p.operator("mozi.sync_select_root", text=tr("Select Parent"), icon='RESTRICT_SELECT_OFF')
        op_sel.container_name = root_obj.name
    else:
        name_str = root_obj.name if root_obj else (active_obj.name if active_obj else "")
        row = box_hier.row(align=True)
        row.label(text=f"{tr('Save Container')}: {name_str}", icon='EMPTY_AXIS')

        m_name = mesh_obj.name if mesh_obj else tr("None")
        c_name = cloud_obj.name if cloud_obj else tr("None")
        row_sub = box_hier.row(align=True)
        row_sub.scale_y = 0.85
        row_sub.label(text=f"Mesh: {m_name} | Cloud: {c_name}")

    # 2. World & Selection Info Card
    box_world = layout.box()
    box_world.label(text=tr("World Metadata"), icon='WORLD')

    col_meta = box_world.column(align=True)
    row_m1 = col_meta.row(align=True)
    row_m1.label(text=f"{tr('Level Name')}: {world_name}")
    row_m1.label(text=f"{tr('Version')}: {mc_version}")

    row_m2 = col_meta.row(align=True)
    row_m2.label(text=f"{tr('World Dimension')}: {dimension}")

    # AABB Bounds & Volume (Current Model Geometry)
    dx = abs(max_coord[0] - min_coord[0]) + 1
    dy = abs(max_coord[1] - min_coord[1]) + 1
    dz = abs(max_coord[2] - min_coord[2]) + 1
    vol = dx * dy * dz

    box_bounds = layout.box()
    row_b_head = box_bounds.row(align=True)
    row_b_head.label(text=tr("3D Selection Bounds"), icon='SNAP_INCREMENT')
    if props and props.is_dirty:
        row_b_head.label(text=tr("Pending Changes (Unsaved)"), icon='COLOR')

    col_b = box_bounds.column(align=True)
    col_b.label(text=f"Min: ({min_coord[0]}, {min_coord[1]}, {min_coord[2]})")
    col_b.label(text=f"Max: ({max_coord[0]}, {max_coord[1]}, {max_coord[2]})")
    col_b.label(text=f"{tr('Size')}: {dx} × {dy} × {dz} ({vol:,} {tr('blocks')})", icon='INFO')

    if mesh_obj and hasattr(mesh_obj, "data"):
        b_mesh = mesh_obj.data
        v_cnt = len(b_mesh.vertices) if hasattr(b_mesh, "vertices") else 0
        p_cnt = len(b_mesh.polygons) if hasattr(b_mesh, "polygons") else 0
        col_b.label(text=f"{tr('Geometry')}: {v_cnt:,} {tr('vertices')}, {p_cnt:,} {tr('faces')}")

    # 3. Re-mesh & Selection Settings (Collapsible Subpanel)
    reg = get_save_registry()
    is_valid = reg.is_path_valid(save_uuid)
    world_path = reg.get_world_dir(save_uuid)

    if props is not None:
        box_edit = layout.box()
        row_toggle = box_edit.row(align=True)
        icon_fold = 'DISCLOSURE_TRI_DOWN' if props.show_rebuild_settings else 'DISCLOSURE_TRI_RIGHT'
        row_toggle.prop(
            props,
            "show_rebuild_settings",
            text=tr("Re-mesh & Selection Settings"),
            icon=icon_fold,
            toggle=True,
        )
        if props.is_dirty:
            row_toggle.label(text=tr("Modified"), icon='COLOR')

        if props.show_rebuild_settings:
            col_s = box_edit.column(align=True)

            # Dimension selection
            row_dim = col_s.row(align=True)
            row_dim.prop(props, "dimension", text="")

            # Bounds configuration
            col_bounds = col_s.column(align=True)
            col_bounds.label(text=tr("3D Selection Bounds (Blocks)"), icon='SNAP_INCREMENT')
            col_bounds.prop(props, "min_coord", text=tr("Min Coordinate"))
            col_bounds.prop(props, "max_coord", text=tr("Max Coordinate"))

            # Dynamic size preview for new settings
            cur_dx = abs(props.max_coord[0] - props.min_coord[0]) + 1
            cur_dy = abs(props.max_coord[1] - props.min_coord[1]) + 1
            cur_dz = abs(props.max_coord[2] - props.min_coord[2]) + 1
            cur_vol = cur_dx * cur_dy * cur_dz
            col_bounds.label(
                text=f"{tr('Configured Size')}: {cur_dx} × {cur_dy} × {cur_dz} ({cur_vol:,} {tr('blocks')})",
                icon='INFO',
            )

            # Yefira selection reload helper button
            if is_valid and world_path and (world_path / "yefira_selection.json").is_file():
                row_yef = col_bounds.row(align=True)
                row_yef.operator("mozi.save_load_yefira_selection", text=tr("Load Yefira Selection"), icon='IMPORT')

            # Meshing options
            col_mesh_opts = col_s.column(align=True)
            col_mesh_opts.label(text=tr("Meshing & Shaders"), icon='MATERIAL')
            r1 = col_mesh_opts.row(align=True)
            r1.prop(props, "enable_ao", text=tr("Ambient Occlusion"))
            r1.prop(props, "mesh_fluids", text=tr("Mesh Fluids"))

            r2 = col_mesh_opts.row(align=True)
            r2.prop(props, "weld_vertices", text=tr("Weld Vertices"))
            r2.prop(props, "origin_centered", text=tr("Origin Centered"))

            r3 = col_mesh_opts.row(align=True)
            r3.prop(props, "enable_ctm", text=tr("Connected Textures (CTM)"))
            r3.prop(props, "enable_animated_textures", text=tr("Animated Textures"))

            # Dirty notice and reset button
            if props.is_dirty:
                box_notice = col_s.box()
                box_notice.alert = True
                box_notice.label(text=tr("Settings modified. Refresh to rebuild mesh."), icon='INFO')
                row_reset = box_notice.row(align=True)
                row_reset.operator("mozi.save_reset_settings", text=tr("Reset to Current Model"), icon='LOOP_BACK')

    # 4. Actions & Local Link Card
    box_act = layout.box()

    if is_valid and world_path:
        row_status = box_act.row(align=True)
        row_status.label(text=f"{tr('Local Link')}: {world_path.name}", icon='FILE_FOLDER')

        if last_refreshed_ts:
            try:
                refreshed_str = datetime.datetime.fromtimestamp(float(last_refreshed_ts)).strftime("%Y-%m-%d %H:%M")
            except Exception:
                refreshed_str = str(last_refreshed_ts)
            row_status.label(text=f"{tr('Last Refreshed')}: {refreshed_str}", icon='TIME')

        # Action Buttons
        col_actions = box_act.column(align=True)
        col_actions.scale_y = 1.2
        if props and props.is_dirty:
            col_actions.alert = True
            refresh_text = f"{tr('Apply & Refresh Model')} *"
        else:
            refresh_text = tr("Refresh Model")
        op_refresh = col_actions.operator("mozi.refresh_save_mesh", text=refresh_text, icon='FILE_REFRESH')

        row_relink = box_act.row(align=True)
        op_relink = row_relink.operator("mozi.relink_save_folder", text=tr("Relink Save Folder..."), icon='FOLDER_REDIRECT')
        op_relink.target_uuid = save_uuid
    else:
        # Warning: unlinked or path moved
        box_warn = box_act.column(align=True)
        box_warn.alert = True
        box_warn.label(text=tr("Local Save Unlinked or Path Moved"), icon='ERROR')
        box_warn.label(text=tr("Link your local Minecraft save folder to enable model refresh."))

        col_warn_action = box_warn.column(align=True)
        col_warn_action.scale_y = 1.2
        op_relink = col_warn_action.operator("mozi.relink_save_folder", text=tr("Link Local Save Folder..."), icon='FILE_FOLDER')
        op_relink.target_uuid = save_uuid


class MOZI_PT_save_container_data(bpy.types.Panel):
    """Minecraft Save container panel in Object Data tab (for Empty root containers)."""

    bl_label = "Minecraft World Save"
    bl_idname = "MOZI_PT_save_container_data"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "data"

    @classmethod
    def poll(cls, context):
        active = getattr(context, "active_object", None)
        return is_save_root_container(active)

    def draw(self, context):
        _draw_save_container_ui(self.layout, context)


class MOZI_PT_save_container_object(bpy.types.Panel):
    """Minecraft Save container panel in Object Properties tab (for Mesh child sections)."""

    bl_label = "Minecraft World Save"
    bl_idname = "MOZI_PT_save_container_object"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        active = getattr(context, "active_object", None)
        if not active or getattr(active, "type", "") == 'EMPTY':
            return False
        return is_save_child_object(active)

    def draw(self, context):
        _draw_save_container_ui(self.layout, context)


class MOZI_PT_view3d_save_container(bpy.types.Panel):
    """Minecraft Save container panel in 3D Viewport sidebar (Mozi tab)."""

    bl_label = "Minecraft World Save"
    bl_idname = "MOZI_PT_view3d_save_container"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mozi"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        active = getattr(context, "active_object", None)
        is_save = bool(active and (is_save_root_container(active) or is_save_child_object(active)))
        if is_save:
            # _draw_save_container_ui draws the warning itself.
            _draw_save_container_ui(self.layout, context)
        else:
            draw_vanilla_pack_warning(
                self.layout,
                get_prefs(context),
                "Configure a Vanilla Client JAR in Preferences to enable save import and refresh.",
            )
            box = self.layout.box()
            box.label(text=tr("Minecraft World Save (.mca)"), icon='WORLD')
            col = box.column(align=True)
            col.scale_y = 0.85
            col.label(text=tr("Import raw Minecraft worlds or inspect save containers."))
            col.label(text=tr("No Minecraft Save container selected."))
            row_imp = box.row(align=True)
            row_imp.scale_y = 1.2
            row_imp.operator("mtk.import_minecraft_save", text=tr("Import Minecraft Save (.mca / level.dat)"), icon='IMPORT')


PANEL_CLASSES = (
    MOZI_PT_save_container_data,
    MOZI_PT_save_container_object,
    MOZI_PT_view3d_save_container,
)


def register():
    if not bpy:
        return
    for cls in PANEL_CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def unregister():
    if not bpy:
        return
    for cls in reversed(PANEL_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

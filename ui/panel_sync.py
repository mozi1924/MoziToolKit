"""
Live Sync Sidebar Panel for 3D Viewport in MoziToolKit.
"""

from __future__ import annotations

import bpy
from ..utils.system.dependencies import draw_websockets_warning, has_websockets


class MOZI_UL_sync_palette_list(bpy.types.UIList):
    """UIList for displaying synchronized block palette."""
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.label(text=f"[{index}]", icon='DOT')
            state_text = item.state_str
            if state_text.startswith("minecraft:"):
                state_text = state_text[10:]
            row.label(text=state_text)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=str(index))


class MOZI_UL_sync_delta_list(bpy.types.UIList):
    """UIList for displaying live delta changes."""
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.label(text=item.timestamp, icon='TIME')
            row.label(text=item.pos_str)
            state_text = item.block_state
            if state_text.startswith("minecraft:"):
                state_text = state_text[10:]
            icon_type = 'MESH_CUBE'
            if "broken" in state_text or "removed" in state_text:
                icon_type = 'TRASH'
            elif "Snapshot" in state_text or "Stream" in state_text or "Sync ready" in state_text:
                icon_type = 'FILE_REFRESH'
            row.label(text=state_text, icon=icon_type)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=item.pos_str)


class MOZI_PT_live_sync(bpy.types.Panel):
    """Live Sync control panel in Object Properties tab."""
    bl_label = "Yefira Live Sync"
    bl_idname = "MOZI_PT_live_sync"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        if not context.object:
            return False
        try:
            from ..utils.materials.yefira import is_yefira_object
            return is_yefira_object(context.object)
        except Exception:
            return context.object.name.startswith("Yefira_") or bool(context.object.get("mtk:is_yefira_world"))

    def draw(self, context):
        layout = self.layout
        active_obj = context.object
        if not active_obj:
            layout.label(text="No active object", icon='ERROR')
            return

        try:
            from ..utils.live_sync.mesh_builder import (
                resolve_world_root_object,
                is_yefira_root_object,
                is_yefira_child_section,
                find_root_section_children,
            )
        except (ImportError, ValueError):
            from utils.live_sync.mesh_builder import (
                resolve_world_root_object,
                is_yefira_root_object,
                is_yefira_child_section,
                find_root_section_children,
            )

        root_obj = resolve_world_root_object(active_obj) or active_obj
        props = getattr(root_obj, "mozi_sync", None) or getattr(context.scene, "mozi_sync", None)
        if not props:
            layout.label(text="Properties unavailable", icon='ERROR')
            return

        # Check websockets dependency
        if not has_websockets():
            draw_websockets_warning(layout)
            return

        # Check Blender online access permission
        if hasattr(bpy.app, "online_access") and not bpy.app.online_access:
            box_online = layout.box()
            box_online.alert = True
            box_online.label(text="Network Access Disabled", icon='ERROR')
            box_online.label(text="Enable in Preferences > System > Network to use Live Sync.")
            row_pref = box_online.row()
            op_pref = row_pref.operator("screen.userpref_show", text="Open System Preferences", icon='PREFERENCES')
            op_pref.section = 'SYSTEM'
            return

        # 1. Hierarchy & Container Context
        box_hierarchy = layout.box()
        is_child = is_yefira_child_section(active_obj) and active_obj != root_obj
        if is_child:
            row = box_hierarchy.row(align=True)
            row.label(text=f"Child Section: {active_obj.name}", icon='MESH_DATA')
            sec_pos = active_obj.get("mtk:section_pos")
            if sec_pos is not None and len(sec_pos) == 3:
                row.label(text=f"Chunk: ({sec_pos[0]}, {sec_pos[1]}, {sec_pos[2]})")

            row_parent = box_hierarchy.row(align=True)
            row_parent.label(text=f"Parent Container: {root_obj.name}", icon='EMPTY_AXIS')
            op = row_parent.operator("mozi.sync_select_root", text="Select Parent", icon='RESTRICT_SELECT_OFF')
            op.container_name = root_obj.name
        else:
            row = box_hierarchy.row(align=True)
            row.label(text=f"Container Root: {root_obj.name}", icon='EMPTY_AXIS')
            children_map = find_root_section_children(root_obj)
            row.label(text=f"Sections: {len(children_map)} chunks")

        # 2. Connection Section (bound to root_obj)
        box_conn = layout.box()
        box_conn.label(text=f"Connection ({root_obj.name})", icon='URL')
        row = box_conn.row(align=True)
        row.prop(props, "url", text="")

        row_btn = box_conn.row(align=True)
        row_btn.scale_y = 1.25
        is_busy_connecting = (
            not props.is_connected and (
                props.connection_status.startswith("CONNECTING") or
                props.connection_status.startswith("RECONNECTING")
            )
        )

        if is_busy_connecting:
            op = row_btn.operator("mozi.sync_disconnect", text="Cancel Connection", icon='CANCEL')
            op.target_container = root_obj.name
        elif not props.is_connected:
            op = row_btn.operator("mozi.sync_connect", text="Connect", icon='PLAY')
            op.target_container = root_obj.name
        else:
            op_disc = row_btn.operator("mozi.sync_disconnect", text="Disconnect", icon='CANCEL')
            op_disc.target_container = root_obj.name
            op_ref = row_btn.operator("mozi.sync_refresh", text="Refresh Data", icon='FILE_REFRESH')
            op_ref.target_container = root_obj.name

        # Status badge
        row_status = box_conn.row(align=True)
        if props.is_connected:
            status_icon = 'CHECKMARK'
        elif is_busy_connecting:
            status_icon = 'SORTTIME'
        else:
            status_icon = 'RADIOBUT_OFF'
        row_status.label(text=f"Status: {props.connection_status}", icon=status_icon)

        # 3. World Selection & Metrics
        if props.has_selection:
            box_sel = layout.box()
            box_sel.label(text="Selection Bounds", icon='SHADING_BBOX')
            col = box_sel.column(align=True)
            col.label(text=f"Min: ({props.min_x}, {props.min_y}, {props.min_z})")
            col.label(text=f"Max: ({props.max_x}, {props.max_y}, {props.max_z})")
            col.label(text=f"Size: {props.size_x} x {props.size_y} x {props.size_z} ({props.total_blocks:,} blocks)")

            box_geo = layout.box()
            box_geo.label(text="Live World Mesh", icon='MESH_CUBE')
            col_geo = box_geo.column(align=True)
            col_geo.label(text=f"Vertices: {props.point_count:,}")
            col_geo.label(text=f"Cubes: {props.cubes_count:,} | Props: {props.props_count:,} | Fluids: {props.fluids_count:,}")

            if props.last_update_info:
                col_geo.label(text=props.last_update_info, icon='INFO')

            # Verification status
            v_icon = 'CHECKMARK' if props.sync_verified else 'ERROR'
            col_geo.label(text=props.validation_info, icon=v_icon)

            row_actions = box_geo.row(align=True)
            row_actions.prop(props, "filter_air", text="Filter Air")
            op_reb = row_actions.operator("mozi.sync_rebuild_world", text="Rebuild Mesh", icon='FILE_REFRESH')
            op_reb.target_container = root_obj.name

            # 4. Block Palette
            box_pal = layout.box()
            row_pal = box_pal.row(align=True)
            row_pal.label(text=f"Palette ({props.palette_count})", icon='COLOR')
            box_pal.template_list(
                "MOZI_UL_sync_palette_list",
                "",
                props,
                "palette_list",
                props,
                "palette_active_index",
                rows=3,
            )

            # 5. Delta History
            box_delta = layout.box()
            row_hist = box_delta.row(align=True)
            row_hist.label(text=f"Delta Log ({len(props.delta_history)})", icon='LONGDISPLAY')
            op_clr = row_hist.operator("mozi.sync_clear_history", text="", icon='TRASH')
            op_clr.target_container = root_obj.name
            box_delta.template_list(
                "MOZI_UL_sync_delta_list",
                "",
                props,
                "delta_history",
                props,
                "delta_active_index",
                rows=4,
            )

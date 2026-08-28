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
            row.label(text=item.state_str)
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
            row.label(text=item.block_state)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=item.pos_str)


class MOZI_PT_live_sync(bpy.types.Panel):
    """Live Sync control panel in 3D View sidebar."""
    bl_label = "Live Sync"
    bl_idname = "MOZI_PT_live_sync"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mozi"

    def draw(self, context):
        layout = self.layout
        props = getattr(context.scene, "mozi_sync", None)
        if not props:
            layout.label(text="Properties unavailable", icon='ERROR')
            return

        # Check websockets dependency
        if not has_websockets():
            draw_websockets_warning(layout)
            return

        # 1. Connection Section
        box_conn = layout.box()
        box_conn.label(text="Connection", icon='URL')
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
            row_btn.operator("mozi.sync_disconnect", text="Cancel Connection", icon='CANCEL')
        elif not props.is_connected:
            row_btn.operator("mozi.sync_connect", text="Connect", icon='PLAY')
        else:
            row_btn.operator("mozi.sync_disconnect", text="Disconnect", icon='CANCEL')
            row_btn.operator("mozi.sync_refresh", text="Refresh Data", icon='FILE_REFRESH')

        # Status badge
        row_status = box_conn.row(align=True)
        if props.is_connected:
            status_icon = 'CHECKMARK'
        elif is_busy_connecting:
            status_icon = 'SORTTIME'
        else:
            status_icon = 'RADIOBUT_OFF'
        row_status.label(text=f"Status: {props.connection_status}", icon=status_icon)

        # 2. World Selection & Metrics
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
            row_actions.operator("mozi.sync_rebuild_world", text="Rebuild Mesh", icon='FILE_REFRESH')

            # 3. Block Palette
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

            # 4. Delta History
            box_delta = layout.box()
            row_hist = box_delta.row(align=True)
            row_hist.label(text=f"Delta Log ({len(props.delta_history)})", icon='LONGDISPLAY')
            row_hist.operator("mozi.sync_clear_history", text="", icon='TRASH')
            box_delta.template_list(
                "MOZI_UL_sync_delta_list",
                "",
                props,
                "delta_history",
                props,
                "delta_active_index",
                rows=4,
            )

"""
UI Panel for Yefira Live Sync in 3D Viewport sidebar and properties.
"""

from __future__ import annotations

import bpy


class MOZI_UL_sync_palette_list(bpy.types.UIList):
    """UIList displaying active block palette."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.label(text=item.name, icon='COLOR')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='COLOR')


class MOZI_UL_sync_delta_list(bpy.types.UIList):
    """UIList displaying real-time delta update history."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.label(text=item.time_str, icon='TIME')
            row.label(text=item.block_state)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='TIME')


def _draw_sync_panel_content(layout: bpy.types.UILayout, context: bpy.types.Context):
    """Draws the Live Sync UI content."""
    props = getattr(context.scene, "mozi_sync", None)
    if not props:
        layout.label(text="Live Sync properties not initialized", icon='ERROR')
        return

    # 1. Connection Card
    box_conn = layout.box()
    box_conn.label(text="Connection", icon='URL')

    row_url = box_conn.row(align=True)
    row_url.prop(props, "url", text="")

    row_btn = box_conn.row(align=True)
    row_btn.scale_y = 1.25

    if not props.is_connected:
        op = row_btn.operator("mozi.sync_connect", text="Connect", icon='PLAY')
    else:
        row_btn.operator("mozi.sync_disconnect", text="Disconnect", icon='CANCEL')
        row_btn.operator("mozi.sync_refresh", text="Refresh", icon='FILE_REFRESH')

    # Status indicator
    row_status = box_conn.row(align=True)
    if props.is_connected:
        icon = 'CHECKMARK'
    elif props.connection_status.startswith("CONNECTING"):
        icon = 'SORTTIME'
    else:
        icon = 'RADIOBUT_OFF'
    row_status.label(text=f"Status: {props.connection_status}", icon=icon)

    if props.validation_info:
        row_val = box_conn.row(align=True)
        row_val.scale_y = 0.85
        row_val.label(text=props.validation_info, icon='INFO')

    # 2. World Bounds & Unified Mesh Metrics
    if props.has_selection:
        box_geo = layout.box()
        box_geo.label(text="Unified World Mesh", icon='MESH_CUBE')

        col_b = box_geo.column(align=True)
        col_b.label(text=f"Origin: ({props.min_x}, {props.min_y}, {props.min_z})")
        col_b.label(text=f"Size: {props.size_x} x {props.size_y} x {props.size_z} ({props.total_blocks:,} blocks)")

        col_m = box_geo.column(align=True)
        col_m.label(text=f"Vertices: {props.point_count:,} | Faces: {props.faces_count:,}")

        if props.last_update_info:
            col_m.label(text=props.last_update_info, icon='INFO')

        row_reb = box_geo.row(align=True)
        row_reb.operator("mozi.sync_rebuild_world", text="Rebuild Mesh", icon='FILE_REFRESH')

    # 3. Delta Update Log
    if len(props.delta_history) > 0:
        box_delta = layout.box()
        row_h = box_delta.row(align=True)
        row_h.label(text=f"Live Delta History ({len(props.delta_history)})", icon='LONGDISPLAY')
        row_h.operator("mozi.sync_clear_history", text="", icon='TRASH')

        box_delta.template_list(
            "MOZI_UL_sync_delta_list",
            "",
            props,
            "delta_history",
            props,
            "delta_active_index",
            rows=3,
        )

    # 4. Block Palette
    if len(props.palette_list) > 0:
        box_pal = layout.box()
        box_pal.label(text=f"Palette ({len(props.palette_list)})", icon='COLOR')
        box_pal.template_list(
            "MOZI_UL_sync_palette_list",
            "",
            props,
            "palette_list",
            props,
            "palette_active_index",
            rows=3,
        )


class MOZI_PT_live_sync_view3d(bpy.types.Panel):
    """Live Sync Panel in 3D Viewport sidebar."""
    bl_label = "Live Sync"
    bl_idname = "MOZI_PT_live_sync_view3d"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mozi"

    def draw(self, context):
        _draw_sync_panel_content(self.layout, context)


class MOZI_PT_live_sync_properties(bpy.types.Panel):
    """Live Sync Panel in Scene Properties tab."""
    bl_label = "Yefira Live Sync"
    bl_idname = "MOZI_PT_live_sync_properties"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    def draw(self, context):
        _draw_sync_panel_content(self.layout, context)


PANEL_CLASSES = (
    MOZI_UL_sync_palette_list,
    MOZI_UL_sync_delta_list,
    MOZI_PT_live_sync_view3d,
    MOZI_PT_live_sync_properties,
)


def register():
    for cls in PANEL_CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(PANEL_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

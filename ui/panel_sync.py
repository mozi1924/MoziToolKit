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


import re

try:
    from ..i18n import tr
except (ImportError, ValueError):
    from i18n import tr


def _format_sync_status(status_str: str) -> str:
    if not status_str:
        return ""
    trans = tr(status_str)
    return trans if trans != status_str else status_str


def _format_sync_info(info_str: str) -> str:
    if not info_str:
        return ""
    direct = tr(info_str)
    if direct != info_str:
        return direct
    m = re.match(r"World Mesh updated: ([\d,]+) vertices, ([\d,]+) faces", info_str)
    if m:
        return f"{tr('World Mesh updated')}: {m.group(1)} {tr('vertices')}, {m.group(2)} {tr('faces')}"
    m = re.match(r"Rebuilt World Mesh: ([\d,]+) vertices, ([\d,]+) faces", info_str)
    if m:
        return f"{tr('Rebuilt World Mesh')}: {m.group(1)} {tr('vertices')}, {m.group(2)} {tr('faces')}"
    m = re.match(r"Detected (\d+) out-of-sync sections?", info_str)
    if m:
        return f"{tr('Detected')} {m.group(1)} {tr('out-of-sync sections')}"
    m = re.match(r"Connecting to (.+)\.\.\.", info_str)
    if m:
        return f"{tr('Connecting to')} {m.group(1)}..."
    m = re.match(r"Sync Handshake: (\d+) chunks \(([\d,]+) blocks\)", info_str)
    if m:
        return f"{tr('Sync Handshake')}: {m.group(1)} {tr('chunks')} ({m.group(2)} {tr('blocks')})"
    m = re.match(r"Delta Applied: (\d+) block modification\(s\)", info_str)
    if m:
        return f"{tr('Delta Applied')}: {m.group(1)} {tr('block modifications')}"
    m = re.match(r"Stream Complete \((\d+) chunks received\)", info_str)
    if m:
        return f"{tr('Stream Complete')} ({m.group(1)} {tr('chunks received')})"
    return info_str


def _format_stream_message(msg: str) -> str:
    if not msg:
        return ""
    direct = tr(msg)
    if direct != msg:
        return direct
    m = re.match(r"Receiving chunk (\(\d+/\d+\) .*)", msg)
    if m:
        return f"{tr('Receiving chunk')} {m.group(1)}"
    return msg


def _draw_sync_panel_content(layout: bpy.types.UILayout, context: bpy.types.Context):
    """Draws the Live Sync UI content."""
    props = getattr(context.scene, "mozi_sync", None)
    if not props:
        layout.label(text=tr("Live Sync properties not initialized"), icon='ERROR')
        return

    # 1. Connection Card
    box_conn = layout.box()
    box_conn.label(text=tr("Connection"), icon='URL')

    row_url = box_conn.row(align=True)
    row_url.prop(props, "url", text="")

    row_btn = box_conn.row(align=True)
    row_btn.scale_y = 1.25

    if not props.is_connected:
        op = row_btn.operator("mozi.sync_connect", text=tr("Connect"), icon='PLAY')
    else:
        row_btn.operator("mozi.sync_disconnect", text=tr("Disconnect"), icon='CANCEL')
        row_btn.operator("mozi.sync_refresh", text=tr("Refresh"), icon='FILE_REFRESH')

    # Status indicator
    row_status = box_conn.row(align=True)
    if props.is_connected:
        icon = 'CHECKMARK'
    elif props.connection_status.startswith("CONNECTING"):
        icon = 'SORTTIME'
    else:
        icon = 'RADIOBUT_OFF'
    status_display = _format_sync_status(props.connection_status)
    row_status.label(text=f"{tr('Status')}: {status_display}", icon=icon)

    if props.validation_info:
        row_val = box_conn.row(align=True)
        row_val.scale_y = 0.85
        row_val.label(text=_format_sync_info(props.validation_info), icon='INFO')

    # 2. Live Synchronization Progress Card
    if props.is_streaming:
        box_prog = layout.box()
        box_prog.label(text=tr("Synchronization in Progress"), icon='SORTTIME')
        if props.stream_message:
            box_prog.label(text=_format_stream_message(props.stream_message), icon='INFO')
        if props.stream_progress_total > 0:
            pct = min(100.0, max(0.0, props.stream_progress_current / props.stream_progress_total * 100.0))
            row_p = box_prog.row(align=True)
            row_p.scale_y = 0.85
            row_p.label(text=f"{tr('Progress')}: {pct:.1f}% ({props.stream_progress_current}/{props.stream_progress_total})")

    # 3. World Bounds & Unified Mesh Metrics
    if props.has_selection:
        box_geo = layout.box()
        box_geo.label(text=tr("Unified World Mesh"), icon='MESH_CUBE')

        col_b = box_geo.column(align=True)
        col_b.label(text=f"{tr('Origin')}: ({props.min_x}, {props.min_y}, {props.min_z})")
        col_b.label(text=f"{tr('Size')}: {props.size_x} × {props.size_y} × {props.size_z} ({props.total_blocks:,} {tr('blocks')})")

        col_m = box_geo.column(align=True)
        col_m.label(text=f"{tr('Vertices')}: {props.point_count:,} | {tr('Faces')}: {props.faces_count:,}")

        if props.last_update_info:
            col_m.label(text=_format_sync_info(props.last_update_info), icon='INFO')

        row_reb = box_geo.row(align=True)
        row_reb.operator("mozi.sync_rebuild_world", text=tr("Rebuild Mesh"), icon='FILE_REFRESH')

    # 4. Delta Update Log
    if len(props.delta_history) > 0:
        box_delta = layout.box()
        row_h = box_delta.row(align=True)
        row_h.label(text=f"{tr('Live Delta History')} ({len(props.delta_history)})", icon='LONGDISPLAY')
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

    # 5. Block Palette
    if len(props.palette_list) > 0:
        box_pal = layout.box()
        box_pal.label(text=f"{tr('Palette')} ({len(props.palette_list)})", icon='COLOR')
        box_pal.template_list(
            "MOZI_UL_sync_palette_list",
            "",
            props,
            "palette_list",
            props,
            "palette_active_index",
            rows=3,
        )


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

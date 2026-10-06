"""
UI Panels for Yefira Live Sync in Object Data (Empty root container) and Object Properties (Child section mesh).
"""

from __future__ import annotations

import re
import bpy

try:
    from ..i18n import tr
except (ImportError, ValueError):
    from i18n import tr

try:
    from ..operators.sync.hierarchy import (
        is_yefira_root_object,
        is_yefira_world_object,
        resolve_world_root_object,
        find_world_mesh_child,
        find_voxel_cloud_child,
    )
    from ..operators.sync.properties import get_active_sync_container
except (ImportError, ValueError):
    from operators.sync.hierarchy import (
        is_yefira_root_object,
        is_yefira_world_object,
        resolve_world_root_object,
        find_world_mesh_child,
        find_voxel_cloud_child,
    )
    from operators.sync.properties import get_active_sync_container


class MOZI_UL_sync_palette_list(bpy.types.UIList):
    """UIList displaying active block palette."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            name = item.name
            if name.startswith("minecraft:"):
                name = name[10:]
            row.label(text=name, icon='COLOR')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='COLOR')


class MOZI_UL_sync_delta_list(bpy.types.UIList):
    """UIList displaying real-time delta update history."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.label(text=item.time_str, icon='TIME')
            state_text = item.block_state
            if state_text.startswith("minecraft:"):
                state_text = state_text[10:]
            row.label(text=state_text)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='TIME')


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


def _draw_live_sync_content(layout: bpy.types.UILayout, context: bpy.types.Context):
    """Internal shared drawing implementation for Live Sync panels."""
    active_obj = getattr(context, "object", None)
    if not active_obj:
        layout.label(text=tr("No active object"), icon='ERROR')
        return

    root_obj = resolve_world_root_object(active_obj) or active_obj
    props = getattr(root_obj, "mozi_sync", None) or getattr(context.scene, "mozi_sync", None)
    if not props:
        layout.label(text=tr("Live Sync properties not initialized"), icon='ERROR')
        return

    # Check network permission if applicable
    if hasattr(bpy.app, "online_access") and not bpy.app.online_access:
        box_online = layout.box()
        box_online.alert = True
        box_online.label(text=tr("Network Access Disabled"), icon='ERROR')
        box_online.label(text=tr("Enable in Preferences > System > Network to use Live Sync."))
        row_pref = box_online.row()
        op_pref = row_pref.operator("screen.userpref_show", text=tr("Open Preferences"), icon='PREFERENCES')
        op_pref.section = 'SYSTEM'
        return

    # 1. Hierarchy & Container Context Card
    box_hierarchy = layout.box()
    is_child = (active_obj != root_obj)
    if is_child:
        row = box_hierarchy.row(align=True)
        child_icon = 'MESH_DATA' if active_obj.type == 'MESH' else 'POINTCLOUD_DATA'
        row.label(text=f"{tr('Child')}: {active_obj.name}", icon=child_icon)

        row_parent = box_hierarchy.row(align=True)
        row_parent.label(text=f"{tr('Parent Container')}: {root_obj.name}", icon='EMPTY_AXIS')
        op = row_parent.operator("mozi.sync_select_root", text=tr("Select Parent"), icon='RESTRICT_SELECT_OFF')
        op.container_name = root_obj.name
    else:
        row = box_hierarchy.row(align=True)
        row.label(text=f"{tr('Container Root')}: {root_obj.name}", icon='EMPTY_AXIS')
        child_mesh = find_world_mesh_child(root_obj)
        child_cloud = find_voxel_cloud_child(root_obj)
        mesh_label = child_mesh.name if child_mesh else tr("None")
        cloud_label = child_cloud.name if child_cloud else tr("None")
        row_info = box_hierarchy.row(align=True)
        row_info.scale_y = 0.85
        row_info.label(text=f"Mesh: {mesh_label} | Cloud: {cloud_label}")

    # Active container notice if another container is currently syncing
    active_cont = get_active_sync_container(context.scene)
    if active_cont and active_cont != root_obj and active_cont.name in bpy.data.objects:
        active_props = getattr(active_cont, "mozi_sync", None)
        if active_props and active_props.is_connected:
            box_warn = layout.box()
            row_w = box_warn.row(align=True)
            row_w.label(text=f"{tr('Active sync connected to')}: {active_cont.name}", icon='INFO')
            op_sw = row_w.operator("mozi.sync_connect", text=tr("Switch to This"), icon='PLAY')
            op_sw.target_container = root_obj.name

    # 2. Connection Card (bound to root_obj)
    box_conn = layout.box()
    box_conn.label(text=f"{tr('Connection')} ({root_obj.name})", icon='URL')

    row_url = box_conn.row(align=True)
    row_url.prop(props, "url", text="")

    row_btn = box_conn.row(align=True)
    row_btn.scale_y = 1.25

    is_busy_connecting = (
        not props.is_connected and (
            props.connection_status.startswith("CONNECTING") or
            props.connection_status.startswith("RECONNECTING")
        )
    )

    if is_busy_connecting:
        op = row_btn.operator("mozi.sync_disconnect", text=tr("Cancel Connection"), icon='CANCEL')
        op.target_container = root_obj.name
    elif not props.is_connected:
        op = row_btn.operator("mozi.sync_connect", text=tr("Connect"), icon='PLAY')
        op.target_container = root_obj.name
    else:
        op_disc = row_btn.operator("mozi.sync_disconnect", text=tr("Disconnect"), icon='CANCEL')
        op_disc.target_container = root_obj.name
        op_ref = row_btn.operator("mozi.sync_refresh", text=tr("Refresh"), icon='FILE_REFRESH')
        op_ref.target_container = root_obj.name

    # Status indicator
    row_status = box_conn.row(align=True)
    if props.is_connected:
        icon = 'CHECKMARK'
    elif is_busy_connecting:
        icon = 'SORTTIME'
    else:
        icon = 'RADIOBUT_OFF'
    status_display = _format_sync_status(props.connection_status)
    row_status.label(text=f"{tr('Status')}: {status_display}", icon=icon)

    if props.validation_info:
        row_val = box_conn.row(align=True)
        row_val.scale_y = 0.85
        val_icon = 'CHECKMARK' if props.sync_verified else ('ERROR' if ("Detected" in props.validation_info or "Out of sync" in props.validation_info) else 'INFO')
        row_val.label(text=_format_sync_info(props.validation_info), icon=val_icon)

    # 3. Live Synchronization Progress Card
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

    # 4. World Bounds & Unified Mesh Metrics
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
        op_reb = row_reb.operator("mozi.sync_rebuild_world", text=tr("Rebuild Mesh"), icon='FILE_REFRESH')
        op_reb.target_container = root_obj.name

    # 5. Delta Update Log
    if len(props.delta_history) > 0:
        box_delta = layout.box()
        row_h = box_delta.row(align=True)
        row_h.label(text=f"{tr('Live Delta History')} ({len(props.delta_history)})", icon='LONGDISPLAY')
        op_clr = row_h.operator("mozi.sync_clear_history", text="", icon='TRASH')
        op_clr.target_container = root_obj.name

        box_delta.template_list(
            "MOZI_UL_sync_delta_list",
            "",
            props,
            "delta_history",
            props,
            "delta_active_index",
            rows=3,
        )

    # 6. Block Palette
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

    # 7. Add New Container Action
    row_add = layout.row(align=True)
    row_add.scale_y = 1.1
    row_add.operator("mozi.add_yefira_world", text=tr("New Live Sync Container"), icon='ADD')


class MOZI_PT_live_sync_data(bpy.types.Panel):
    """Live Sync control panel in Object Data Properties tab (for Yefira Empty container)."""
    bl_label = "Yefira Live Sync"
    bl_idname = "MOZI_PT_live_sync_data"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "data"

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        if not obj or obj.type != 'EMPTY':
            return False
        return is_yefira_root_object(obj)

    def draw(self, context):
        _draw_live_sync_content(self.layout, context)


class MOZI_PT_live_sync(bpy.types.Panel):
    """Live Sync control panel in Object Properties tab (for Mesh child sections)."""
    bl_label = "Yefira Live Sync"
    bl_idname = "MOZI_PT_live_sync"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        if not obj or obj.type == 'EMPTY':
            return False
        return is_yefira_world_object(obj)

    def draw(self, context):
        _draw_live_sync_content(self.layout, context)


PANEL_CLASSES = (
    MOZI_UL_sync_palette_list,
    MOZI_UL_sync_delta_list,
    MOZI_PT_live_sync_data,
    MOZI_PT_live_sync,
)

# Backward compatibility alias
MOZI_PT_live_sync_properties = MOZI_PT_live_sync_data


def register():
    for cls in PANEL_CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(PANEL_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

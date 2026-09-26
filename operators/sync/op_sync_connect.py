"""
Operators for connecting, disconnecting, and synchronizing with Live Sync WebSocket server.
"""

from __future__ import annotations

import logging
import time
import bpy

try:
    from ...bridge.sync import (
        get_sync_bridge_session,
        is_sync_available,
        load_model_database_from_cache,
    )
except (ImportError, ValueError):
    from bridge.sync import (
        get_sync_bridge_session,
        is_sync_available,
        load_model_database_from_cache,
    )
from .hierarchy import get_or_create_world_mesh_object, update_world_mesh

logger = logging.getLogger("MoziToolKit.Sync.Connect")

_timer_registered = False


def _get_active_props(context: bpy.types.Context) -> Optional[bpy.types.PropertyGroup]:
    """Resolves active scene-level sync properties."""
    if hasattr(context, "scene") and hasattr(context.scene, "mozi_sync"):
        return context.scene.mozi_sync
    return None


def _sync_timer_tick() -> Optional[float]:
    """
    Main-thread non-blocking timer polling events from native libmtk engine
    and updating the Blender viewport world mesh.
    """
    global _timer_registered
    session = get_sync_bridge_session()
    if not session.is_active:
        _timer_registered = False
        return None

    props = _get_active_props(bpy.context)
    events = session.poll_events()

    for ev in events:
        ev_type = ev.get("type")
        if not ev_type:
            continue

        if ev_type == "STATUS_CHANGE":
            status = ev.get("status", "DISCONNECTED")
            if props:
                props.connection_status = status
                props.is_connected = (status == "CONNECTED")
                if status == "CONNECTED":
                    props.validation_info = "Connected to Live Sync"

        elif ev_type == "SELECTION_UPDATED":
            if props:
                props.has_selection = True
                props.min_x = ev.get("min_x", 0)
                props.min_y = ev.get("min_y", 0)
                props.min_z = ev.get("min_z", 0)
                props.size_x = ev.get("size_x", 0)
                props.size_y = ev.get("size_y", 0)
                props.size_z = ev.get("size_z", 0)
                props.total_blocks = props.size_x * props.size_y * props.size_z

        elif ev_type == "HANDSHAKE":
            if props:
                tot = ev.get("total_sections", 0)
                vol = ev.get("total_volume", 0)
                props.validation_info = f"Sync Handshake: {tot} chunks ({vol:,} blocks)"

        elif ev_type == "WORLD_MESH_READY":
            mesh_data = ev.get("mesh")
            if mesh_data:
                try:
                    world_obj = get_or_create_world_mesh_object(bpy.context)
                    v_count, f_count = update_world_mesh(world_obj, mesh_data)
                    if props:
                        props.point_count = v_count
                        props.faces_count = f_count
                        props.last_update_info = f"World Mesh updated: {v_count:,} vertices, {f_count:,} faces"
                except Exception as e:
                    logger.error(f"Failed to inject WorldMesh into Blender: {e}")

        elif ev_type == "DELTA_APPLIED":
            if props:
                cnt = ev.get("change_count", 0)
                props.last_update_info = f"Delta Applied: {cnt} block modification(s)"

                # Add to history
                item = props.delta_history.add()
                item.pos_str = f"Delta #{len(props.delta_history)}"
                item.block_state = f"{cnt} blocks modified"
                item.time_str = time.strftime("%H:%M:%S")

                # Keep history bounded (max 50)
                if len(props.delta_history) > 50:
                    props.delta_history.remove(0)

        elif ev_type == "STREAM_PROGRESS":
            if props:
                props.stream_progress_current = ev.get("current", 0)
                props.stream_progress_total = ev.get("total", 0)
                props.stream_message = ev.get("message", "")

        elif ev_type == "STREAM_FINISHED":
            if props:
                built = ev.get("built_sections", 0)
                props.last_update_info = f"Stream Complete ({built} chunks received)"

        elif ev_type == "VERIFIED":
            if props:
                props.sync_verified = ev.get("is_verified", False)
                props.validation_info = ev.get("message", "")

        elif ev_type == "WARNING":
            if props:
                props.validation_info = f"Warning: {ev.get('message', '')}"

        elif ev_type == "ERROR":
            if props:
                props.validation_info = f"Error: {ev.get('message', '')}"

    return 0.016  # ~60 fps poll interval


class MOZI_OT_sync_connect(bpy.types.Operator):
    """Connect to Minecraft Live Sync streaming server."""
    bl_idname = "mozi.sync_connect"
    bl_label = "Connect"
    bl_description = "Connect to Minecraft Live Sync WebSocket Server"

    def execute(self, context):
        global _timer_registered
        if not is_sync_available():
            self.report({'ERROR'}, "Native libmtk core is missing or not installed!")
            return {'CANCELLED'}

        props = _get_active_props(context)
        url = props.url if props else "ws://127.0.0.1:8765"

        # Attempt to load prebaked model database
        model_db = load_model_database_from_cache()

        session = get_sync_bridge_session()
        success = session.start(
            url=url,
            auto_reconnect=True,
            max_reconnect_attempts=5,
            model_db=model_db,
            unified_mesh=True,
        )

        if not success:
            self.report({'ERROR'}, f"Failed to initiate connection to {url}")
            return {'CANCELLED'}

        if props:
            props.connection_status = "CONNECTING..."
            props.validation_info = f"Connecting to {url}..."

        # Register non-blocking event timer
        if not _timer_registered:
            bpy.app.timers.register(_sync_timer_tick, first_interval=0.016)
            _timer_registered = True

        self.report({'INFO'}, f"Connecting to Live Sync at {url}")
        return {'FINISHED'}


class MOZI_OT_sync_disconnect(bpy.types.Operator):
    """Disconnect from Minecraft Live Sync streaming server."""
    bl_idname = "mozi.sync_disconnect"
    bl_label = "Disconnect"
    bl_description = "Disconnect Live Sync session and stop background listener"

    def execute(self, context):
        global _timer_registered
        session = get_sync_bridge_session()
        session.stop()

        props = _get_active_props(context)
        if props:
            props.is_connected = False
            props.connection_status = "DISCONNECTED"
            props.validation_info = "Disconnected"

        _timer_registered = False
        self.report({'INFO'}, "Live Sync Disconnected.")
        return {'FINISHED'}


class MOZI_OT_sync_refresh(bpy.types.Operator):
    """Request server to resend active selection snapshot."""
    bl_idname = "mozi.sync_refresh"
    bl_label = "Refresh Data"
    bl_description = "Request a full snapshot resync from the server"

    def execute(self, context):
        session = get_sync_bridge_session()
        if not session.is_active:
            self.report({'WARNING'}, "Live Sync is not connected.")
            return {'CANCELLED'}

        session.send_full_sync_request()
        self.report({'INFO'}, "Full snapshot requested from server.")
        return {'FINISHED'}


OPERATOR_CLASSES = (
    MOZI_OT_sync_connect,
    MOZI_OT_sync_disconnect,
    MOZI_OT_sync_refresh,
)

"""
Operators for connecting, disconnecting, and refreshing Minecraft Live Sync.
Supports multiple simultaneous container sessions and robust error handling.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple
import bpy

from ...utils.live_sync.client import SyncClientThread
from ...utils.live_sync.constants import (
    DEFAULT_WORLD_OBJECT_NAME,
)
from ...utils.mc_baker import (
    refresh_shared_baker_sources,
    clear_shared_baker_cache,
)
from ...utils.live_sync.mesh_builder import (
    sync_world_mesh,
    build_world_mesh,
    apply_block_delta_to_world,
    clear_mesh_builder_caches,
    preload_sync_world_data,
    WorldMeshBuildResult,
    resolve_world_root_object,
    get_or_create_world_root,
    find_root_section_children,
    is_yefira_root_object,
    is_yefira_child_section,
    is_yefira_object,
)
from ...utils.live_sync.storage import VoxelStorage, voxel_storage, EMPTY_SECTION_CRC
from ...utils.live_sync.session_manager import (
    SyncSession,
    SyncSessionManager,
    get_active_session_manager,
    get_active_sync_props,
    get_target_world_object,
    get_current_world_object,
    get_cached_atlas_params,
    clear_sync_caches,
    trigger_mesh_sync,
    schedule_mesh_sync,
    persist_sync_state_to_scene,
    restore_sync_state_from_scene,
    sync_palette_to_props,
    append_delta_history,
    start_main_thread_pump,
    stop_main_thread_pump,
    _pump_main_thread_events,
    cleanup_sync_state as _engine_cleanup_sync_state,
    _finalize_stream_sync,
    _session_manager,
    MAX_DELTA_HISTORY,
    _delta_queue,
    _stream_section_queue,
    _accumulated_stream_palettes,
)
from ...utils.materials.pipeline.session import cleanup_unused_mtk_datablocks
from ...utils.materials.yefira import (
    extract_atlas_parameters,
    find_bound_atlas_material,
)
from ...utils.system.dependencies import has_websockets
from ...pipeline.progress import ProgressBar
from .op_sync_stream_modal import start_stream_modal_lock

logger = logging.getLogger("MoziToolKit.LiveSync")

# Legacy module-level variables for test and backwards compatibility
_client_thread: Optional[SyncClientThread] = None
_is_streaming: bool = False
_last_seq_id: int = 0
_stream_total_sections: int = 0
_stream_received_sections: int = 0
_is_initial_handshake: bool = False
_rebuild_timer_registered: bool = False
_pending_full_rebuild: bool = False
_cached_atlas_params: Optional[dict] = None
_cached_mat_signature: Optional[tuple] = None
_is_repairing_partial: bool = False


def cleanup_sync_state() -> None:
    """Clean up all live sync module globals, background threads, timers, and storage."""
    global _client_thread, _is_streaming, _last_seq_id, _stream_received_sections, _stream_total_sections
    global _is_initial_handshake, _is_repairing_partial, _rebuild_timer_registered, _pending_full_rebuild
    global _cached_atlas_params, _cached_mat_signature
    if _client_thread:
        try:
            _client_thread.stop()
        except Exception:
            pass
    _client_thread = None
    _is_streaming = False
    _last_seq_id = 0
    _stream_received_sections = 0
    _stream_total_sections = 0
    _is_initial_handshake = False
    _is_repairing_partial = False
    _rebuild_timer_registered = False
    _pending_full_rebuild = False
    _cached_atlas_params = None
    _cached_mat_signature = None
    _engine_cleanup_sync_state()



class MOZI_OT_sync_connect(bpy.types.Operator):
    bl_idname = "mozi.sync_connect"
    bl_label = "Connect"
    bl_description = "Connect to Minecraft Live Sync WebSocket Server"

    target_container: bpy.props.StringProperty(name="Target Container", default="")

    def execute(self, context):
        # Check Blender online access permission (official manual requirement for network extensions)
        if hasattr(bpy.app, "online_access") and not bpy.app.online_access:
            self.report(
                {'ERROR'},
                "Internet / Network access is disabled in Blender preferences. "
                "Please go to Edit > Preferences > System > Network and enable 'Allow Online Access' to use Live Sync."
            )
            return {'CANCELLED'}

        if not has_websockets():
            self.report({'WARNING'}, "Missing 'websockets' library! Check bundled extension wheels.")
            return {'CANCELLED'}

        # 1. Resolve target container object
        target_obj = None
        if self.target_container:
            target_obj = bpy.data.objects.get(self.target_container)
        if not target_obj:
            target_obj = get_target_world_object(context)
        if not target_obj:
            target_obj = get_or_create_world_root(context)

        props = get_active_sync_props(context, target_obj=target_obj)
        if not props:
            self.report({'ERROR'}, "Container properties not initialized.")
            return {'CANCELLED'}

        # 2. Check Blender system network connection limit
        sys_pref = getattr(context.preferences, "system", None)
        conn_limit = getattr(sys_pref, "network_connection_limit", 0) if sys_pref else 0
        if conn_limit > 0:
            active_sessions = [
                s for s in _session_manager.get_all_sessions()
                if s.target_object_name != target_obj.name and s.client_thread and s.client_thread.is_alive()
            ]
            if len(active_sessions) >= conn_limit:
                self.report(
                    {'ERROR'},
                    f"Live Sync connection limit reached ({len(active_sessions)}/{conn_limit}). "
                    f"Please increase the limit in Edit > Preferences > System > Network, or disconnect unused sessions."
                )
                return {'CANCELLED'}

        url = props.url if props.url else "ws://localhost:8765"
        session_mgr = get_active_session_manager()
        session = session_mgr.get_or_create_session(target_obj.name, url=url)

        if session.client_thread and session.client_thread.is_alive():
            self.report({'INFO'}, f"Already connected or connecting: {target_obj.name}")
            return {'FINISHED'}

        # Start live sync connection via SyncSession lifecycle manager
        session.start_connection(context=context)

        self.report({'INFO'}, f"Connecting {target_obj.name} to {props.url}...")
        return {'FINISHED'}


class MOZI_OT_sync_disconnect(bpy.types.Operator):
    bl_idname = "mozi.sync_disconnect"
    bl_label = "Disconnect"
    bl_description = "Disconnect from Minecraft Live Sync server"

    target_container: bpy.props.StringProperty(name="Target Container", default="")

    def execute(self, context):
        target_obj = None
        if self.target_container:
            target_obj = bpy.data.objects.get(self.target_container)
        if not target_obj:
            target_obj = get_target_world_object(context)

        session_mgr = get_active_session_manager()
        if target_obj and target_obj.name in session_mgr._sessions:
            session = session_mgr.get_session(target_obj.name)
            if session:
                session.persist_sync_state_to_scene(target_obj)
            session_mgr.remove_session(target_obj.name)
            props = get_active_sync_props(context, target_obj=target_obj)
            if props:
                props.is_connected = False
                props.connection_status = "DISCONNECTED"
        else:
            # Disconnect all active sessions
            for s in session_mgr.get_all_sessions():
                s_obj = bpy.data.objects.get(s.target_object_name)
                if s_obj:
                    s.persist_sync_state_to_scene(s_obj)
            session_mgr.clear_all()
            props = get_active_sync_props(context)
            if props:
                props.is_connected = False
                props.connection_status = "DISCONNECTED"

        if not any(s.client_thread and s.client_thread.is_connected for s in session_mgr.get_all_sessions()):
            stop_main_thread_pump()
            ProgressBar.end(context=context)

        self.report({'INFO'}, "Disconnected from Live Sync server.")
        return {'FINISHED'}


class MOZI_OT_sync_refresh(bpy.types.Operator):
    bl_idname = "mozi.sync_refresh"
    bl_label = "Refresh"
    bl_description = "Request fresh data snapshot and re-verify sync state with server"

    target_container: bpy.props.StringProperty(name="Target Container", default="")

    def execute(self, context):
        target_obj = None
        if self.target_container:
            target_obj = bpy.data.objects.get(self.target_container)
        if not target_obj:
            target_obj = get_target_world_object(context)
        if not target_obj:
            target_obj = get_or_create_world_root(context)

        session_mgr = get_active_session_manager()
        session = session_mgr.get_session(target_obj.name)
        if session and session.client_thread and session.client_thread.is_connected:
            session.skip_next_full_snapshot = False
            session.force_next_full_rebuild = True
            session.pending_full_sync_request = True
            session.is_repairing_partial = False
            session.is_streaming = True
            session.clear_caches()
            ProgressBar.begin(title=f"Live Sync Refresh ({target_obj.name})", total=100.0, message="Requesting full snapshot...", context=context)
            session.client_thread.send_full_sync_request()
            self.report({'INFO'}, f"Refreshing live sync data for {target_obj.name}...")
        else:
            bpy.ops.mozi.sync_connect(target_container=target_obj.name)
        return {'FINISHED'}


def unregister():
    """Unregister cleanup hook called when addon is disabled/uninstalled."""
    cleanup_sync_state()

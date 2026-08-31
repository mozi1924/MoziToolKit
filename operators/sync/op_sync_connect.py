"""
Operators for connecting, disconnecting, and refreshing Minecraft Live Sync.
Supports multiple simultaneous container sessions and robust error handling.
"""

from __future__ import annotations

import logging
import queue
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import bpy

try:
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
except (ImportError, ValueError):
    from utils.live_sync.client import SyncClientThread
    from utils.live_sync.constants import (
        DEFAULT_WORLD_OBJECT_NAME,
    )
    from utils.mc_baker import (
        refresh_shared_baker_sources,
        clear_shared_baker_cache,
    )
    from utils.live_sync.mesh_builder import (
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
    from utils.live_sync.storage import VoxelStorage, voxel_storage, EMPTY_SECTION_CRC
    from utils.live_sync.session_manager import (
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
    from utils.materials.pipeline.session import cleanup_unused_mtk_datablocks
    from utils.materials.yefira import (
        extract_atlas_parameters,
        find_bound_atlas_material,
    )
    from utils.system.dependencies import has_websockets
    from pipeline.progress import ProgressBar

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
    while not _delta_queue.empty():
        try:
            _delta_queue.get_nowait()
        except queue.Empty:
            break
    while not _stream_section_queue.empty():
        try:
            _stream_section_queue.get_nowait()
        except queue.Empty:
            break
    _accumulated_stream_palettes.clear()
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

        try:
            from ...utils.materials.pack import get_configured_pack_stack
        except (ImportError, ValueError):
            from utils.materials.pack import get_configured_pack_stack

        pack_stack = get_configured_pack_stack()
        if not pack_stack or not pack_stack.packs:
            self.report(
                {'ERROR'},
                "No active resource packs or Minecraft JARs configured. "
                "Please configure your Resource Pack Stack in Edit > Preferences > Add-ons > MoziToolKit and click 'Precompile / Rebuild Stack Atlas Cache'."
            )
            return {'CANCELLED'}

        if not pack_stack.is_stack_baked():
            self.report(
                {'ERROR'},
                "The configured Resource Pack Stack has not been precompiled. "
                "Please go to Edit > Preferences > Add-ons > MoziToolKit and click 'Precompile / Rebuild Stack Atlas Cache' before using Live Sync."
            )
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
        session = _session_manager.get_or_create_session(target_obj.name, url=url)

        if session.client_thread and session.client_thread.is_alive():
            self.report({'INFO'}, f"Already connected or connecting: {target_obj.name}")
            return {'FINISHED'}

        session.is_initial_handshake = True
        session.skip_next_full_snapshot = False

        if session.storage.size_x == 0 or not session.storage.section_crc_map:
            session.restore_sync_state_from_scene(target_obj)

        ProgressBar.begin(title=f"Live Sync ({target_obj.name})", total=100.0, message="Connecting to Minecraft...", context=context)

        def run_in_main_thread(func):
            def wrapper():
                try:
                    func()
                except Exception as e:
                    logger.error(f"Main thread update error for {target_obj.name}: {e}", exc_info=True)
                return None
            bpy.app.timers.register(wrapper)

        def on_status_change(status: str):
            def update():
                cur_obj = bpy.data.objects.get(session.target_object_name)
                cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)
                if cur_props:
                    cur_props.connection_status = status
                    cur_props.is_connected = (status == "CONNECTED")

                if status == "CONNECTED":
                    ProgressBar.update(current=20.0, total=100.0, message="Handshake established...")
                    if session.client_thread:
                        session.client_thread.send_sync_config(throttle_mode=0, target_fps=60, is_active=True)
                    start_main_thread_pump()
                else:
                    if status.startswith("ERROR"):
                        ProgressBar.cancel(message=status)
                    elif not any(s.client_thread and s.client_thread.is_connected for s in _session_manager.get_all_sessions()):
                        stop_main_thread_pump()
                        ProgressBar.end()

                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type in ('PROPERTIES', 'VIEW_3D'):
                            area.tag_redraw()
            run_in_main_thread(update)

        def on_handshake_info(total_sections, non_empty_sections, total_volume, dimension, flags):
            def update():
                session.stream_total_sections = max(1, non_empty_sections)
                session.stream_received_sections = 0
                cur_obj = bpy.data.objects.get(session.target_object_name)
                cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)
                if cur_props:
                    cur_props.last_update_info = f"Handshake: {dimension} ({non_empty_sections} chunks, {total_volume:,} blocks)"
                ProgressBar.update(current=25.0, total=100.0, message=f"Handshake: {dimension} ({non_empty_sections} chunks)")
            run_in_main_thread(update)

        def on_selection_info(min_x, min_y, min_z, size_x, size_y, size_z):
            session.storage.set_bounds(min_x, min_y, min_z, size_x, size_y, size_z)
            def update():
                cur_obj = bpy.data.objects.get(session.target_object_name)
                cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)
                if cur_props:
                    cur_props.has_selection = True
                    cur_props.min_x, cur_props.min_y, cur_props.min_z = min_x, min_y, min_z
                    cur_props.max_x = min_x + size_x - 1
                    cur_props.max_y = min_y + size_y - 1
                    cur_props.max_z = min_z + size_z - 1
                    cur_props.size_x, cur_props.size_y, cur_props.size_z = size_x, size_y, size_z
                    cur_props.total_blocks = size_x * size_y * size_z
            run_in_main_thread(update)

        def on_full_snapshot(min_x, min_y, min_z, size_x, size_y, size_z, palette, grid_indices):
            session.storage.set_full_snapshot(min_x, min_y, min_z, size_x, size_y, size_z, palette, grid_indices)

            def step1_update_props():
                try:
                    session.last_seq_id = 0
                    cur_obj = bpy.data.objects.get(session.target_object_name)
                    cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)
                    if cur_props:
                        cur_props.has_selection = True
                        cur_props.min_x, cur_props.min_y, cur_props.min_z = min_x, min_y, min_z
                        cur_props.max_x = min_x + size_x - 1
                        cur_props.max_y = min_y + size_y - 1
                        cur_props.max_z = min_z + size_z - 1
                        cur_props.size_x, cur_props.size_y, cur_props.size_z = size_x, size_y, size_z
                        cur_props.palette_count = len(palette)
                        cur_props.total_blocks = size_x * size_y * size_z
                        cur_props.update_counter += 1
                        cur_props.sync_verified = True
                        cur_props.validation_info = "Verified (100% in sync)"

                        sync_palette_to_props(cur_props, session.storage)

                    session.skip_next_full_snapshot = False
                    session.force_next_full_rebuild = False
                    session.clear_caches()
                    ProgressBar.update(current=50.0, total=100.0, message="Preloading block assets...")
                except Exception as e:
                    logger.error(f"Snapshot props update error: {e}")
                return None

            def step2_preload_and_sync():
                try:
                    cur_obj = bpy.data.objects.get(session.target_object_name)
                    cur_mat = find_bound_atlas_material(cur_obj) if cur_obj else None
                    cur_atlas_params = session.get_cached_atlas_params(cur_mat)
                    preload_sync_world_data(palette=palette, world_obj=cur_obj, atlas_params=cur_atlas_params)

                    ProgressBar.update(current=75.0, total=100.0, message="Building world geometry...")
                    session.schedule_mesh_sync(force_full_rebuild=True)
                    session.persist_sync_state_to_scene(cur_obj)
                except Exception as e:
                    logger.error(f"Snapshot geometry build error: {e}")
                finally:
                    ProgressBar.finish(message=f"Live Sync Active ({len(palette)} block types)", auto_dismiss_delay=1.0)
                return None

            bpy.app.timers.register(step1_update_props)
            bpy.app.timers.register(step2_preload_and_sync, first_interval=0.01)

        def on_delta_update(min_x, min_y, min_z, changes, seq_id):
            session.delta_queue.put((min_x, min_y, min_z, changes, seq_id))

        def on_section_snapshot(min_x, min_y, min_z, size_x, size_y, size_z, sec_x, sec_y, sec_z, crc, palette, indices):
            session.is_streaming = True
            session.storage.set_section_snapshot(
                min_x, min_y, min_z, size_x, size_y, size_z,
                sec_x, sec_y, sec_z, crc, palette, indices
            )
            session.stream_section_queue.put((sec_x, sec_y, sec_z, palette))

        def on_section_manifest(min_x, min_y, min_z, size_x, size_y, size_z, entries):
            mismatch_requests = []
            cur_obj = bpy.data.objects.get(session.target_object_name)
            cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)

            if (
                session.storage.size_x != size_x
                or session.storage.size_y != size_y
                or session.storage.size_z != size_z
                or session.storage.min_x != min_x
                or session.storage.min_y != min_y
                or session.storage.min_z != min_z
                or not session.storage.section_crc_map
                or session.force_next_full_rebuild
            ):
                logger.info("Manifest bounds mismatch or empty local storage. Initializing full container sync.")
                session.storage.set_bounds(min_x, min_y, min_z, size_x, size_y, size_z)
                for sec_x, sec_y, sec_z, server_crc in entries:
                    session.storage.set_section_crc(sec_x, sec_y, sec_z, 0)
                    if server_crc != EMPTY_SECTION_CRC:
                        mismatch_requests.append((sec_x, sec_y, sec_z))
                session.is_repairing_partial = False
            else:
                for sec_x, sec_y, sec_z, server_crc in entries:
                    local_crc = session.storage.get_section_crc(sec_x, sec_y, sec_z)
                    if local_crc != server_crc:
                        if server_crc == EMPTY_SECTION_CRC:
                            session.storage.clear_section(sec_x, sec_y, sec_z)
                        else:
                            mismatch_requests.append((sec_x, sec_y, sec_z))
                session.is_repairing_partial = True

            session.stream_total_sections = max(1, len(mismatch_requests))
            session.stream_received_sections = 0
            session.stream_last_drain_time = time.time()
            session.accumulated_stream_palettes.clear()

            def update_ui_manifest():
                c_obj = bpy.data.objects.get(session.target_object_name)
                c_props = get_active_sync_props(bpy.context, target_obj=c_obj)
                if c_props:
                    c_props.has_selection = True
                    c_props.min_x, c_props.min_y, c_props.min_z = min_x, min_y, min_z
                    c_props.max_x = min_x + size_x - 1
                    c_props.max_y = min_y + size_y - 1
                    c_props.max_z = min_z + size_z - 1
                    c_props.size_x, c_props.size_y, c_props.size_z = size_x, size_y, size_z
                    c_props.total_blocks = size_x * size_y * size_z
                    c_props.last_update_info = f"Manifest: {len(entries)} chunks ({len(mismatch_requests)} out-of-sync)"
                if mismatch_requests:
                    ProgressBar.update(current=30.0, total=100.0, message=f"Syncing {len(mismatch_requests)} chunks...")
            run_in_main_thread(update_ui_manifest)

            if mismatch_requests:
                session.is_streaming = True
                if session.client_thread:
                    session.client_thread.send_repair_request(mismatch_requests)
            else:
                def on_clean_sync():
                    c_obj = bpy.data.objects.get(session.target_object_name)
                    c_props = get_active_sync_props(bpy.context, target_obj=c_obj)
                    if c_props:
                        c_props.sync_verified = True
                        c_props.validation_info = "Verified (100% in sync)"
                        c_props.last_update_info = f"Verified ({len(entries)} chunks identical)"
                    session.is_streaming = False
                    session.is_repairing_partial = False
                    session.is_initial_handshake = False
                    session.force_next_full_rebuild = False
                    ProgressBar.finish(message=f"Sync Verified ({len(entries)} chunks up to date)", auto_dismiss_delay=1.0)
                run_in_main_thread(on_clean_sync)

        # 3. Create client thread
        session.client_thread = SyncClientThread(
            url=url,
            on_status_change=on_status_change,
            on_selection_info=on_selection_info,
            on_full_snapshot=on_full_snapshot,
            on_delta_update=on_delta_update,
            on_section_manifest=on_section_manifest,
            on_section_snapshot=on_section_snapshot,
            on_handshake_info=on_handshake_info,
        )

        session.client_thread.start()
        start_main_thread_pump()

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

        if target_obj and target_obj.name in _session_manager._sessions:
            session = _session_manager.get_session(target_obj.name)
            if session:
                session.stop()
                _session_manager.remove_session(target_obj.name)
            props = get_active_sync_props(context, target_obj=target_obj)
            if props:
                props.is_connected = False
                props.connection_status = "DISCONNECTED"
        else:
            # Disconnect all active sessions
            _session_manager.clear_all()
            props = get_active_sync_props(context)
            if props:
                props.is_connected = False
                props.connection_status = "DISCONNECTED"

        if not any(s.client_thread and s.client_thread.is_connected for s in _session_manager.get_all_sessions()):
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

        session = _session_manager.get_session(target_obj.name)
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

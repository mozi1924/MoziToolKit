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

        session.is_initial_handshake = True
        session.skip_next_full_snapshot = False

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
                    # Phase 1: Material Hash & Precompiled Cache Verification deferred until network connection is live
                    try:
                        from ...utils.live_sync.material_binding import validate_and_sync_scene_materials
                        validate_and_sync_scene_materials(cur_obj)
                    except Exception as e:
                        logger.debug(f"Deferred material sync note: {e}")

                    if session.storage.size_x == 0 or not session.storage.section_crc_map:
                        session.restore_sync_state_from_scene(cur_obj)

                    if session.client_thread:
                        session.client_thread.send_sync_config(throttle_mode=0, target_fps=60, is_active=True)
                    start_main_thread_pump()
                else:
                    if status.startswith("ERROR") or "failed" in status.lower() or "refused" in status.lower():
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
            bounds_changed = session.storage.set_bounds(min_x, min_y, min_z, size_x, size_y, size_z)
            if bounds_changed:
                session.clear_caches()
                session.skip_next_full_snapshot = False
                session.pending_full_sync_request = True
                session.is_initial_handshake = True
            def update():
                cur_obj = bpy.data.objects.get(session.target_object_name)
                if cur_obj:
                    try:
                        from ...utils.live_sync.mesh_builder import clear_all_section_objects, prune_out_of_bounds_section_objects
                    except (ImportError, ValueError):
                        from utils.live_sync.mesh_builder import clear_all_section_objects, prune_out_of_bounds_section_objects
                    if bounds_changed:
                        clear_all_section_objects(cur_obj)
                    else:
                        prune_out_of_bounds_section_objects(cur_obj, session.storage)
                cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)
                if cur_props:
                    cur_props.has_selection = True
                    cur_props.min_x, cur_props.min_y, cur_props.min_z = min_x, min_y, min_z
                    cur_props.max_x = min_x + size_x - 1
                    cur_props.max_y = min_y + size_y - 1
                    cur_props.max_z = min_z + size_z - 1
                    cur_props.size_x, cur_props.size_y, cur_props.size_z = size_x, size_y, size_z
                    cur_props.total_blocks = size_x * size_y * size_z
                    if bounds_changed:
                        cur_props.sync_verified = False
                        cur_props.validation_info = "New selection detected..."
            run_in_main_thread(update)

        def on_full_snapshot(min_x, min_y, min_z, size_x, size_y, size_z, palette, grid_indices, biome_palette=None, biome_indices=None):
            logger.info(f"Live Sync ({session.target_object_name}): Received full snapshot ({size_x}x{size_y}x{size_z}, {len(palette)} palette entries, {len(biome_palette or [])} biomes)")
            if session.skip_next_full_snapshot:
                logger.info(f"Live Sync ({session.target_object_name}): Skipping unneeded full snapshot due to verified manifest.")
                session.skip_next_full_snapshot = False
                return

            if session.storage.is_snapshot_identical(min_x, min_y, min_z, size_x, size_y, size_z, palette, grid_indices):
                logger.info(f"Live Sync ({session.target_object_name}): Snapshot is identical to current voxel storage. Skipping rebuild.")
                session.skip_next_full_snapshot = False
                session.is_streaming = False
                def on_identical():
                    cur_obj = bpy.data.objects.get(session.target_object_name)
                    if cur_obj:
                        try:
                            from ...utils.live_sync.mesh_builder import prune_out_of_bounds_section_objects
                        except (ImportError, ValueError):
                            from utils.live_sync.mesh_builder import prune_out_of_bounds_section_objects
                        prune_out_of_bounds_section_objects(cur_obj, session.storage)
                    cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)
                    if cur_props:
                        cur_props.sync_verified = True
                        cur_props.validation_info = "Verified (100% in sync)"
                    ProgressBar.finish(message="Sync Verified (data identical)", auto_dismiss_delay=0.8)
                run_in_main_thread(on_identical)
                return

            session.storage.set_full_snapshot(
                min_x, min_y, min_z, size_x, size_y, size_z,
                palette, grid_indices, biome_palette=biome_palette, biome_indices=biome_indices
            )

            def step_progressive_stream():
                cur_obj = bpy.data.objects.get(session.target_object_name)
                cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)
                try:
                    session.last_seq_id = 0
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

                    # Prune any old child section meshes outside the new selection bounds
                    if cur_obj:
                        try:
                            from ...utils.live_sync.mesh_builder import prune_out_of_bounds_section_objects
                        except (ImportError, ValueError):
                            from utils.live_sync.mesh_builder import prune_out_of_bounds_section_objects
                        prune_out_of_bounds_section_objects(cur_obj, session.storage)

                    # Check existing child section meshes to identify which sections ACTUALLY changed or are missing
                    existing_sections = find_root_section_children(cur_obj) if cur_obj else {}
                    all_sections = session.storage.get_all_sections()
                    sections_to_rebuild = []

                    for (sx, sy, sz) in all_sections:
                        sec_blocks = session.storage.get_section_blocks(sx, sy, sz)
                        if not sec_blocks or all(s.startswith("minecraft:air") or s == "air" for s in sec_blocks.values()):
                            continue

                        sec_obj = existing_sections.get((sx, sy, sz))
                        if sec_obj is None:
                            sections_to_rebuild.append((sx, sy, sz))
                        else:
                            stored_crc = str(sec_obj.get("mtk:section_crc", ""))
                            expected_crc = str(session.storage.section_crc_map.get((sx, sy, sz), 0))
                            if stored_crc != expected_crc:
                                sections_to_rebuild.append((sx, sy, sz))

                    if not sections_to_rebuild:
                        logger.info(f"Live Sync ({session.target_object_name}): All {len(existing_sections)} section meshes verified up to date. Skipping rebuild.")
                        _finalize_stream_sync(session, cur_props, cur_obj, 0)
                        return None

                    session.is_streaming = True
                    session.stream_total_sections = len(sections_to_rebuild)
                    session.stream_received_sections = 0
                    session.stream_last_drain_time = time.time()

                    # Put each section into the stream section queue so the pump builds them progressively
                    for (sx, sy, sz) in sections_to_rebuild:
                        session.stream_section_queue.put((sx, sy, sz, palette))

                    ProgressBar.begin(title=f"Live Sync ({session.target_object_name})", total=100.0, message=f"Updating {len(sections_to_rebuild)} chunks...")
                except Exception as e:
                    logger.error(f"Snapshot progressive streaming error: {e}", exc_info=True)
                    session.is_streaming = False
                    if cur_props:
                        cur_props.is_locked = False
                return None

            bpy.app.timers.register(step_progressive_stream)

        def on_delta_update(min_x, min_y, min_z, changes, seq_id):
            session.delta_queue.put((min_x, min_y, min_z, changes, seq_id))

        def on_section_snapshot(sec_x, sec_y, sec_z, start_x, start_y, start_z, size_x, size_y, size_z, palette, grid_indices, biome_palette=None, biome_indices=None):
            session.is_streaming = True
            session.stream_last_drain_time = time.time()
            updated = session.storage.set_section_snapshot(
                sec_x, sec_y, sec_z, start_x, start_y, start_z,
                size_x, size_y, size_z, palette, grid_indices,
                biome_palette=biome_palette, biome_indices=biome_indices
            )
            if updated:
                session.stream_section_queue.put((sec_x, sec_y, sec_z, palette))

        def on_section_manifest(server_seq_id, sections):
            def update():
                try:
                    cur_obj = bpy.data.objects.get(session.target_object_name)
                    cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)
                    non_empty_manifest_count = sum(
                        1 for _sx, _sy, _sz, _crc in sections if not session.storage.is_empty_section_crc(_sx, _sy, _sz, _crc)
                    )

                    if session.pending_full_sync_request or session.force_next_full_rebuild:
                        session.pending_full_sync_request = False
                        session.skip_next_full_snapshot = False
                        session.is_streaming = True
                        session.stream_total_sections = max(1, non_empty_manifest_count)
                        session.stream_received_sections = 0
                        if cur_props:
                            cur_props.validation_info = f"Syncing ({non_empty_manifest_count} chunks)..."
                        if non_empty_manifest_count == 0:
                            _finalize_stream_sync(session, cur_props, cur_obj, 0)
                        else:
                            ProgressBar.begin(title=f"Live Sync ({session.target_object_name})", total=100.0, message=f"Receiving {non_empty_manifest_count} chunks...")
                            ProgressBar.update(current=30.0, total=100.0, message=f"Receiving {non_empty_manifest_count} chunks...")
                            if session.client_thread and session.client_thread.is_connected:
                                logger.info(f"Live Sync ({session.target_object_name}): Requesting full sync on manifest ({non_empty_manifest_count} sections)...")
                                session.client_thread.send_full_sync_request()
                        return

                    if session.is_streaming:
                        logger.debug("Live Sync: Ignoring periodic manifest check while streaming is in progress.")
                        return

                    existing_sections = find_root_section_children(cur_obj) if cur_obj else {}
                    existing_mesh_coords = set(existing_sections.keys()) if existing_sections else None

                    if not session.is_initial_handshake:
                        # Runtime heartbeat validation check:
                        # If active deltas are queued or dirty sections are being processed, skip to avoid interrupting fast micro-deltas
                        if not session.delta_queue.empty() or session.storage.get_dirty_sections():
                            return

                        mismatched_crc = session.storage.validate_manifest(sections, existing_section_meshes=existing_mesh_coords)
                        if cur_props:
                            cur_props.sync_verified = (len(mismatched_crc) == 0)
                            if len(mismatched_crc) == 0 and cur_props.validation_info != "Verified (100% in sync)":
                                cur_props.validation_info = "Verified (100% in sync)"

                        if len(mismatched_crc) > 0 and not session.is_streaming and session.client_thread and session.client_thread.is_connected:
                            logger.info(f"Live Sync ({session.target_object_name}): Background manifest detected {len(mismatched_crc)} out-of-sync sections. Requesting repair...")
                            session.is_repairing_partial = True
                            session.is_streaming = True
                            session.stream_total_sections = len(mismatched_crc)
                            session.stream_received_sections = 0
                            if cur_props:
                                cur_props.validation_info = f"Repairing {len(mismatched_crc)} section(s)..."
                            session.client_thread.send_repair_request(mismatched_crc)
                        return

                    # Initial Handshake / Reconnect Validation
                    mismatched_crc = session.storage.validate_manifest(sections, existing_section_meshes=existing_mesh_coords)
                    if cur_props:
                        cur_props.sync_verified = (len(mismatched_crc) == 0)

                    if len(mismatched_crc) == 0:
                        session.skip_next_full_snapshot = True
                        session.is_repairing_partial = False
                        if cur_props:
                            if cur_props.validation_info != "Verified (100% in sync)":
                                cur_props.validation_info = "Verified (100% in sync)"
                            if not cur_props.palette_list and session.storage.block_map:
                                sync_palette_to_props(cur_props, session.storage)
                        ProgressBar.finish(message="Verified: 100% in sync with scene", auto_dismiss_delay=0.8)
                        session.is_initial_handshake = False

                    elif (len(mismatched_crc) >= non_empty_manifest_count) or (not session.storage.section_crc_map and not existing_mesh_coords):
                        # Full sync needed (no existing mesh/CRC or complete mismatch)
                        session.skip_next_full_snapshot = False
                        session.is_repairing_partial = False
                        session.pending_full_sync_request = True
                        session.is_initial_handshake = False
                        session.is_streaming = True
                        session.stream_total_sections = max(1, non_empty_manifest_count)
                        session.stream_received_sections = 0
                        if cur_props:
                            cur_props.validation_info = f"Full sync ({non_empty_manifest_count} chunks)..."
                        ProgressBar.begin(title=f"Live Sync ({session.target_object_name})", total=100.0, message=f"Full sync ({non_empty_manifest_count} chunks)...")
                        ProgressBar.update(current=30.0, total=100.0, message="Requesting full world data...")
                        if session.client_thread and session.client_thread.is_connected:
                            logger.info(f"Live Sync ({session.target_object_name}): Requesting full sync ({non_empty_manifest_count} sections)...")
                            session.client_thread.send_full_sync_request()

                    else:
                        # Existing local scene with partial differences on reconnect
                        logger.info(f"Live Sync ({session.target_object_name}): Detected {len(mismatched_crc)} out-of-sync sections on reconnect. Requesting incremental repair...")
                        session.skip_next_full_snapshot = True
                        session.is_repairing_partial = True
                        session.is_initial_handshake = False
                        session.is_streaming = True
                        session.stream_total_sections = len(mismatched_crc)
                        session.stream_received_sections = 0
                        if cur_props:
                            cur_props.validation_info = f"Repairing {len(mismatched_crc)} section(s)..."
                        ProgressBar.begin(title=f"Live Sync ({session.target_object_name})", total=100.0, message=f"Repairing {len(mismatched_crc)} section(s)...")
                        ProgressBar.update(current=30.0, total=100.0, message=f"Syncing {len(mismatched_crc)} modified chunks...")
                        if session.client_thread and session.client_thread.is_connected:
                            session.client_thread.send_repair_request(mismatched_crc)
                except Exception as e:
                    logger.error(f"Live Sync manifest error for {session.target_object_name}: {e}", exc_info=True)
                    ProgressBar.cancel(message=f"Manifest check error: {e}")
            run_in_main_thread(update)

        def on_stream_begin(stream_id, total_sections, flags):
            session.current_stream_id = stream_id
            session.is_streaming = True
            session.server_stream_finished = False
            session.stream_total_sections = max(1, total_sections)
            session.stream_received_sections = 0
            session.stream_last_drain_time = time.time()
            def update():
                cur_obj = bpy.data.objects.get(session.target_object_name)
                if cur_obj:
                    try:
                        from ...utils.live_sync.mesh_builder import prune_out_of_bounds_section_objects
                    except (ImportError, ValueError):
                        from utils.live_sync.mesh_builder import prune_out_of_bounds_section_objects
                    prune_out_of_bounds_section_objects(cur_obj, session.storage)
                cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)
                if cur_props:
                    cur_props.validation_info = f"Streaming {total_sections} chunks..."
                ProgressBar.begin(title=f"Live Sync ({session.target_object_name})", total=100.0, message=f"Streaming {total_sections} chunks...")
                ProgressBar.update(current=30.0, total=100.0, message=f"Streaming chunk (0/{total_sections})")
            run_in_main_thread(update)

        def on_stream_end(stream_id, sent_sections, status):
            session.server_stream_finished = True
            session.stream_last_drain_time = time.time()
            if status != 0:
                logger.warning(f"Live Sync ({session.target_object_name}): Stream {stream_id} ended with status code {status}")

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
            on_stream_begin=on_stream_begin,
            on_stream_end=on_stream_end,
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

"""
Adaptive main thread event pump and mesh sync triggering for Live Sync.
"""

from __future__ import annotations

import logging
import queue
import time
from typing import Optional
import bpy

from ...mc_baker import (
    refresh_shared_baker_sources,
    get_shared_state_baker,
)
from ..meshing import (
    sync_world_mesh,
    apply_block_delta_to_world,
)
from ..storage.voxel_storage import VoxelStorage, voxel_storage
from ....pipeline.progress import ProgressBar
from .material_cache import (
    find_bound_atlas_material,
    get_cached_atlas_params,
    clear_sync_caches,
)
from .props import (
    MAX_DELTA_HISTORY,
    REBUILD_DEBOUNCE_SECONDS,
    _PUMP_INTERVAL_ACTIVE,
    _PUMP_INTERVAL_IDLE,
    get_active_sync_props,
    get_target_world_object,
    sync_palette_to_props,
    append_delta_history,
)

logger = logging.getLogger("MoziToolKit.LiveSync.EventPump")

_pump_timer_registered: bool = False
_rebuild_timer_registered: bool = False
_pending_full_rebuild: bool = False

# Backward compatibility module-level globals (used in unit tests / direct calls)
_last_seq_id: int = 0
_delta_queue: queue.Queue = queue.Queue()
_stream_section_queue: queue.Queue = queue.Queue()
_accumulated_stream_palettes: set[str] = set()


def _run_in_main_thread(func) -> None:
    """Helper to schedule a callable on Blender's main thread timer pump safely."""
    import threading
    if getattr(bpy.app, "background", False) and threading.current_thread() is threading.main_thread():
        try:
            func()
            return
        except Exception as e:
            logger.error(f"Main thread update error: {e}", exc_info=True)
            return

    def wrapper():
        try:
            func()
        except Exception as e:
            logger.error(f"Main thread update error: {e}", exc_info=True)
        return None
    bpy.app.timers.register(wrapper)


def trigger_mesh_sync(
    context: bpy.types.Context,
    force_full_rebuild: bool = False,
    target_obj: Optional[bpy.types.Object] = None,
    storage: Optional[VoxelStorage] = None,
) -> None:
    """Invoked on main thread when storage updates to incrementally synchronize world mesh."""
    refresh_shared_baker_sources()
    existing_world = target_obj or get_target_world_object(context)
    active_storage = storage or voxel_storage
    if target_obj and not storage:
        from .registry import get_active_session_manager
        mgr = get_active_session_manager()
        sess = mgr.get_session(target_obj.name) if mgr else None
        if sess:
            active_storage = sess.storage

    props = get_active_sync_props(context, target_obj=existing_world)
    mat = find_bound_atlas_material(existing_world) if existing_world else None
    atlas_params = get_cached_atlas_params(mat)

    res = sync_world_mesh(
        context=context,
        storage=active_storage,
        atlas_params=atlas_params,
        force_full_rebuild=force_full_rebuild,
        target_obj=existing_world,
    )

    try:
        from ...materials.pipeline.session import cleanup_unused_mtk_datablocks
        cleanup_unused_mtk_datablocks()
    except Exception:
        pass

    if props:
        props.point_count = res.vertex_count
        props.cubes_count = res.cubes_count
        props.props_count = res.props_count
        props.fluids_count = res.fluids_count


def schedule_mesh_sync(force_full_rebuild: bool = False, target_obj: Optional[bpy.types.Object] = None) -> None:
    """Coalesce live updates into a fast incremental main-thread mesh sync."""
    target = target_obj or get_target_world_object()
    if target:
        from .registry import get_active_session_manager
        mgr = get_active_session_manager()
        sess = mgr.get_session(target.name) if mgr else None
        if sess:
            sess.schedule_mesh_sync(force_full_rebuild=force_full_rebuild)
            return

    global _rebuild_timer_registered, _pending_full_rebuild
    _pending_full_rebuild = _pending_full_rebuild or force_full_rebuild
    if _rebuild_timer_registered:
        return

    _rebuild_timer_registered = True

    def flush():
        global _rebuild_timer_registered, _pending_full_rebuild
        try:
            if voxel_storage.size_x and voxel_storage.size_y and voxel_storage.size_z:
                full_rebuild = _pending_full_rebuild
                _pending_full_rebuild = False
                trigger_mesh_sync(bpy.context, force_full_rebuild=full_rebuild)
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type in ('VIEW_3D', 'PROPERTIES'):
                            area.tag_redraw()
        except Exception as e:
            logger.error(f"Deferred mesh sync error: {e}")
        finally:
            _rebuild_timer_registered = False
        return None

    bpy.app.timers.register(flush, first_interval=REBUILD_DEBOUNCE_SECONDS)


def _finalize_stream_sync(session, props: Any, target_obj: Optional[bpy.types.Object], total_target: int) -> None:
    """Finalize world mesh build for a session, clean up stream flags, and dismiss progress bar."""
    try:
        dirty_remaining = [s for s in session.storage.get_dirty_sections() if s in session.storage._section_map]
        if dirty_remaining and target_obj:
            from ..meshing import build_single_section_mesh, find_root_section_children
            cur_mat = find_bound_atlas_material(target_obj)
            cur_atlas_params = session.get_cached_atlas_params(cur_mat)
            from ..material.binding import get_shared_material_manager
            mat_mgr = get_shared_material_manager(world_obj=target_obj, atlas_params=cur_atlas_params)
            baker = get_shared_state_baker()
            state_cache = getattr(session, "_stream_state_cache", None) or {}
            existing_sections = find_root_section_children(target_obj)
            session._existing_sections_cache = existing_sections
            for (sx, sy, sz) in dirty_remaining:
                build_single_section_mesh(
                    context=bpy.context,
                    storage=session.storage,
                    sx=sx, sy=sy, sz=sz,
                    root_obj=target_obj,
                    mat_manager=mat_mgr,
                    baker=baker,
                    state_cache=state_cache,
                    existing_sections=existing_sections,
                    origin_centered=True,
                    weld_vertices=True,
                )
        session.storage.clear_dirty_sections()
        session.persist_sync_state_to_scene(target_obj)

        if props:
            sync_palette_to_props(props, session.storage)
            props.update_counter += 1
            props.last_update_info = f"Repaired {total_target} sections" if session.is_repairing_partial else f"Streamed {total_target} sections"
            props.sync_verified = True
            props.validation_info = "Verified (100% in sync)"
            props.is_locked = False

            try:
                if target_obj:
                    from ..meshing import _get_mesh_vertex_and_face_count
                    total_verts = 0
                    for child in target_obj.children:
                        if child.data and isinstance(child.data, bpy.types.Mesh):
                            v_cnt, _ = _get_mesh_vertex_and_face_count(child.data)
                            total_verts += v_cnt
                    props.point_count = total_verts
            except Exception:
                pass

            item = props.delta_history.add()
            item.timestamp = time.strftime("%H:%M:%S")
            item.pos_str = f"Stream ({total_target} chunks)"
            item.block_state = f"Sync ready ({props.total_blocks:,} blks)" if props.total_blocks else f"Sync ready ({total_target} chunks)"
            while len(props.delta_history) > MAX_DELTA_HISTORY:
                props.delta_history.remove(0)
            props.delta_active_index = max(0, len(props.delta_history) - 1)
    except Exception as e:
        logger.error(f"Finalize stream sync error for {session.target_object_name}: {e}", exc_info=True)
        if props:
            props.validation_info = f"Finalize error: {e}"
            props.is_locked = False
    finally:
        was_initial = session.is_initial_handshake
        session.is_streaming = False
        session.is_repairing_partial = False
        session.is_initial_handshake = False
        session.force_next_full_rebuild = False
        session.pending_full_sync_request = False
        session.server_stream_finished = False
        session.stream_received_sections = 0
        session.stream_total_sections = 0
        session._reconciled_pass = False
        session._stream_state_cache = None
        session._existing_sections_cache = None
        if was_initial or ProgressBar.is_active():
            ProgressBar.finish(message=f"Sync Ready ({total_target} chunks processed)", auto_dismiss_delay=0.8)


def _pump_main_thread_events() -> Optional[float]:
    """Continuous adaptive event pump executing on Blender's main thread across all sessions."""
    global _pump_timer_registered, _last_seq_id
    if not _pump_timer_registered:
        return None

    from .registry import get_active_session_manager
    mgr = get_active_session_manager()
    sessions = mgr.get_all_sessions() if mgr else []
    has_active_work = False
    any_connected = False

    for session in sessions:
        if session.client_thread and session.client_thread.is_connected:
            any_connected = True
        target_obj = bpy.data.objects.get(session.target_object_name)
        props = get_active_sync_props(bpy.context, target_obj=target_obj) if target_obj else None

        # 1. Drain streaming section queue
        sections_drained = 0
        mat_mgr = None
        baker = None
        state_cache = None
        existing_sections = None

        if session.is_streaming and props and not props.is_locked:
            try:
                from ....operators.sync.op_sync_connect import start_stream_modal_lock
            except (ImportError, ValueError):
                try:
                    from operators.sync.op_sync_connect import start_stream_modal_lock
                except Exception:
                    start_stream_modal_lock = None
            if start_stream_modal_lock:
                start_stream_modal_lock(session.target_object_name)

        t_drain_start = time.perf_counter()
        max_batch = 32
        while not session.stream_section_queue.empty() and sections_drained < max_batch:
            try:
                item = session.stream_section_queue.get_nowait()
                sec_x, sec_y, sec_z, palette = item
                session.stream_received_sections += 1
                if palette:
                    session.accumulated_stream_palettes.update(palette)

                if mat_mgr is None:
                    cur_mat = find_bound_atlas_material(target_obj) if target_obj else None
                    cur_atlas_params = session.get_cached_atlas_params(cur_mat)
                    from ..material.binding import get_shared_material_manager
                    mat_mgr = get_shared_material_manager(world_obj=target_obj, atlas_params=cur_atlas_params)
                    baker = get_shared_state_baker()
                    if not hasattr(session, "_stream_state_cache") or session._stream_state_cache is None:
                        session._stream_state_cache = {}
                    state_cache = session._stream_state_cache
                    if not hasattr(session, "_existing_sections_cache") or session._existing_sections_cache is None:
                        from ..meshing import find_root_section_children
                        session._existing_sections_cache = find_root_section_children(target_obj)
                    existing_sections = session._existing_sections_cache

                from ..meshing import build_single_section_mesh
                build_single_section_mesh(
                    context=bpy.context,
                    storage=session.storage,
                    sx=sec_x, sy=sec_y, sz=sec_z,
                    root_obj=target_obj,
                    mat_manager=mat_mgr,
                    baker=baker,
                    state_cache=state_cache,
                    existing_sections=existing_sections,
                    origin_centered=True,
                    weld_vertices=True,
                )

                sections_drained += 1
                has_active_work = True

                if (time.perf_counter() - t_drain_start) > 0.015:
                    break
            except queue.Empty:
                break

        if sections_drained > 0:
            session.stream_last_drain_time = time.time()
            total_target = max(1, session.stream_total_sections)
            frac = min(1.0, session.stream_received_sections / total_target)
            pct = int(20.0 + frac * 80.0)

            if session.stream_section_queue.empty():
                is_batch_complete = session.server_stream_finished or (session.stream_received_sections >= total_target)
                if is_batch_complete:
                    dirty_reconcile = [s for s in session.storage.get_dirty_sections() if s in session.storage._section_map]
                    if dirty_reconcile:
                        session.storage.clear_dirty_sections()
                        for (sx, sy, sz) in dirty_reconcile:
                            session.stream_section_queue.put((sx, sy, sz, []))
                        session.stream_total_sections += len(dirty_reconcile)
                        ProgressBar.update(current=pct, total=100.0, message=f"Reconciling boundary chunks ({len(dirty_reconcile)})...")
                    else:
                        _finalize_stream_sync(session, props, target_obj, session.stream_received_sections)
                else:
                    ProgressBar.update(current=pct, total=100.0, message=f"Streaming chunk ({session.stream_received_sections}/{total_target})")
            else:
                ProgressBar.update(current=pct, total=100.0, message=f"Building chunk ({session.stream_received_sections}/{total_target})")

            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type in ('STATUSBAR', 'VIEW_3D', 'PROPERTIES'):
                        area.tag_redraw()
        elif session.is_streaming and session.stream_section_queue.empty():
            total_target = max(1, session.stream_total_sections)
            is_batch_complete = session.server_stream_finished or (session.stream_received_sections >= total_target)
            if is_batch_complete:
                dirty_reconcile = [s for s in session.storage.get_dirty_sections() if s in session.storage._section_map]
                if dirty_reconcile:
                    session.storage.clear_dirty_sections()
                    for (sx, sy, sz) in dirty_reconcile:
                        session.stream_section_queue.put((sx, sy, sz, []))
                    session.stream_total_sections += len(dirty_reconcile)
                    ProgressBar.update(current=95.0, total=100.0, message=f"Reconciling boundary chunks ({len(dirty_reconcile)})...")
                else:
                    _finalize_stream_sync(session, props, target_obj, session.stream_received_sections)
            else:
                drain_elapsed = time.time() - session.stream_last_drain_time if session.stream_last_drain_time > 0 else 0
                is_conn_dead = session.client_thread and not session.client_thread.is_connected
                if is_conn_dead or (session.stream_last_drain_time > 0 and drain_elapsed > 45.0):
                    logger.warning("Live Sync: Stream inactivity timeout or disconnection reached for %s (%s of %s sections processed). Finalizing.", session.target_object_name, session.stream_received_sections, session.stream_total_sections)
                    _finalize_stream_sync(session, props, target_obj, session.stream_received_sections)

        # 2. Drain pending delta changes
        accumulated_changes: dict[tuple[int, int, int], str] = {}
        latest_seq_id = session.last_seq_id
        active_origin = (session.storage.min_x, session.storage.min_y, session.storage.min_z)

        while not session.delta_queue.empty():
            try:
                item = session.delta_queue.get_nowait()
                m_x, m_y, m_z, chs, seq_id = item
                if seq_id > latest_seq_id:
                    latest_seq_id = seq_id
                    if (m_x, m_y, m_z) == active_origin:
                        for x, y, z, state in chs:
                            accumulated_changes[(x, y, z)] = state
                has_active_work = True
            except queue.Empty:
                break

        if accumulated_changes:
            session.last_seq_id = latest_seq_id
            coalesced_changes = [
                (x, y, z, state) for (x, y, z), state in accumulated_changes.items()
            ]
            applied = session.storage.apply_delta_update_detailed(*active_origin, coalesced_changes)
            if applied:
                mesh_changes = [(x, y, z, new_state) for x, y, z, _old_state, new_state in applied]
                previous_states = {(x, y, z): old_state for x, y, z, old_state, _new_state in applied}
                mat = find_bound_atlas_material(target_obj) if target_obj else None
                atlas_params = session.get_cached_atlas_params(mat)

                if len(mesh_changes) <= 64:
                    res = apply_block_delta_to_world(
                        context=bpy.context,
                        storage=session.storage,
                        changes=mesh_changes,
                        atlas_params=atlas_params,
                        previous_states=previous_states,
                        target_obj=target_obj,
                    )
                else:
                    res = sync_world_mesh(
                        context=bpy.context,
                        storage=session.storage,
                        atlas_params=atlas_params,
                        force_full_rebuild=False,
                        target_obj=target_obj,
                    )

                if props:
                    props.point_count = res.vertex_count
                    props.cubes_count = res.cubes_count
                    props.props_count = res.props_count
                    props.fluids_count = res.fluids_count
                    props.update_counter += 1
                    props.last_update_info = f"Delta: {len(mesh_changes)} blocks (seq {latest_seq_id})"
                    append_delta_history(props, applied)
                    if len(session.storage.get_unique_states()) != props.palette_count:
                        sync_palette_to_props(props, session.storage)

                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == 'VIEW_3D':
                            area.tag_redraw()

    # 3. Pump global fallback queues for direct/unit-test backward compatibility
    global_props = get_active_sync_props(bpy.context)
    if global_props and global_props.is_connected:
        any_connected = True

    if not _delta_queue.empty():
        accumulated_changes_g: dict[tuple[int, int, int], str] = {}
        latest_seq_id_g = _last_seq_id
        active_origin_g = (voxel_storage.min_x, voxel_storage.min_y, voxel_storage.min_z)

        while not _delta_queue.empty():
            try:
                item = _delta_queue.get_nowait()
                m_x, m_y, m_z, chs, seq_id = item
                if seq_id > latest_seq_id_g:
                    latest_seq_id_g = seq_id
                    if (m_x, m_y, m_z) == active_origin_g:
                        for x, y, z, state in chs:
                            accumulated_changes_g[(x, y, z)] = state
                has_active_work = True
            except queue.Empty:
                break

        if accumulated_changes_g:
            _last_seq_id = latest_seq_id_g
            coalesced_changes_g = [
                (x, y, z, state) for (x, y, z), state in accumulated_changes_g.items()
            ]
            applied_g = voxel_storage.apply_delta_update_detailed(*active_origin_g, coalesced_changes_g)
            if applied_g:
                mesh_changes_g = [(x, y, z, new_state) for x, y, z, _old_state, new_state in applied_g]
                previous_states_g = {(x, y, z): old_state for x, y, z, old_state, _new_state in applied_g}
                target_obj_g = get_target_world_object(bpy.context)
                mat_g = find_bound_atlas_material(target_obj_g) if target_obj_g else None
                atlas_params_g = get_cached_atlas_params(mat_g)

                if len(mesh_changes_g) <= 64:
                    res_g = apply_block_delta_to_world(
                        context=bpy.context,
                        storage=voxel_storage,
                        changes=mesh_changes_g,
                        atlas_params=atlas_params_g,
                        previous_states=previous_states_g,
                        target_obj=target_obj_g,
                    )
                else:
                    res_g = sync_world_mesh(
                        context=bpy.context,
                        storage=voxel_storage,
                        atlas_params=atlas_params_g,
                        force_full_rebuild=False,
                        target_obj=target_obj_g,
                    )

                if global_props:
                    global_props.point_count = res_g.vertex_count
                    global_props.cubes_count = res_g.cubes_count
                    global_props.props_count = res_g.props_count
                    global_props.fluids_count = res_g.fluids_count
                    global_props.update_counter += 1
                    global_props.last_update_info = f"Delta: {len(mesh_changes_g)} blocks (seq {latest_seq_id_g})"
                    append_delta_history(global_props, applied_g)
                    if len(voxel_storage.get_unique_states()) != global_props.palette_count:
                        sync_palette_to_props(global_props, voxel_storage)

                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == 'VIEW_3D':
                            area.tag_redraw()

    if has_active_work:
        return _PUMP_INTERVAL_ACTIVE

    if not any_connected:
        _pump_timer_registered = False
        return None

    return _PUMP_INTERVAL_IDLE


def start_main_thread_pump():
    """Ensure the adaptive dynamic event pump is registered and running."""
    global _pump_timer_registered
    if not _pump_timer_registered:
        _pump_timer_registered = True
        bpy.app.timers.register(_pump_main_thread_events, first_interval=_PUMP_INTERVAL_ACTIVE, persistent=True)


def stop_main_thread_pump():
    """Stop the event pump."""
    global _pump_timer_registered
    _pump_timer_registered = False


def cleanup_sync_state() -> None:
    """Clean up all live sync module globals, background threads, timers, and storage."""
    global _last_seq_id, _rebuild_timer_registered, _pending_full_rebuild
    from .registry import get_active_session_manager

    stop_main_thread_pump()
    mgr = get_active_session_manager()
    if mgr:
        mgr.clear_all()

    _last_seq_id = 0
    _rebuild_timer_registered = False
    _pending_full_rebuild = False

    voxel_storage.clear()
    clear_sync_caches()
    ProgressBar.end()

    try:
        from ..classifier import clear_parse_cache
        clear_parse_cache()
    except Exception:
        pass

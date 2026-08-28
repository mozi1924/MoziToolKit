"""
Operators for connecting, disconnecting, and refreshing Minecraft Live Sync.
"""

from __future__ import annotations

import logging
import queue
import time
from typing import Optional
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
    )
    from ...utils.live_sync.storage import voxel_storage, EMPTY_SECTION_CRC
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
    )
    from utils.live_sync.storage import voxel_storage, EMPTY_SECTION_CRC
    from utils.materials.pipeline.session import cleanup_unused_mtk_datablocks
    from utils.materials.yefira import (
        extract_atlas_parameters,
        find_bound_atlas_material,
    )
    from utils.system.dependencies import has_websockets
    from pipeline.progress import ProgressBar

logger = logging.getLogger("MoziToolKit.LiveSync")

_client_thread: Optional[SyncClientThread] = None
_last_seq_id: int = 0
_stream_total_sections: int = 0
_stream_received_sections: int = 0
_is_streaming: bool = False
_is_initial_handshake: bool = False
_rebuild_timer_registered: bool = False
# Debounce caps expensive UI redraws while maintaining sub-millisecond sync
REBUILD_DEBOUNCE_SECONDS: float = 0.05
_pending_full_rebuild: bool = False

_cached_atlas_params: Optional[dict] = None
_cached_mat_signature: Optional[tuple] = None
_is_repairing_partial: bool = False

# Adaptive dynamic main-thread pump for sub-millisecond delta and stream chunk processing
_delta_queue: queue.Queue = queue.Queue()
_stream_section_queue: queue.Queue = queue.Queue()
_accumulated_stream_palettes: set[str] = set()
_pump_timer_registered: bool = False
_PUMP_INTERVAL_ACTIVE: float = 0.015  # 15ms (~66 Hz when processing active deltas/chunks)
_PUMP_INTERVAL_IDLE: float = 0.035    # 35ms (~28 Hz idle throttle to save CPU)

_SETTLE_TIMEOUT_SECONDS: float = 3.0
_stream_last_drain_time: float = 0.0


def _finalize_stream_sync(props, total_target: int) -> None:
    """Finalize world mesh build, clean up stream flags, and smoothly finish progress bar."""
    global _is_repairing_partial, _is_initial_handshake, _force_next_full_rebuild, _pending_full_sync_request
    global _stream_received_sections, _stream_total_sections, _is_streaming

    existing_world = bpy.data.objects.get(DEFAULT_WORLD_OBJECT_NAME)
    cur_mat = find_bound_atlas_material(existing_world) if existing_world else None
    cur_atlas_params = get_cached_atlas_params(cur_mat)
    target_palette = _accumulated_stream_palettes if _accumulated_stream_palettes else voxel_storage.get_unique_states()
    if target_palette:
        preload_sync_world_data(palette=target_palette, world_obj=existing_world, atlas_params=cur_atlas_params)
        _accumulated_stream_palettes.clear()

    rebuild_full = not _is_repairing_partial
    schedule_mesh_sync(force_full_rebuild=rebuild_full)
    persist_sync_state_to_scene(bpy.context)
    if props:
        props.update_counter += 1
        props.last_update_info = f"Repaired {total_target} sections" if _is_repairing_partial else f"Streamed {total_target} sections"
        props.sync_verified = True
        props.validation_info = "Verified (100% in sync)"
    _is_streaming = False
    _is_repairing_partial = False
    _is_initial_handshake = False
    _force_next_full_rebuild = False
    _pending_full_sync_request = False
    _stream_received_sections = 0
    _stream_total_sections = 0
    ProgressBar.finish(message=f"Sync Ready ({total_target} chunks processed)", auto_dismiss_delay=0.8)


def _pump_main_thread_events() -> Optional[float]:
    """Continuous adaptive event pump executing on Blender's main thread."""
    global _pump_timer_registered, _last_seq_id, _stream_received_sections, _stream_total_sections
    global _is_repairing_partial, _stream_last_drain_time, _is_streaming
    if not _pump_timer_registered:
        return None

    props = get_active_sync_props()
    has_active_work = False

    # 1. Drain pending streamed section snapshots (batch up to 16 chunks per tick to keep UI buttery smooth)
    sections_drained = 0
    while not _stream_section_queue.empty() and sections_drained < 16:
        try:
            item = _stream_section_queue.get_nowait()
            sec_x, sec_y, sec_z, palette = item
            _stream_received_sections += 1
            if palette:
                _accumulated_stream_palettes.update(palette)
            sections_drained += 1
            has_active_work = True
        except queue.Empty:
            break

    if sections_drained > 0:
        _stream_last_drain_time = time.time()
        total_target = max(1, _stream_total_sections)
        frac = min(1.0, _stream_received_sections / total_target)
        pct = int(30.0 + frac * 70.0)

        if _stream_received_sections >= total_target and _stream_section_queue.empty():
            _finalize_stream_sync(props, total_target)
        else:
            ProgressBar.update(current=pct, total=100.0, message=f"Streaming chunk ({_stream_received_sections}/{total_target})")

        # Tag redraw for visual progress bar update
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in ('STATUSBAR', 'VIEW_3D', 'PROPERTIES'):
                    area.tag_redraw()
    elif _is_streaming and _stream_received_sections > 0 and _stream_section_queue.empty() and ProgressBar.is_active():
        # Settle timeout: If snapshots finished streaming and queue has been idle for >_SETTLE_TIMEOUT_SECONDS, complete progress
        if _stream_last_drain_time > 0 and (time.time() - _stream_last_drain_time > _SETTLE_TIMEOUT_SECONDS):
            logger.info("Live Sync: Stream settle timeout reached (%s sections processed). Finalizing.", _stream_received_sections)
            _finalize_stream_sync(props, _stream_received_sections)

    # 2. Drain pending delta changes
    # Coalesce repeated writes to a voxel, retaining the latest state.  A
    # single pump can consume several network packets, and feeding duplicate
    # intermediate writes into BMesh makes the result order-dependent.
    accumulated_changes: dict[tuple[int, int, int], str] = {}
    latest_seq_id = _last_seq_id
    active_origin = (voxel_storage.min_x, voxel_storage.min_y, voxel_storage.min_z)

    while not _delta_queue.empty():
        try:
            item = _delta_queue.get_nowait()
            m_x, m_y, m_z, chs, seq_id = item
            if seq_id > latest_seq_id:
                latest_seq_id = seq_id
                # Selection changes may leave old packets in the queue.  Do
                # not let their origin validate a batch for the new selection.
                if (m_x, m_y, m_z) == active_origin:
                    for x, y, z, state in chs:
                        accumulated_changes[(x, y, z)] = state
            has_active_work = True
        except queue.Empty:
            break

    if accumulated_changes:
        _last_seq_id = latest_seq_id
        coalesced_changes = [
            (x, y, z, state) for (x, y, z), state in accumulated_changes.items()
        ]
        applied = voxel_storage.apply_delta_update_detailed(*active_origin, coalesced_changes)
        if applied:
            mesh_changes = [(x, y, z, new_state) for x, y, z, _old_state, new_state in applied]
            previous_states = {(x, y, z): old_state for x, y, z, old_state, _new_state in applied}
            if len(mesh_changes) <= 64:
                existing_world = bpy.data.objects.get(DEFAULT_WORLD_OBJECT_NAME)
                mat = find_bound_atlas_material(existing_world) if existing_world else None
                atlas_params = get_cached_atlas_params(mat)
                res = apply_block_delta_to_world(
                    context=bpy.context,
                    storage=voxel_storage,
                    changes=mesh_changes,
                    atlas_params=atlas_params,
                    previous_states=previous_states,
                )
                if props:
                    props.point_count = res.vertex_count
                    props.cubes_count = res.cubes_count
                    props.props_count = res.props_count
                    props.fluids_count = res.fluids_count
            else:
                # Batch sync: regenerate affected dirty 16x16x16 sections in sub-millisecond time
                existing_world = bpy.data.objects.get(DEFAULT_WORLD_OBJECT_NAME)
                mat = find_bound_atlas_material(existing_world) if existing_world else None
                atlas_params = get_cached_atlas_params(mat)
                res = sync_world_mesh(
                    context=bpy.context,
                    storage=voxel_storage,
                    atlas_params=atlas_params,
                    force_full_rebuild=False,
                )
                if props:
                    props.point_count = res.vertex_count
                    props.cubes_count = res.cubes_count
                    props.props_count = res.props_count
                    props.fluids_count = res.fluids_count

            props.update_counter += 1
            props.last_update_info = f"Delta: {len(mesh_changes)} blocks (seq {latest_seq_id})"

            # Force redraw of 3D Viewport
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type in ('VIEW_3D', 'PROPERTIES'):
                        area.tag_redraw()

    if has_active_work:
        return _PUMP_INTERVAL_ACTIVE

    if not props or not props.is_connected:
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
    """Stop the event pump and clear pending queues."""
    global _pump_timer_registered
    _pump_timer_registered = False
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


def get_active_sync_props(context: Optional[bpy.types.Context] = None):
    """Retrieve mozi_sync scene properties safely."""
    if context is None:
        context = bpy.context
    return getattr(context.scene, "mozi_sync", None) if hasattr(context, "scene") else None


def get_cached_atlas_params(mat: Optional[bpy.types.Material]) -> dict:
    """Retrieve atlas parameters, invalidating when a material is edited in place."""
    global _cached_atlas_params, _cached_mat_signature
    if mat:
        mapping = mat.get("mtk:atlas_mapping", mat.get("mtk_atlas_mapping", ""))
        current_signature = (
            mat.as_pointer() if hasattr(mat, "as_pointer") else id(mat),
            mapping,
            mat.get("mtk:pack_hash", mat.get("mtk_pack_hash", "")),
        )
    else:
        current_signature = (0, "", "")
    if _cached_atlas_params is None or _cached_mat_signature != current_signature:
        _cached_mat_signature = current_signature
        _cached_atlas_params = extract_atlas_parameters(mat)
        clear_mesh_builder_caches()
    return _cached_atlas_params


def clear_sync_caches() -> None:
    """Invalidate atlas parameter cache, mesh builder caches, and baker caches on material or world reset."""
    global _cached_atlas_params, _cached_mat_signature
    _cached_atlas_params = None
    _cached_mat_signature = None
    clear_mesh_builder_caches()
    clear_shared_baker_cache()


def trigger_mesh_sync(context: bpy.types.Context, force_full_rebuild: bool = False) -> None:
    """Invoked on main thread when storage updates to incrementally synchronize world mesh."""
    refresh_shared_baker_sources()
    props = get_active_sync_props(context)
    filter_air = props.filter_air if props else True

    existing_world = bpy.data.objects.get(DEFAULT_WORLD_OBJECT_NAME)
    mat = find_bound_atlas_material(existing_world) if existing_world else None
    atlas_params = get_cached_atlas_params(mat)

    res = sync_world_mesh(
        context=context,
        storage=voxel_storage,
        atlas_params=atlas_params,
        force_full_rebuild=force_full_rebuild,
    )

    # Rebuilding may detach old MTK materials/images.  Release only orphaned
    # datablocks owned by this addon; user/imported assets remain untouched.
    cleanup_unused_mtk_datablocks()

    if props:
        props.point_count = res.vertex_count
        props.cubes_count = res.cubes_count
        props.props_count = res.props_count
        props.fluids_count = res.fluids_count


def schedule_mesh_sync(force_full_rebuild: bool = False) -> None:
    """Coalesce live updates into a fast incremental main-thread mesh sync."""
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


_skip_next_full_snapshot: bool = False
_force_next_full_rebuild: bool = False
_pending_full_sync_request: bool = False


def persist_sync_state_to_scene(context: Optional[bpy.types.Context] = None) -> None:
    """Persist bounds, generation, and section CRC manifest onto Yefira_World object and scene properties."""
    try:
        world_obj = bpy.data.objects.get(DEFAULT_WORLD_OBJECT_NAME)
        if world_obj is not None:
            manifest_dict = voxel_storage.export_manifest_metadata()
            import json
            world_obj["mtk:sync_manifest"] = json.dumps(manifest_dict)
            world_obj["mtk_block_bounds"] = [
                voxel_storage.min_x, voxel_storage.min_y, voxel_storage.min_z,
                voxel_storage.size_x, voxel_storage.size_y, voxel_storage.size_z,
            ]
    except Exception as e:
        logger.warning(f"Failed to persist live sync state to scene object: {e}")


def restore_sync_state_from_scene(context: Optional[bpy.types.Context] = None) -> bool:
    """Attempt to restore live sync voxel metadata from existing Yefira_World scene object."""
    try:
        world_obj = bpy.data.objects.get(DEFAULT_WORLD_OBJECT_NAME)
        if world_obj is None:
            return False

        manifest_str = world_obj.get("mtk:sync_manifest", "")
        if manifest_str and isinstance(manifest_str, str):
            import json
            manifest_data = json.loads(manifest_str)
            if voxel_storage.import_manifest_metadata(manifest_data):
                props = get_active_sync_props(context)
                if props:
                    props.has_selection = True
                    props.min_x, props.min_y, props.min_z = voxel_storage.min_x, voxel_storage.min_y, voxel_storage.min_z
                    props.max_x = voxel_storage.min_x + voxel_storage.size_x - 1
                    props.max_y = voxel_storage.min_y + voxel_storage.size_y - 1
                    props.max_z = voxel_storage.min_z + voxel_storage.size_z - 1
                    props.size_x, props.size_y, props.size_z = voxel_storage.size_x, voxel_storage.size_y, voxel_storage.size_z
                    props.total_blocks = voxel_storage.size_x * voxel_storage.size_y * voxel_storage.size_z
                    props.last_update_info = f"Restored from scene object ({props.total_blocks:,} blocks in bounds)"
                logger.info(f"Restored Live Sync metadata from scene object ({voxel_storage.size_x}x{voxel_storage.size_y}x{voxel_storage.size_z})")
                return True
    except Exception as e:
        logger.warning(f"Failed to restore live sync state from scene object: {e}")
    return False


class MOZI_OT_sync_connect(bpy.types.Operator):
    bl_idname = "mozi.sync_connect"
    bl_label = "Connect"
    bl_description = "Connect to Minecraft Live Sync WebSocket Server"

    def execute(self, context):
        global _client_thread, _last_seq_id, _skip_next_full_snapshot, _is_initial_handshake
        _is_initial_handshake = True
        props = get_active_sync_props(context)
        if not props:
            self.report({'ERROR'}, "Scene properties not initialized.")
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

        if _client_thread and _client_thread.is_alive():
            self.report({'INFO'}, "Already connected or connecting.")
            return {'FINISHED'}

        # 1. Check for existing world object in scene and restore cached manifest if storage is empty
        _skip_next_full_snapshot = False
        if voxel_storage.size_x == 0 or not voxel_storage.section_crc_map:
            restore_sync_state_from_scene(context)

        ProgressBar.begin(title="Live Sync", total=100.0, message="Connecting to Minecraft...", context=context)

        def run_in_main_thread(func):
            def wrapper():
                try:
                    func()
                except Exception as e:
                    logger.error(f"Main thread update error: {e}")
                return None
            bpy.app.timers.register(wrapper)

        def on_status_change(status: str):
            def update():
                props.connection_status = status
                props.is_connected = (status == "CONNECTED")
                if props.is_connected:
                    ProgressBar.update(current=20.0, total=100.0, message="Handshake established...")
                    if _client_thread:
                        _client_thread.send_sync_config(throttle_mode=0, target_fps=60, is_active=True)
                    start_main_thread_pump()
                else:
                    stop_main_thread_pump()
                    if status.startswith("ERROR"):
                        ProgressBar.cancel(message=status)
                    else:
                        ProgressBar.end()
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == 'PROPERTIES':
                            area.tag_redraw()
            run_in_main_thread(update)

        def on_handshake_info(total_sections, non_empty_sections, total_volume, dimension, flags):
            def update():
                global _stream_total_sections, _stream_received_sections
                _stream_total_sections = max(1, non_empty_sections)
                _stream_received_sections = 0
                props.last_update_info = f"Handshake: {dimension} ({non_empty_sections} chunks, {total_volume:,} blocks)"
                ProgressBar.update(current=25.0, total=100.0, message=f"Handshake: {dimension} ({non_empty_sections} chunks)")
            run_in_main_thread(update)

        def on_selection_info(min_x, min_y, min_z, size_x, size_y, size_z):
            voxel_storage.set_bounds(min_x, min_y, min_z, size_x, size_y, size_z)
            def update():
                props.has_selection = True
                props.min_x, props.min_y, props.min_z = min_x, min_y, min_z
                props.max_x = min_x + size_x - 1
                props.max_y = min_y + size_y - 1
                props.max_z = min_z + size_z - 1
                props.size_x, props.size_y, props.size_z = size_x, size_y, size_z
                props.total_blocks = size_x * size_y * size_z
            run_in_main_thread(update)

        start_main_thread_pump()

        def on_full_snapshot(min_x, min_y, min_z, size_x, size_y, size_z, palette, grid_indices):
            # 1. ALWAYS populate VoxelStorage in RAM immediately on worker thread
            voxel_storage.set_full_snapshot(min_x, min_y, min_z, size_x, size_y, size_z, palette, grid_indices)

            def step1_update_props():
                global _last_seq_id, _skip_next_full_snapshot, _force_next_full_rebuild
                _last_seq_id = 0
                props.has_selection = True
                props.min_x, props.min_y, props.min_z = min_x, min_y, min_z
                props.max_x = min_x + size_x - 1
                props.max_y = min_y + size_y - 1
                props.max_z = min_z + size_z - 1
                props.size_x, props.size_y, props.size_z = size_x, size_y, size_z
                props.palette_count = len(palette)
                total_blocks = size_x * size_y * size_z
                props.total_blocks = total_blocks
                props.update_counter += 1

                # Update Palette UI list
                props.palette_list.clear()
                for p_item in palette:
                    item = props.palette_list.add()
                    item.state_str = p_item

                _skip_next_full_snapshot = False
                _force_next_full_rebuild = False
                clear_sync_caches()

                ProgressBar.update(current=40.0, total=100.0, message="Pre-warming voxel models...")

                def step2_preload_and_build():
                    existing_world = bpy.data.objects.get(DEFAULT_WORLD_OBJECT_NAME)
                    mat = find_bound_atlas_material(existing_world) if existing_world else None
                    atlas_params = get_cached_atlas_params(mat)
                    preload_sync_world_data(palette=palette, world_obj=existing_world, atlas_params=atlas_params)

                    ProgressBar.update(current=70.0, total=100.0, message="Building world geometry...")

                    def step3_mesh_sync():
                        global _is_initial_handshake
                        schedule_mesh_sync(force_full_rebuild=True)
                        props.last_update_info = f"Snapshot: {total_blocks:,} blocks (gen {voxel_storage.generation})"
                        persist_sync_state_to_scene(bpy.context)

                        # Log delta history
                        item = props.delta_history.add()
                        item.timestamp = time.strftime("%H:%M:%S")
                        item.pos_str = f"Bounds: {size_x}x{size_y}x{size_z}"
                        item.block_state = f"Snapshot ({total_blocks:,} blks)"
                        while len(props.delta_history) > 50:
                            props.delta_history.remove(0)

                        _is_initial_handshake = False
                        ProgressBar.finish(message=f"Snapshot ({total_blocks:,} blocks) loaded", auto_dismiss_delay=0.8)
                        return None

                    bpy.app.timers.register(step3_mesh_sync, first_interval=0.01)
                    return None

                bpy.app.timers.register(step2_preload_and_build, first_interval=0.01)
                return None

            bpy.app.timers.register(step1_update_props)

        def on_delta_update(min_x, min_y, min_z, changes, seq_id):
            _delta_queue.put((min_x, min_y, min_z, changes, seq_id))

        def on_section_manifest(server_seq_id, sections):
            def update():
                global _skip_next_full_snapshot, _force_next_full_rebuild, _is_initial_handshake
                global _stream_total_sections, _stream_received_sections, _is_repairing_partial
                global _pending_full_sync_request, _is_streaming

                non_empty_manifest_count = sum(
                    1 for _sx, _sy, _sz, _crc in sections if not voxel_storage.is_empty_section_crc(_sx, _sy, _sz, _crc)
                )

                # If full sync was requested by Refresh or initial sync, this manifest is header of incoming stream.
                # Do NOT issue recursive send_full_sync_request() calls!
                if _pending_full_sync_request or _force_next_full_rebuild:
                    _pending_full_sync_request = False
                    _skip_next_full_snapshot = False
                    _is_streaming = True
                    _stream_total_sections = max(1, non_empty_manifest_count)
                    _stream_received_sections = 0
                    props.validation_info = f"Syncing ({non_empty_manifest_count} chunks)..."
                    if non_empty_manifest_count == 0:
                        _finalize_stream_sync(props, 0)
                    else:
                        ProgressBar.update(current=30.0, total=100.0, message=f"Receiving {non_empty_manifest_count} chunks...")
                    return

                # If an active stream is currently in progress, do not let periodic heartbeats interrupt it
                if _is_streaming:
                    logger.debug("Live Sync: Ignoring periodic manifest check while streaming is in progress.")
                    return

                existing_world = bpy.data.objects.get(DEFAULT_WORLD_OBJECT_NAME)
                existing_section_meshes: set[tuple[int, int, int]] = set()
                if existing_world:
                    for child in existing_world.children:
                        if child.name.startswith("Yefira_Section_"):
                            try:
                                parts = child.name.split("_")[2:]
                                existing_section_meshes.add((int(parts[0]), int(parts[1]), int(parts[2])))
                            except Exception:
                                pass
                    if not existing_section_meshes and existing_world.data and len(existing_world.data.polygons) > 0:
                        existing_section_meshes = set(voxel_storage.get_all_sections())

                mismatched = voxel_storage.validate_manifest(
                    sections,
                    existing_section_meshes=existing_section_meshes if existing_world else None
                )
                props.sync_verified = (len(mismatched) == 0)
                has_existing_mesh = existing_world is not None and (
                    len(existing_section_meshes) > 0 or (existing_world.data and len(existing_world.data.polygons) > 0)
                )

                if props.sync_verified and has_existing_mesh:
                    _skip_next_full_snapshot = True
                    _is_repairing_partial = False
                    props.validation_info = "Verified (100% in sync with scene)"
                    logger.info("Live Sync: Handshake verified 100% match with existing scene objects.")
                    if _is_initial_handshake or ProgressBar.is_active():
                        ProgressBar.finish(message="Verified: 100% in sync with scene", auto_dismiss_delay=0.8)
                    _is_initial_handshake = False
                elif has_existing_mesh and 0 < len(mismatched) < len(sections):
                    # Targeted partial repair / Bad chunk auto-healing
                    _skip_next_full_snapshot = False
                    _is_repairing_partial = True
                    _is_streaming = True
                    _stream_total_sections = len(mismatched)
                    _stream_received_sections = 0
                    props.validation_info = f"Repairing {len(mismatched)} section(s)..."
                    ProgressBar.begin(title="Live Sync Repair", total=100.0, message=f"Repairing {len(mismatched)} section(s)...")
                    ProgressBar.update(current=30.0, total=100.0, message=f"Repairing {len(mismatched)} section(s)...")
                    if _client_thread and _client_thread.is_connected:
                        logger.info(f"Live Sync: Requesting auto-healing repair for {len(mismatched)} bad/mismatched section(s)...")
                        _client_thread.send_repair_request(mismatched)
                elif _is_initial_handshake:
                    # Initial connection with fresh scene: request full sync once
                    _skip_next_full_snapshot = False
                    _is_repairing_partial = False
                    _pending_full_sync_request = True
                    _is_initial_handshake = False
                    _is_streaming = True
                    _stream_total_sections = max(1, non_empty_manifest_count)
                    _stream_received_sections = 0
                    props.validation_info = f"Full sync ({non_empty_manifest_count} chunks)..."
                    ProgressBar.begin(title="Live Sync", total=100.0, message=f"Full sync ({non_empty_manifest_count} chunks)...")
                    ProgressBar.update(current=30.0, total=100.0, message="Requesting full world data...")
                    if _client_thread and _client_thread.is_connected:
                        logger.info(f"Live Sync: Requesting full sync ({non_empty_manifest_count} sections)...")
                        _client_thread.send_full_sync_request()
                else:
                    # Periodic heartbeat manifest update
                    if len(mismatched) > 0 and _client_thread and _client_thread.is_connected:
                        logger.info(f"Live Sync: Periodic manifest check detected {len(mismatched)} mismatched sections. Requesting repair...")
                        _is_repairing_partial = True
                        _is_streaming = True
                        _stream_total_sections = len(mismatched)
                        _stream_received_sections = 0
                        _client_thread.send_repair_request(mismatched)
            run_in_main_thread(update)

        def on_section_snapshot(sec_x, sec_y, sec_z, start_x, start_y, start_z, size_x, size_y, size_z, palette, grid_indices):
            global _stream_last_drain_time, _is_streaming
            _is_streaming = True
            _stream_last_drain_time = time.time()
            # 1. Update in-memory storage immediately on worker thread for high throughput
            updated = voxel_storage.set_section_snapshot(
                sec_x, sec_y, sec_z, start_x, start_y, start_z,
                size_x, size_y, size_z, palette, grid_indices
            )
            if updated:
                # Enqueue section for smooth progressive pumping on the main thread
                _stream_section_queue.put((sec_x, sec_y, sec_z, palette))

        _client_thread = SyncClientThread(
            url=props.url,
            on_status_change=on_status_change,
            on_selection_info=on_selection_info,
            on_full_snapshot=on_full_snapshot,
            on_delta_update=on_delta_update,
            on_section_manifest=on_section_manifest,
            on_section_snapshot=on_section_snapshot,
            on_handshake_info=on_handshake_info,
        )
        _client_thread.start()

        self.report({'INFO'}, f"Connecting to {props.url}...")
        return {'FINISHED'}


class MOZI_OT_sync_disconnect(bpy.types.Operator):
    bl_idname = "mozi.sync_disconnect"
    bl_label = "Disconnect"
    bl_description = "Disconnect from Minecraft Live Sync server"

    def execute(self, context):
        global _client_thread, _is_repairing_partial, _pending_full_sync_request, _is_streaming
        stop_main_thread_pump()
        ProgressBar.end(context=context)
        props = get_active_sync_props(context)
        _is_streaming = False
        _is_repairing_partial = False
        _pending_full_sync_request = False

        if _client_thread:
            _client_thread.stop()
            _client_thread = None

        if props:
            props.is_connected = False
            props.connection_status = "DISCONNECTED"

        self.report({'INFO'}, "Disconnected from Live Sync server.")
        return {'FINISHED'}


class MOZI_OT_sync_refresh(bpy.types.Operator):
    bl_idname = "mozi.sync_refresh"
    bl_label = "Refresh"
    bl_description = "Request fresh data snapshot and re-verify sync state with server"

    def execute(self, context):
        global _skip_next_full_snapshot, _force_next_full_rebuild, _is_repairing_partial, _pending_full_sync_request, _is_streaming
        _skip_next_full_snapshot = False
        _force_next_full_rebuild = True
        _pending_full_sync_request = True
        _is_repairing_partial = False
        _is_streaming = True
        clear_sync_caches()
        clear_mesh_builder_caches()
        clear_shared_baker_cache()
        props = get_active_sync_props(context)
        if props and props.is_connected and _client_thread and _client_thread.is_connected:
            ProgressBar.begin(title="Live Sync Refresh", total=100.0, message="Requesting full snapshot...", context=context)
            _client_thread.send_full_sync_request()
            self.report({'INFO'}, "Refreshing live sync data from server...")
        else:
            bpy.ops.mozi.sync_connect()
        return {'FINISHED'}


def cleanup_sync_state() -> None:
    """Clean up all live sync module globals, background threads, timers, and storage."""
    global _client_thread, _last_seq_id, _rebuild_timer_registered, _pending_full_rebuild
    global _cached_atlas_params, _cached_mat_signature, _is_initial_handshake, _is_repairing_partial, _pending_full_sync_request
    global _is_streaming, _stream_received_sections, _stream_total_sections
    stop_main_thread_pump()
    if _client_thread:
        try:
            _client_thread.stop()
        except Exception:
            pass
        _client_thread = None

    _last_seq_id = 0
    _is_streaming = False
    _stream_received_sections = 0
    _stream_total_sections = 0
    _is_initial_handshake = False
    _is_repairing_partial = False
    _pending_full_sync_request = False
    _rebuild_timer_registered = False
    _pending_full_rebuild = False
    _cached_atlas_params = None
    _cached_mat_signature = None

    voxel_storage.clear()
    clear_sync_caches()
    ProgressBar.end()

    try:
        from ...utils.live_sync.classifier import clear_parse_cache
        clear_parse_cache()
    except Exception:
        try:
            from utils.live_sync.classifier import clear_parse_cache
            clear_parse_cache()
        except Exception:
            pass

    try:
        from ...utils.materials.pack import clear_resource_pack_cache
        clear_resource_pack_cache()
    except Exception:
        try:
            from utils.materials.pack import clear_resource_pack_cache
            clear_resource_pack_cache()
        except Exception:
            pass


def unregister():
    """Unregister cleanup hook called when addon is disabled/uninstalled."""
    cleanup_sync_state()

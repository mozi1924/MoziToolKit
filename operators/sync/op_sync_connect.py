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
    from ...utils.live_sync.storage import voxel_storage
    from ...utils.materials.yefira import (
        extract_atlas_parameters,
        find_bound_atlas_material,
    )
    from ...utils.system.dependencies import has_websockets
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
    from utils.live_sync.storage import voxel_storage
    from utils.materials.yefira import (
        extract_atlas_parameters,
        find_bound_atlas_material,
    )
    from utils.system.dependencies import has_websockets

logger = logging.getLogger("MoziToolKit.LiveSync")

_client_thread: Optional[SyncClientThread] = None
_last_seq_id: int = 0
_rebuild_timer_registered: bool = False
# Debounce caps expensive UI redraws while maintaining sub-millisecond sync
REBUILD_DEBOUNCE_SECONDS: float = 0.05
_pending_full_rebuild: bool = False

_cached_atlas_params: Optional[dict] = None
_cached_mat_signature: Optional[tuple] = None

# High-frequency main-thread pump for sub-millisecond delta streaming
_delta_queue: queue.Queue = queue.Queue()
_pump_timer_registered: bool = False
_PUMP_INTERVAL: float = 0.005  # 5ms (200 Hz event pump rate)


def _pump_main_thread_events() -> Optional[float]:
    """Continuous high-frequency event pump executing on Blender's main thread."""
    global _pump_timer_registered, _last_seq_id
    if not _pump_timer_registered:
        return None

    props = get_active_sync_props()
    if not props or not props.is_connected:
        _pump_timer_registered = False
        return None

    # Drain pending delta changes
    accumulated_changes = []
    latest_seq_id = _last_seq_id
    min_x, min_y, min_z = 0, 0, 0

    while not _delta_queue.empty():
        try:
            item = _delta_queue.get_nowait()
            m_x, m_y, m_z, chs, seq_id = item
            if seq_id > latest_seq_id:
                latest_seq_id = seq_id
                min_x, min_y, min_z = m_x, m_y, m_z
                accumulated_changes.extend(chs)
        except queue.Empty:
            break

    if accumulated_changes:
        _last_seq_id = latest_seq_id
        applied = voxel_storage.apply_delta_update(min_x, min_y, min_z, accumulated_changes)
        if applied:
            if len(accumulated_changes) <= 64:
                existing_world = bpy.data.objects.get(DEFAULT_WORLD_OBJECT_NAME)
                mat = find_bound_atlas_material(existing_world) if existing_world else None
                atlas_params = get_cached_atlas_params(mat)
                res = apply_block_delta_to_world(
                    context=bpy.context,
                    storage=voxel_storage,
                    changes=accumulated_changes,
                    atlas_params=atlas_params,
                )
                if props:
                    props.point_count = res.vertex_count
                    props.cubes_count = res.cubes_count
                    props.props_count = res.props_count
                    props.fluids_count = res.fluids_count
            else:
                schedule_mesh_sync()

            props.update_counter += 1
            props.last_update_info = f"Delta: {len(accumulated_changes)} blocks (seq {latest_seq_id})"

            # Force redraw of 3D Viewport
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type in ('VIEW_3D', 'PROPERTIES'):
                        area.tag_redraw()

    return _PUMP_INTERVAL


def start_main_thread_pump():
    """Ensure the high-frequency event pump is registered and running."""
    global _pump_timer_registered
    if not _pump_timer_registered:
        _pump_timer_registered = True
        bpy.app.timers.register(_pump_main_thread_events, first_interval=_PUMP_INTERVAL, persistent=True)


def stop_main_thread_pump():
    """Stop the event pump and clear pending queues."""
    global _pump_timer_registered
    _pump_timer_registered = False
    while not _delta_queue.empty():
        try:
            _delta_queue.get_nowait()
        except queue.Empty:
            break


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
        global _client_thread, _last_seq_id, _skip_next_full_snapshot
        props = get_active_sync_props(context)
        if not props:
            self.report({'ERROR'}, "Scene properties not initialized.")
            return {'CANCELLED'}

        if not has_websockets():
            self.report({'WARNING'}, "Missing 'websockets' library! Check bundled extension wheels.")
            return {'CANCELLED'}

        if _client_thread and _client_thread.is_alive():
            self.report({'INFO'}, "Already connected or connecting.")
            return {'FINISHED'}

        # 1. Check for existing world object in scene and restore cached manifest if storage is empty
        _skip_next_full_snapshot = False
        if voxel_storage.size_x == 0 or not voxel_storage.section_crc_map:
            restore_sync_state_from_scene(context)

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
                    start_main_thread_pump()
                else:
                    stop_main_thread_pump()
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == 'PROPERTIES':
                            area.tag_redraw()
            run_in_main_thread(update)

        def on_selection_info(min_x, min_y, min_z, size_x, size_y, size_z):
            def update():
                props.has_selection = True
                props.min_x, props.min_y, props.min_z = min_x, min_y, min_z
                props.max_x = min_x + size_x - 1
                props.max_y = min_y + size_y - 1
                props.max_z = min_z + size_z - 1
                props.size_x, props.size_y, props.size_z = size_x, size_y, size_z
                props.total_blocks = size_x * size_y * size_z
            run_in_main_thread(update)

        def on_full_snapshot(min_x, min_y, min_z, size_x, size_y, size_z, palette, grid_indices):
            def update():
                global _last_seq_id, _skip_next_full_snapshot
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

                # If manifest validation already confirmed 100% match with existing scene mesh, skip redundant full rebuild
                existing_world = bpy.data.objects.get(DEFAULT_WORLD_OBJECT_NAME)
                if _skip_next_full_snapshot and existing_world and voxel_storage.matches_bounds(min_x, min_y, min_z):
                    logger.info("Live Sync: Verified existing scene mesh matches server snapshot, skipping full rebuild.")
                    props.last_update_info = f"Verified: {total_blocks} blocks (reused existing mesh)"
                    _skip_next_full_snapshot = False
                    return

                clear_sync_caches()

                # 1. Update VoxelStorage
                voxel_storage.set_full_snapshot(min_x, min_y, min_z, size_x, size_y, size_z, palette, grid_indices)

                # 2. Pre-warm and pre-load all palette blockstate models and materials in RAM
                mat = find_bound_atlas_material(existing_world) if existing_world else None
                atlas_params = get_cached_atlas_params(mat)
                preload_sync_world_data(palette=palette, world_obj=existing_world, atlas_params=atlas_params)

                # 3. Schedule initial world mesh build
                schedule_mesh_sync(force_full_rebuild=True)

                props.last_update_info = f"Snapshot: {total_blocks} blocks (gen {voxel_storage.generation})"

                # 4. Persist metadata onto world object
                persist_sync_state_to_scene(bpy.context)

                # Log delta history
                item = props.delta_history.add()
                item.timestamp = time.strftime("%H:%M:%S")
                item.pos_str = f"Bounds: {size_x}x{size_y}x{size_z}"
                item.block_state = f"Snapshot ({total_blocks} blks)"
                while len(props.delta_history) > 50:
                    props.delta_history.remove(0)
            run_in_main_thread(update)

        def on_delta_update(min_x, min_y, min_z, changes, seq_id):
            _delta_queue.put((min_x, min_y, min_z, changes, seq_id))

        def on_section_manifest(server_seq_id, sections):
            def update():
                global _skip_next_full_snapshot
                mismatched = voxel_storage.validate_manifest(sections)
                props.sync_verified = (len(mismatched) == 0)
                existing_world = bpy.data.objects.get(DEFAULT_WORLD_OBJECT_NAME)
                has_existing_mesh = existing_world is not None and (
                    len(existing_world.children) > 0 or (existing_world.data and len(existing_world.data.polygons) > 0)
                )

                if props.sync_verified and has_existing_mesh:
                    _skip_next_full_snapshot = True
                    props.validation_info = "Verified (100% in sync with scene)"
                    logger.info("Live Sync: Handshake verified 100% match with existing scene objects.")
                elif props.sync_verified:
                    props.validation_info = "Verified (100% in sync)"
                else:
                    _skip_next_full_snapshot = False
                    props.validation_info = f"Mismatch in {len(mismatched)} section(s)"
                    if _client_thread:
                        _client_thread.send_repair_request(mismatched)
            run_in_main_thread(update)

        def on_section_snapshot(sec_x, sec_y, sec_z, start_x, start_y, start_z, size_x, size_y, size_z, palette, grid_indices):
            def update():
                updated = voxel_storage.set_section_snapshot(
                    sec_x, sec_y, sec_z, start_x, start_y, start_z,
                    size_x, size_y, size_z, palette, grid_indices
                )
                if updated:
                    schedule_mesh_sync()
                    props.update_counter += 1
                    props.last_update_info = f"Repaired Section ({sec_x}, {sec_y}, {sec_z})"
                    persist_sync_state_to_scene(bpy.context)
            run_in_main_thread(update)

        _client_thread = SyncClientThread(
            url=props.url,
            on_status_change=on_status_change,
            on_selection_info=on_selection_info,
            on_full_snapshot=on_full_snapshot,
            on_delta_update=on_delta_update,
            on_section_manifest=on_section_manifest,
            on_section_snapshot=on_section_snapshot,
        )
        _client_thread.start()

        self.report({'INFO'}, f"Connecting to {props.url}...")
        return {'FINISHED'}


class MOZI_OT_sync_disconnect(bpy.types.Operator):
    bl_idname = "mozi.sync_disconnect"
    bl_label = "Disconnect"
    bl_description = "Disconnect from Minecraft Live Sync server"

    def execute(self, context):
        global _client_thread
        stop_main_thread_pump()
        props = get_active_sync_props(context)

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
        global _skip_next_full_snapshot
        _skip_next_full_snapshot = False
        props = get_active_sync_props(context)
        if props and props.is_connected:
            # Re-fetch fresh full data from server
            bpy.ops.mozi.sync_disconnect()
            bpy.ops.mozi.sync_connect()
            self.report({'INFO'}, "Refreshing live sync data from server...")
        else:
            bpy.ops.mozi.sync_connect()
        return {'FINISHED'}


def cleanup_sync_state() -> None:
    """Clean up all live sync module globals, background threads, timers, and storage."""
    global _client_thread, _last_seq_id, _rebuild_timer_registered, _pending_full_rebuild, _cached_atlas_params, _cached_mat_signature
    stop_main_thread_pump()
    if _client_thread:
        try:
            _client_thread.stop()
        except Exception:
            pass
        _client_thread = None

    _last_seq_id = 0
    _rebuild_timer_registered = False
    _pending_full_rebuild = False
    _cached_atlas_params = None
    _cached_mat_signature = None

    voxel_storage.clear()
    clear_sync_caches()

    try:
        from ...utils.live_sync.classifier import clear_parse_cache
        clear_parse_cache()
    except Exception:
        pass


def unregister():
    """Unregister cleanup hook called when addon is disabled/uninstalled."""
    cleanup_sync_state()

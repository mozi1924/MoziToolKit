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
    from utils.materials.pipeline.session import cleanup_unused_mtk_datablocks
    from utils.materials.yefira import (
        extract_atlas_parameters,
        find_bound_atlas_material,
    )
    from utils.system.dependencies import has_websockets
    from pipeline.progress import ProgressBar

logger = logging.getLogger("MoziToolKit.LiveSync")

REBUILD_DEBOUNCE_SECONDS: float = 0.05
_PUMP_INTERVAL_ACTIVE: float = 0.015  # 15ms (~66 Hz when processing active deltas/chunks)
_PUMP_INTERVAL_IDLE: float = 0.035    # 35ms (~28 Hz idle throttle to save CPU)
_SETTLE_TIMEOUT_SECONDS: float = 3.0

_pump_timer_registered: bool = False


class SyncSession:
    """Manages the connection, storage, event queues, and build state for a specific world container."""

    def __init__(self, target_object_name: str, url: str = "ws://localhost:8765"):
        self.target_object_name: str = target_object_name
        self.url: str = url
        # Use dedicated VoxelStorage per container session
        self.storage: VoxelStorage = VoxelStorage()
        self.client_thread: Optional[SyncClientThread] = None

        self.delta_queue: queue.Queue = queue.Queue()
        self.stream_section_queue: queue.Queue = queue.Queue()
        self.accumulated_stream_palettes: Set[str] = set()

        self.last_seq_id: int = 0
        self.stream_total_sections: int = 0
        self.stream_received_sections: int = 0
        self.stream_last_drain_time: float = 0.0

        self.is_streaming: bool = False
        self.is_initial_handshake: bool = True
        self.is_repairing_partial: bool = False
        self.pending_full_sync_request: bool = False
        self.force_next_full_rebuild: bool = False
        self.skip_next_full_snapshot: bool = False

        self.rebuild_timer_registered: bool = False
        self.pending_full_rebuild: bool = False

        self.cached_atlas_params: Optional[dict] = None
        self.cached_mat_signature: Optional[tuple] = None

    def clear_caches(self) -> None:
        self.cached_atlas_params = None
        self.cached_mat_signature = None
        clear_mesh_builder_caches()
        clear_shared_baker_cache()

    def get_cached_atlas_params(self, mat: Optional[bpy.types.Material]) -> dict:
        try:
            from ...utils.materials.pack import get_configured_pack_stack
            from ...utils.materials.pipeline.provenance import get_effective_pack_hash, is_material_hash_valid
        except (ImportError, ValueError):
            from utils.materials.pack import get_configured_pack_stack
            from utils.materials.pipeline.provenance import get_effective_pack_hash, is_material_hash_valid

        pack_stack = None
        stack_hash = ""
        try:
            pack_stack = get_configured_pack_stack()
            stack_hash = get_effective_pack_hash(pack_stack)
        except Exception:
            pass

        if mat and stack_hash and not is_material_hash_valid(mat, stack_hash):
            mat = None

        if mat:
            mapping = mat.get("mtk:atlas_mapping", mat.get("mtk_atlas_mapping", ""))
            current_signature = (
                mat.as_pointer() if hasattr(mat, "as_pointer") else id(mat),
                mapping,
                get_effective_pack_hash(mat),
                stack_hash,
            )
        else:
            current_signature = (0, "", "", stack_hash)

        if self.cached_atlas_params is None or self.cached_mat_signature != current_signature:
            self.cached_mat_signature = current_signature
            self.cached_atlas_params = extract_atlas_parameters(mat, pack_stack=pack_stack)
            clear_mesh_builder_caches()
        return self.cached_atlas_params

    def schedule_mesh_sync(self, force_full_rebuild: bool = False) -> None:
        self.pending_full_rebuild = self.pending_full_rebuild or force_full_rebuild
        if self.rebuild_timer_registered:
            return

        self.rebuild_timer_registered = True

        def flush():
            try:
                if self.storage.size_x and self.storage.size_y and self.storage.size_z:
                    full_rebuild = self.pending_full_rebuild
                    self.pending_full_rebuild = False
                    target_obj = bpy.data.objects.get(self.target_object_name)
                    if target_obj:
                        trigger_mesh_sync(bpy.context, force_full_rebuild=full_rebuild, target_obj=target_obj, storage=self.storage)
                        for window in bpy.context.window_manager.windows:
                            for area in window.screen.areas:
                                if area.type in ('VIEW_3D', 'PROPERTIES'):
                                    area.tag_redraw()
            except Exception as e:
                logger.error(f"Deferred mesh sync error for {self.target_object_name}: {e}", exc_info=True)
            finally:
                self.rebuild_timer_registered = False
            return None

        bpy.app.timers.register(flush, first_interval=REBUILD_DEBOUNCE_SECONDS)

    def persist_sync_state_to_scene(self, target_obj: Optional[bpy.types.Object] = None) -> None:
        try:
            obj = target_obj or bpy.data.objects.get(self.target_object_name)
            if obj is not None:
                manifest_dict = self.storage.export_manifest_metadata()
                import json
                obj["mtk:sync_manifest"] = json.dumps(manifest_dict)
                obj["mtk_block_bounds"] = [
                    self.storage.min_x, self.storage.min_y, self.storage.min_z,
                    self.storage.size_x, self.storage.size_y, self.storage.size_z,
                ]
        except Exception as e:
            logger.warning(f"Failed to persist live sync state to {self.target_object_name}: {e}")

    def restore_sync_state_from_scene(self, target_obj: Optional[bpy.types.Object] = None) -> bool:
        try:
            obj = target_obj or bpy.data.objects.get(self.target_object_name)
            if obj is None:
                return False

            manifest_str = obj.get("mtk:sync_manifest", "")
            if manifest_str and isinstance(manifest_str, str):
                import json
                manifest_data = json.loads(manifest_str)
                if self.storage.import_manifest_metadata(manifest_data):
                    props = get_active_sync_props(bpy.context, target_obj=obj)
                    if props:
                        props.has_selection = True
                        props.min_x, props.min_y, props.min_z = self.storage.min_x, self.storage.min_y, self.storage.min_z
                        props.max_x = self.storage.min_x + self.storage.size_x - 1
                        props.max_y = self.storage.min_y + self.storage.size_y - 1
                        props.max_z = self.storage.min_z + self.storage.size_z - 1
                        props.size_x, props.size_y, props.size_z = self.storage.size_x, self.storage.size_y, self.storage.size_z
                        props.total_blocks = self.storage.size_x * self.storage.size_y * self.storage.size_z
                        props.last_update_info = f"Restored from scene object ({props.total_blocks:,} blocks in bounds)"
                    logger.info(f"Restored Live Sync metadata for {self.target_object_name} ({self.storage.size_x}x{self.storage.size_y}x{self.storage.size_z})")
                    return True
        except Exception as e:
            logger.warning(f"Failed to restore live sync state from {self.target_object_name}: {e}")
        return False

    def stop(self) -> None:
        if self.client_thread:
            try:
                self.client_thread.stop()
            except Exception:
                pass
            self.client_thread = None
        self.is_streaming = False
        self.is_repairing_partial = False
        self.pending_full_sync_request = False
        self.rebuild_timer_registered = False
        self.pending_full_rebuild = False
        while not self.delta_queue.empty():
            try:
                self.delta_queue.get_nowait()
            except queue.Empty:
                break
        while not self.stream_section_queue.empty():
            try:
                self.stream_section_queue.get_nowait()
            except queue.Empty:
                break
        self.accumulated_stream_palettes.clear()


class SyncSessionManager:
    """Manages all active sync sessions keyed by container object name."""

    def __init__(self):
        self._sessions: Dict[str, SyncSession] = {}

    def get_session(self, obj_name: str) -> Optional[SyncSession]:
        return self._sessions.get(obj_name)

    def get_or_create_session(self, obj_name: str, url: str = "ws://localhost:8765") -> SyncSession:
        if obj_name not in self._sessions:
            session = SyncSession(target_object_name=obj_name, url=url)
            self._sessions[obj_name] = session
        else:
            session = self._sessions[obj_name]
            if url:
                session.url = url
        return session

    def remove_session(self, obj_name: str) -> None:
        if obj_name in self._sessions:
            session = self._sessions.pop(obj_name)
            session.stop()

    def get_all_sessions(self) -> List[SyncSession]:
        return list(self._sessions.values())

    def clear_all(self) -> None:
        for session in list(self._sessions.values()):
            session.stop()
        self._sessions.clear()


_session_manager = SyncSessionManager()


def get_active_session_manager() -> SyncSessionManager:
    return _session_manager


# Backward compatibility properties & global references
_client_thread: Optional[SyncClientThread] = None
_last_seq_id: int = 0
_stream_total_sections: int = 0
_stream_received_sections: int = 0
_is_streaming: bool = False
_is_initial_handshake: bool = False
_rebuild_timer_registered: bool = False
_pending_full_rebuild: bool = False
_cached_atlas_params: Optional[dict] = None
_cached_mat_signature: Optional[tuple] = None
_is_repairing_partial: bool = False
_delta_queue: queue.Queue = queue.Queue()
_stream_section_queue: queue.Queue = queue.Queue()
_accumulated_stream_palettes: Set[str] = set()


def get_active_sync_props(context: Optional[bpy.types.Context] = None, target_obj: Optional[bpy.types.Object] = None):
    """Retrieve mozi_sync properties safely, preferring the container object's properties."""
    ctx = context or (bpy.context if hasattr(bpy, "context") else None)

    # 1. If target_obj is explicitly provided
    if target_obj is not None:
        root = resolve_world_root_object(target_obj) or target_obj
        if hasattr(root, "mozi_sync"):
            return root.mozi_sync

    # 2. Check context active / selected object
    active_obj = getattr(ctx, "active_object", None) if ctx else None
    if active_obj is not None:
        root = resolve_world_root_object(active_obj) or active_obj
        if hasattr(root, "mozi_sync") and (is_yefira_object(active_obj) or root.get("mtk:is_yefira_world")):
            return root.mozi_sync

    # 3. Fallback to Scene mozi_sync
    if ctx and hasattr(ctx, "scene") and hasattr(ctx.scene, "mozi_sync"):
        return ctx.scene.mozi_sync
    if hasattr(bpy, "context") and hasattr(bpy.context, "scene") and hasattr(bpy.context.scene, "mozi_sync"):
        return bpy.context.scene.mozi_sync
    return None


def get_target_world_object(context: Optional[bpy.types.Context] = None, obj_name: Optional[str] = None) -> Optional[bpy.types.Object]:
    """Retrieve the target Yefira World container object for a session or active context."""
    if obj_name and obj_name in bpy.data.objects:
        obj = bpy.data.objects[obj_name]
        return resolve_world_root_object(obj) or obj

    ctx = context or (bpy.context if hasattr(bpy, "context") else None)
    active_obj = getattr(ctx, "active_object", None) if ctx else None
    if active_obj:
        root = resolve_world_root_object(active_obj)
        if root:
            return root

    if ctx and hasattr(ctx, "selected_objects"):
        for sel in ctx.selected_objects:
            root = resolve_world_root_object(sel)
            if root:
                return root

    world_obj = bpy.data.objects.get(DEFAULT_WORLD_OBJECT_NAME)
    if world_obj is not None:
        return resolve_world_root_object(world_obj) or world_obj

    for obj in bpy.data.objects:
        if is_yefira_root_object(obj):
            return obj
    return None


def get_current_world_object(context: Optional[bpy.types.Context] = None) -> Optional[bpy.types.Object]:
    """Retrieve the currently active or existing Yefira World container object."""
    return get_target_world_object(context)


def get_cached_atlas_params(mat: Optional[bpy.types.Material]) -> dict:
    """Retrieve atlas parameters authoritatively, invalidating when material or pack stack changes."""
    global _cached_atlas_params, _cached_mat_signature
    try:
        from ...utils.materials.pack import get_configured_pack_stack
        from ...utils.materials.pipeline.provenance import get_effective_pack_hash, is_material_hash_valid
    except (ImportError, ValueError):
        from utils.materials.pack import get_configured_pack_stack
        from utils.materials.pipeline.provenance import get_effective_pack_hash, is_material_hash_valid

    pack_stack = None
    stack_hash = ""
    try:
        pack_stack = get_configured_pack_stack()
        stack_hash = get_effective_pack_hash(pack_stack)
    except Exception:
        pass

    if mat and stack_hash and not is_material_hash_valid(mat, stack_hash):
        mat = None

    if mat:
        mapping = mat.get("mtk:atlas_mapping", mat.get("mtk_atlas_mapping", ""))
        current_signature = (
            mat.as_pointer() if hasattr(mat, "as_pointer") else id(mat),
            mapping,
            get_effective_pack_hash(mat),
            stack_hash,
        )
    else:
        current_signature = (0, "", "", stack_hash)

    if _cached_atlas_params is None or _cached_mat_signature != current_signature:
        _cached_mat_signature = current_signature
        _cached_atlas_params = extract_atlas_parameters(mat, pack_stack=pack_stack)
        clear_mesh_builder_caches()
    return _cached_atlas_params


def clear_sync_caches() -> None:
    """Invalidate atlas parameter cache, mesh builder caches, and baker caches on material or world reset."""
    global _cached_atlas_params, _cached_mat_signature
    _cached_atlas_params = None
    _cached_mat_signature = None
    clear_mesh_builder_caches()
    clear_shared_baker_cache()
    for s in _session_manager.get_all_sessions():
        s.clear_caches()


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
        sess = _session_manager.get_session(target_obj.name)
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

    cleanup_unused_mtk_datablocks()

    if props:
        props.point_count = res.vertex_count
        props.cubes_count = res.cubes_count
        props.props_count = res.props_count
        props.fluids_count = res.fluids_count


def schedule_mesh_sync(force_full_rebuild: bool = False, target_obj: Optional[bpy.types.Object] = None) -> None:
    """Coalesce live updates into a fast incremental main-thread mesh sync."""
    target = target_obj or get_target_world_object()
    if target:
        sess = _session_manager.get_session(target.name)
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


def persist_sync_state_to_scene(context: Optional[bpy.types.Context] = None, target_obj: Optional[bpy.types.Object] = None) -> None:
    """Persist bounds, generation, and section CRC manifest onto target world object."""
    try:
        world_obj = target_obj or get_target_world_object(context)
        if world_obj is not None:
            sess = _session_manager.get_session(world_obj.name)
            storage = sess.storage if sess else voxel_storage
            manifest_dict = storage.export_manifest_metadata()
            import json
            world_obj["mtk:sync_manifest"] = json.dumps(manifest_dict)
            world_obj["mtk_block_bounds"] = [
                storage.min_x, storage.min_y, storage.min_z,
                storage.size_x, storage.size_y, storage.size_z,
            ]
    except Exception as e:
        logger.warning(f"Failed to persist live sync state to scene object: {e}")


def restore_sync_state_from_scene(context: Optional[bpy.types.Context] = None, target_obj: Optional[bpy.types.Object] = None) -> bool:
    """Attempt to restore live sync voxel metadata from existing scene object."""
    try:
        world_obj = target_obj or get_target_world_object(context)
        if world_obj is None:
            return False

        sess = _session_manager.get_session(world_obj.name)
        storage = sess.storage if sess else voxel_storage

        manifest_str = world_obj.get("mtk:sync_manifest", "")
        if manifest_str and isinstance(manifest_str, str):
            import json
            manifest_data = json.loads(manifest_str)
            if storage.import_manifest_metadata(manifest_data):
                props = get_active_sync_props(context, target_obj=world_obj)
                if props:
                    props.has_selection = True
                    props.min_x, props.min_y, props.min_z = storage.min_x, storage.min_y, storage.min_z
                    props.max_x = storage.min_x + storage.size_x - 1
                    props.max_y = storage.min_y + storage.size_y - 1
                    props.max_z = storage.min_z + storage.size_z - 1
                    props.size_x, props.size_y, props.size_z = storage.size_x, storage.size_y, storage.size_z
                    props.total_blocks = storage.size_x * storage.size_y * storage.size_z
                    props.last_update_info = f"Restored from scene object ({props.total_blocks:,} blocks in bounds)"
                logger.info(f"Restored Live Sync metadata for {world_obj.name} ({storage.size_x}x{storage.size_y}x{storage.size_z})")
                return True
    except Exception as e:
        logger.warning(f"Failed to restore live sync state from scene object: {e}")
    return False


def _finalize_stream_sync(session: SyncSession, props: Any, target_obj: bpy.types.Object, total_target: int) -> None:
    """Finalize world mesh build for a session, clean up stream flags, and dismiss progress bar."""
    try:
        cur_mat = find_bound_atlas_material(target_obj) if target_obj else None
        cur_atlas_params = session.get_cached_atlas_params(cur_mat)
        target_palette = session.accumulated_stream_palettes if session.accumulated_stream_palettes else session.storage.get_unique_states()
        if target_palette:
            preload_sync_world_data(palette=target_palette, world_obj=target_obj, atlas_params=cur_atlas_params)
            session.accumulated_stream_palettes.clear()

        rebuild_full = not session.is_repairing_partial
        session.schedule_mesh_sync(force_full_rebuild=rebuild_full)
        session.persist_sync_state_to_scene(target_obj)

        if props:
            props.update_counter += 1
            props.last_update_info = f"Repaired {total_target} sections" if session.is_repairing_partial else f"Streamed {total_target} sections"
            props.sync_verified = True
            props.validation_info = "Verified (100% in sync)"
    except Exception as e:
        logger.error(f"Finalize stream sync error for {session.target_object_name}: {e}", exc_info=True)
        if props:
            props.validation_info = f"Finalize error: {e}"
    finally:
        session.is_streaming = False
        session.is_repairing_partial = False
        session.is_initial_handshake = False
        session.force_next_full_rebuild = False
        session.pending_full_sync_request = False
        session.stream_received_sections = 0
        session.stream_total_sections = 0
        ProgressBar.finish(message=f"Sync Ready ({total_target} chunks processed)", auto_dismiss_delay=0.8)


def _pump_main_thread_events() -> Optional[float]:
    """Continuous adaptive event pump executing on Blender's main thread across all sessions."""
    global _pump_timer_registered, _last_seq_id, _stream_received_sections, _stream_total_sections
    global _is_repairing_partial, _stream_last_drain_time, _is_streaming
    if not _pump_timer_registered:
        return None

    sessions = _session_manager.get_all_sessions()
    has_active_work = False
    any_connected = False

    # 1. Pump active sessions in SessionManager
    for session in sessions:
        target_obj = bpy.data.objects.get(session.target_object_name)
        if target_obj is None:
            continue

        props = getattr(target_obj, "mozi_sync", None) or getattr(bpy.context.scene, "mozi_sync", None)
        if session.client_thread and session.client_thread.is_connected:
            any_connected = True

        # Guard: Force back to Object Mode if Edit Mode is attempted
        if props and props.is_connected:
            active_obj = getattr(bpy.context, "active_object", None)
            if bpy.context.mode == 'EDIT_MESH' or (active_obj and getattr(active_obj, "mode", None) == 'EDIT'):
                try:
                    bpy.ops.object.mode_set(mode='OBJECT')
                    msg = bpy.app.translations.pgettext_iface("Edit Mode is not supported during Live Sync. Switched to Object Mode.")
                    props.validation_info = msg
                    props.last_update_info = msg
                except Exception:
                    pass

        # 1. Drain pending streamed section snapshots (batch up to 16 chunks per tick)
        sections_drained = 0
        while not session.stream_section_queue.empty() and sections_drained < 16:
            try:
                item = session.stream_section_queue.get_nowait()
                sec_x, sec_y, sec_z, palette = item
                session.stream_received_sections += 1
                if palette:
                    session.accumulated_stream_palettes.update(palette)
                sections_drained += 1
                has_active_work = True
            except queue.Empty:
                break

        if sections_drained > 0:
            session.stream_last_drain_time = time.time()
            total_target = max(1, session.stream_total_sections)
            frac = min(1.0, session.stream_received_sections / total_target)
            pct = int(30.0 + frac * 70.0)

            if session.stream_received_sections >= total_target and session.stream_section_queue.empty():
                _finalize_stream_sync(session, props, target_obj, total_target)
            else:
                ProgressBar.update(current=pct, total=100.0, message=f"Streaming chunk ({session.stream_received_sections}/{total_target})")

            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type in ('STATUSBAR', 'VIEW_3D', 'PROPERTIES'):
                        area.tag_redraw()
        elif session.is_streaming and session.stream_received_sections > 0 and session.stream_section_queue.empty() and ProgressBar.is_active():
            if session.stream_last_drain_time > 0 and (time.time() - session.stream_last_drain_time > _SETTLE_TIMEOUT_SECONDS):
                logger.info("Live Sync: Stream settle timeout reached for %s (%s sections processed). Finalizing.", session.target_object_name, session.stream_received_sections)
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

                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type in ('VIEW_3D', 'PROPERTIES'):
                            area.tag_redraw()

    # 2. Pump global fallback queues for direct/unit-test backward compatibility
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


class MOZI_OT_sync_connect(bpy.types.Operator):
    bl_idname = "mozi.sync_connect"
    bl_label = "Connect"
    bl_description = "Connect to Minecraft Live Sync WebSocket Server"

    target_container: bpy.props.StringProperty(name="Target Container", default="")

    def execute(self, context):
        global _client_thread
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

                        cur_props.palette_list.clear()
                        for p_item in palette:
                            item = cur_props.palette_list.add()
                            item.state_str = p_item

                    session.skip_next_full_snapshot = False
                    session.force_next_full_rebuild = False
                    session.clear_caches()

                    ProgressBar.update(current=40.0, total=100.0, message="Pre-warming voxel models...")

                    def step2_preload_and_build():
                        try:
                            world_obj = bpy.data.objects.get(session.target_object_name)
                            cur_mat = find_bound_atlas_material(world_obj) if world_obj else None
                            cur_atlas_params = session.get_cached_atlas_params(cur_mat)
                            preload_sync_world_data(palette=palette, world_obj=world_obj, atlas_params=cur_atlas_params)

                            ProgressBar.update(current=70.0, total=100.0, message="Building world geometry...")

                            def step3_mesh_sync():
                                try:
                                    world_obj_inner = bpy.data.objects.get(session.target_object_name)
                                    session.schedule_mesh_sync(force_full_rebuild=True)
                                    total_blks = size_x * size_y * size_z
                                    inner_props = get_active_sync_props(bpy.context, target_obj=world_obj_inner)
                                    if inner_props:
                                        inner_props.last_update_info = f"Snapshot: {total_blks:,} blocks (gen {session.storage.generation})"
                                        item = inner_props.delta_history.add()
                                        item.timestamp = time.strftime("%H:%M:%S")
                                        item.pos_str = f"Bounds: {size_x}x{size_y}x{size_z}"
                                        item.block_state = f"Snapshot ({total_blks:,} blks)"
                                        while len(inner_props.delta_history) > 50:
                                            inner_props.delta_history.remove(0)

                                    session.persist_sync_state_to_scene(world_obj_inner)
                                    session.is_initial_handshake = False
                                    ProgressBar.finish(message=f"Snapshot ({total_blks:,} blocks) loaded", auto_dismiss_delay=0.8)
                                except Exception as e:
                                    logger.error(f"Live Sync step3_mesh_sync error: {e}", exc_info=True)
                                    ProgressBar.cancel(message=f"Mesh build error: {e}")
                                    if cur_props:
                                        cur_props.validation_info = f"Error: {e}"
                                return None

                            bpy.app.timers.register(step3_mesh_sync, first_interval=0.01)
                        except Exception as e:
                            logger.error(f"Live Sync step2_preload_and_build error: {e}", exc_info=True)
                            ProgressBar.cancel(message=f"Preload error: {e}")
                            if cur_props:
                                cur_props.validation_info = f"Error: {e}"
                        return None

                    bpy.app.timers.register(step2_preload_and_build, first_interval=0.01)
                except Exception as e:
                    logger.error(f"Live Sync step1_update_props error: {e}", exc_info=True)
                    ProgressBar.cancel(message=f"Snapshot error: {e}")
                    if cur_props:
                        cur_props.validation_info = f"Error: {e}"
                return None

            bpy.app.timers.register(step1_update_props)

        def on_delta_update(min_x, min_y, min_z, changes, seq_id):
            session.delta_queue.put((min_x, min_y, min_z, changes, seq_id))

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
                            ProgressBar.update(current=30.0, total=100.0, message=f"Receiving {non_empty_manifest_count} chunks...")
                        return

                    if session.is_streaming:
                        logger.debug("Live Sync: Ignoring periodic manifest check while streaming is in progress.")
                        return

                    existing_section_meshes: set[tuple[int, int, int]] = set()
                    if cur_obj:
                        sections_map = find_root_section_children(cur_obj)
                        existing_section_meshes = set(sections_map.keys())
                        if not existing_section_meshes and cur_obj.data and len(cur_obj.data.polygons) > 0:
                            existing_section_meshes = set(session.storage.get_all_sections())

                    mismatched = session.storage.validate_manifest(
                        sections,
                        existing_section_meshes=existing_section_meshes if cur_obj else None
                    )
                    if cur_props:
                        cur_props.sync_verified = (len(mismatched) == 0)
                    has_existing_mesh = cur_obj is not None and (
                        len(existing_section_meshes) > 0 or (cur_obj.data and len(cur_obj.data.polygons) > 0)
                    )

                    if cur_props and cur_props.sync_verified and has_existing_mesh:
                        session.skip_next_full_snapshot = True
                        session.is_repairing_partial = False
                        cur_props.validation_info = "Verified (100% in sync with scene)"
                        logger.info(f"Live Sync ({session.target_object_name}): Handshake verified 100% match with scene.")
                        if session.is_initial_handshake or ProgressBar.is_active():
                            ProgressBar.finish(message="Verified: 100% in sync with scene", auto_dismiss_delay=0.8)
                        session.is_initial_handshake = False
                    elif has_existing_mesh and 0 < len(mismatched) < len(sections):
                        session.skip_next_full_snapshot = False
                        session.is_repairing_partial = True
                        session.is_streaming = True
                        session.stream_total_sections = len(mismatched)
                        session.stream_received_sections = 0
                        if cur_props:
                            cur_props.validation_info = f"Repairing {len(mismatched)} section(s)..."
                        ProgressBar.begin(title=f"Live Sync Repair ({session.target_object_name})", total=100.0, message=f"Repairing {len(mismatched)} section(s)...")
                        ProgressBar.update(current=30.0, total=100.0, message=f"Repairing {len(mismatched)} section(s)...")
                        if session.client_thread and session.client_thread.is_connected:
                            logger.info(f"Live Sync ({session.target_object_name}): Requesting auto-healing repair for {len(mismatched)} sections...")
                            session.client_thread.send_repair_request(mismatched)
                    elif session.is_initial_handshake:
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
                        if len(mismatched) > 0 and session.client_thread and session.client_thread.is_connected:
                            logger.info(f"Live Sync ({session.target_object_name}): Periodic check detected {len(mismatched)} mismatched sections.")
                            session.is_repairing_partial = True
                            session.is_streaming = True
                            session.stream_total_sections = len(mismatched)
                            session.stream_received_sections = 0
                            session.client_thread.send_repair_request(mismatched)
                except Exception as e:
                    logger.error(f"Live Sync manifest error for {session.target_object_name}: {e}", exc_info=True)
                    ProgressBar.cancel(message=f"Manifest check error: {e}")
            run_in_main_thread(update)

        def on_section_snapshot(sec_x, sec_y, sec_z, start_x, start_y, start_z, size_x, size_y, size_z, palette, grid_indices):
            session.is_streaming = True
            session.stream_last_drain_time = time.time()
            updated = session.storage.set_section_snapshot(
                sec_x, sec_y, sec_z, start_x, start_y, start_z,
                size_x, size_y, size_z, palette, grid_indices
            )
            if updated:
                session.stream_section_queue.put((sec_x, sec_y, sec_z, palette))

        timeout_sec = getattr(sys_pref, "network_timeout", 0) if sys_pref else 0
        effective_timeout = float(timeout_sec) if timeout_sec > 0 else 10.0

        session.client_thread = SyncClientThread(
            url=props.url,
            on_status_change=on_status_change,
            on_selection_info=on_selection_info,
            on_full_snapshot=on_full_snapshot,
            on_delta_update=on_delta_update,
            on_section_manifest=on_section_manifest,
            on_section_snapshot=on_section_snapshot,
            on_handshake_info=on_handshake_info,
            timeout=effective_timeout,
        )
        _client_thread = session.client_thread
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
        global _client_thread
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
            _client_thread = None

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


def cleanup_sync_state() -> None:
    """Clean up all live sync module globals, background threads, timers, and storage."""
    global _client_thread, _last_seq_id, _rebuild_timer_registered, _pending_full_rebuild
    global _cached_atlas_params, _cached_mat_signature, _is_initial_handshake, _is_repairing_partial, _pending_full_sync_request
    global _is_streaming, _stream_received_sections, _stream_total_sections
    stop_main_thread_pump()
    _session_manager.clear_all()
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


def unregister():
    """Unregister cleanup hook called when addon is disabled/uninstalled."""
    cleanup_sync_state()


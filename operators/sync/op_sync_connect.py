"""
Operators for connecting, disconnecting, and synchronizing with Live Sync WebSocket server.
Supports multi-container isolation with single active session exclusivity and switching.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional
import bpy

from ...bridge.sync import (
    get_sync_bridge_session,
    is_sync_available,
    load_atlas_from_cache,
    load_model_database_from_cache,
    load_biome_resolver_from_cache,
)
from ...bridge.assets import (
    invalidate_asset_cache_memory,
    reload_atlas_images,
)
from ...utils.assets import (
    can_execute_asset_pipeline,
    check_asset_cache_status,
    ensure_pipeline_assets_ready_sync,
)
from .hierarchy import (
    _safe_get_custom_prop,
    _safe_set_custom_prop,
    get_or_create_world_container,
    get_or_create_world_mesh_object,
    find_world_mesh_child,
    resolve_world_root_object,
    update_world_mesh,
    persist_sync_session_state,
    load_persisted_sync_session_state,
)
from .properties import (
    get_active_sync_container,
    set_active_sync_container,
)

logger = logging.getLogger("MoziToolKit.Sync.Connect")

_timer_registered = False
_progress_reporter = None
_delayed_close_callback = None
_pending_cloud_sync_time = None

# RFC v3.1 §6.2 zero-rebuild fast path.
# The protocol/server support VERIFIED_SKIP_REBUILD, but the Blender client cannot
# use it yet: the native VoxelStorage is not persisted into the .blend, so entering
# LIVE with an empty Rust storage would make the next delta remesh only the changed
# blocks and wipe the viewport. Keep HELLO cached_* fields zeroed (full baseline)
# until VoxelStorage persistence/restore is implemented.
_ZERO_REBUILD_FAST_PATH_ENABLED = False


def is_sync_timer_running() -> bool:
    """Checks whether the Live Sync polling timer is currently active."""
    return bpy is not None and hasattr(bpy.app, "timers") and bpy.app.timers.is_registered(_sync_timer_tick)


def start_sync_timer() -> None:
    """Safely registers the main-thread sync polling timer if not already running."""
    global _timer_registered
    if bpy is not None and hasattr(bpy.app, "timers"):
        if not bpy.app.timers.is_registered(_sync_timer_tick):
            bpy.app.timers.register(_sync_timer_tick, first_interval=0.016)
    _timer_registered = True


def stop_sync_timer() -> None:
    """Safely unregisters and cancels the main-thread sync polling timer and pending progress reporters."""
    global _timer_registered, _delayed_close_callback, _pending_cloud_sync_time
    if bpy is not None and hasattr(bpy.app, "timers"):
        if bpy.app.timers.is_registered(_sync_timer_tick):
            try:
                bpy.app.timers.unregister(_sync_timer_tick)
            except Exception as e:
                logger.debug(f"Failed to unregister sync timer: {e}")
        if _delayed_close_callback is not None and bpy.app.timers.is_registered(_delayed_close_callback):
            try:
                bpy.app.timers.unregister(_delayed_close_callback)
            except Exception:
                pass
            _delayed_close_callback = None
    _pending_cloud_sync_time = None
    _timer_registered = False
    _close_progress_reporter()


def _get_progress_reporter(title: str = "Mozi Live Sync"):
    global _progress_reporter
    if _progress_reporter is None:
        from ...utils.progress import BlenderProgressReporter
        _progress_reporter = BlenderProgressReporter(bpy.context, title=title)
        _progress_reporter.start()
    else:
        _progress_reporter.title = title
    return _progress_reporter


def _close_progress_reporter(delay_sec: float = 0.0):
    global _progress_reporter, _delayed_close_callback
    if _delayed_close_callback is not None:
        if bpy is not None and hasattr(bpy.app, "timers") and bpy.app.timers.is_registered(_delayed_close_callback):
            try:
                bpy.app.timers.unregister(_delayed_close_callback)
            except Exception:
                pass
        _delayed_close_callback = None

    if _progress_reporter is not None:
        rep = _progress_reporter
        _progress_reporter = None
        if delay_sec > 0 and bpy is not None and hasattr(bpy.app, "timers"):
            def _delayed_close():
                global _delayed_close_callback
                _delayed_close_callback = None
                rep.close()
                return None
            _delayed_close_callback = _delayed_close
            bpy.app.timers.register(_delayed_close, first_interval=delay_sec)
        else:
            rep.close()


def _get_active_props(context: Optional[bpy.types.Context] = None, root_container: Optional[bpy.types.Object] = None) -> Optional[bpy.types.PropertyGroup]:
    """Resolves active live sync properties bound to container or scene."""
    if root_container is not None and hasattr(root_container, "mozi_sync"):
        return root_container.mozi_sync
    ctx = context or getattr(bpy, "context", None)
    if ctx:
        scene = getattr(ctx, "scene", None)
        active_container = get_active_sync_container(scene)
        if active_container and hasattr(active_container, "mozi_sync"):
            return active_container.mozi_sync
        active_obj = getattr(ctx, "active_object", None)
        if active_obj:
            resolved = resolve_world_root_object(active_obj)
            if resolved and hasattr(resolved, "mozi_sync"):
                return resolved.mozi_sync
        if scene and hasattr(scene, "mozi_sync"):
            return scene.mozi_sync
    return None


def _sync_timer_tick() -> Optional[float]:
    """
    Main-thread non-blocking timer polling events from native libmtk engine
    and updating the Blender viewport world mesh of the active bound container.
    """
    global _pending_cloud_sync_time
    session = get_sync_bridge_session()

    # Drain pending events BEFORE checking is_active. The terminal DISCONNECTED
    # event is queued just before the worker exits; checking is_active first would
    # discard it and leave the panel stuck showing "CONNECTED" while the native
    # session is already dead (clicking Refresh then reports "not connected").
    events = session.poll_events() if session is not None else []
    session_active = bool(session is not None and session.is_active)

    scene = getattr(bpy.context, "scene", None) if bpy.context else None
    active_container = get_active_sync_container(scene)
    if not active_container:
        active_container = get_or_create_world_container(bpy.context)
        set_active_sync_container(scene, active_container)

    props = getattr(active_container, "mozi_sync", None) or _get_active_props(bpy.context, active_container)
    scene_props = getattr(scene, "mozi_sync", None) if scene else None

    def _sync_prop(name: str, val: Any) -> None:
        if props and hasattr(props, name):
            setattr(props, name, val)
        if scene_props and hasattr(scene_props, name):
            setattr(scene_props, name, val)

    latest_world_mesh = None
    latest_generation = 0
    needs_voxel_sync = False
    terminal_status: Optional[str] = None

    for ev in events:
        ev_type = ev.get("type")
        if not ev_type:
            continue

        if ev_type == "WORLD_MESH_READY":
            # Coalesce: only keep newest mesh to prevent Blender event queue choke and OOM
            latest_world_mesh = ev.get("mesh")
            latest_generation = ev.get("generation", 0)
            continue

        if ev_type == "STATUS_CHANGE":
            status = ev.get("status", "DISCONNECTED")
            _sync_prop("connection_status", status)
            if status == "CONNECTED":
                _sync_prop("validation_info", "Connected to Live Sync")
            elif status.startswith("DISCONNECTED"):
                terminal_status = status
                _sync_prop("is_streaming", False)
                _sync_prop("validation_info", status)
                _close_progress_reporter()
            # Intermediate statuses (CONNECTING/RECONNECTING/transport errors) are
            # surfaced by connection_status but must not be treated as "disconnected".

        elif ev_type == "SELECTION_UPDATED":
            _sync_prop("has_selection", True)
            _sync_prop("min_x", ev.get("min_x", 0))
            _sync_prop("min_y", ev.get("min_y", 0))
            _sync_prop("min_z", ev.get("min_z", 0))
            sx = ev.get("size_x", 0)
            sy = ev.get("size_y", 0)
            sz = ev.get("size_z", 0)
            _sync_prop("size_x", sx)
            _sync_prop("size_y", sy)
            _sync_prop("size_z", sz)
            _sync_prop("total_blocks", sx * sy * sz)

        elif ev_type == "HANDSHAKE":
            epoch = ev.get("epoch", 0)
            seq = ev.get("sequence", 0)
            decision = ev.get("decision", 2)
            dimension = ev.get("dimension", "minecraft:overworld")
            _sync_prop("dimension", dimension)
            _sync_prop("validation_info", f"Sync Handshake: decision={decision}, epoch={epoch}, seq={seq}")
            if ev.get("decision_code") == 0 or decision == "VERIFIED_SKIP_REBUILD":
                _sync_prop("sync_verified", True)
                _sync_prop("validation_info", "0ms Instant Reconnect Verified: 100% in sync with scene")
                _sync_prop("is_streaming", False)
                _close_progress_reporter()

        elif ev_type == "DELTA_APPLIED":
            cnt = ev.get("change_count", 0)
            _sync_prop("last_update_info", f"Delta Applied: {cnt} block modification(s)")

            # Add to history
            if props:
                item = props.delta_history.add()
                item.pos_str = f"Delta #{len(props.delta_history)}"
                item.block_state = f"{cnt} blocks modified"
                item.time_str = time.strftime("%H:%M:%S")
                if len(props.delta_history) > 50:
                    props.delta_history.remove(0)

            # Schedule debounced voxel point cloud synchronization (coalesce rapid block changes)
            _pending_cloud_sync_time = time.time() + 0.35

        elif ev_type == "STREAM_PROGRESS":
            stage = ev.get("stage", "sync")
            tot = ev.get("total", 0)
            msg = ev.get("message", "")
            _sync_prop("is_streaming", True)
            _sync_prop("stream_stage", stage)

            # Rust owns the two-phase phase weighting; the host only displays it.
            normalized_curr = int(min(100.0, max(0.0, float(ev.get("percent", 0.0)))))
            _sync_prop("stream_progress_current", normalized_curr)
            _sync_prop("stream_progress_total", 100)
            _sync_prop("stream_message", msg)

            if tot > 0:
                stage_title = (
                    "Live Sync: Download" if stage == "sync_download"
                    else ("Live Sync: Mesh" if stage == "sync_meshing"
                    else ("Live Sync: Request" if stage == "sync_request"
                    else "Live Sync"))
                )
                _get_progress_reporter(title=stage_title).update(normalized_curr, 100, message=msg)

        elif ev_type == "STREAM_FINISHED":
            needs_voxel_sync = True
            _pending_cloud_sync_time = None
            built = ev.get("built_sections", 0)
            _sync_prop("last_update_info", f"Stream Complete ({built} active chunks)")
            _sync_prop("stream_progress_current", 100)
            _sync_prop("stream_progress_total", 100)
            _sync_prop("is_streaming", False)

        elif ev_type == "VERIFIED":
            is_ver = ev.get("is_verified", False)
            _sync_prop("sync_verified", is_ver)
            msg = ev.get("message", "")
            if is_ver:
                _sync_prop("validation_info", msg or "100% in sync with scene")
                _sync_prop("is_streaming", False)
            else:
                _sync_prop("validation_info", f"Out of sync: {msg}" if msg else "Detected out-of-sync sections")

        elif ev_type == "WARNING":
            _sync_prop("validation_info", f"Warning: {ev.get('message', '')}")

        elif ev_type == "ERROR":
            message = ev.get("message", "")
            # Make the #1 failure mode actionable: the token field is not persisted
            # into .blend, so a blank field after reopening looks "identical".
            if "Authentication failed" in message:
                message = f"{message} (fill 'Auth Token' with the value of /yefira config token, then reconnect)"
            _sync_prop("validation_info", f"Error: {message}")
            _sync_prop("is_streaming", False)
            _close_progress_reporter()

    # Authoritative connection state comes from the native session, never from a
    # string comparison against an intermediate status message.
    if session_active:
        native_status = getattr(session, "connection_status", "") or ""
        if isinstance(native_status, str) and native_status:
            _sync_prop("connection_status", native_status)
        _sync_prop("is_connected", bool(getattr(session, "is_connected", False)))

    if latest_world_mesh is not None:
        try:
            curr_gen_raw = _safe_get_custom_prop(active_container, "mtk:client_generation", 0)
            if isinstance(curr_gen_raw, (int, float)):
                curr_gen = int(curr_gen_raw)
            elif isinstance(curr_gen_raw, str):
                try:
                    curr_gen = int(curr_gen_raw)
                except ValueError:
                    curr_gen = 0
            else:
                curr_gen = 0
            if latest_generation >= curr_gen:
                if getattr(latest_world_mesh, "profile", None) is not None:
                    try:
                        from ...bridge.diagnostics import record_operation_profile
                        record_operation_profile("Live Sync Mesh", latest_world_mesh.profile)
                    except Exception:
                        pass
                world_obj = get_or_create_world_mesh_object(bpy.context, root_container=active_container)
                # Delta updates deliberately avoid copying the native storage; the
                # initial baseline/point-cloud sync registers it for biome re-tints.
                storage = session.get_storage() if needs_voxel_sync else None
                v_count, f_count = update_world_mesh(
                    world_obj,
                    latest_world_mesh,
                    skip_string_attributes=True,
                    storage=storage,
                    sync_point_cloud=needs_voxel_sync,
                    atlas=getattr(session, "atlas", None),
                    session=session,
                )
                _safe_set_custom_prop(active_container, "mtk:client_generation", latest_generation)
                _sync_prop("point_count", v_count)
                _sync_prop("faces_count", f_count)
                _sync_prop("last_update_info", f"World Mesh updated: {v_count:,} vertices, {f_count:,} faces")
                _sync_prop("is_streaming", False)

                # Atomically persist the Rust-produced session state into the root container.
                if active_container:
                    state_json = session.export_persisted_state_json(user_modified=False)
                    if isinstance(state_json, str) and state_json:
                        persist_sync_session_state(active_container, state_json)

                if _progress_reporter is not None:
                    _progress_reporter.update(_progress_reporter.total, _progress_reporter.total, message=f"Mesh ready ({v_count:,} v, {f_count:,} f)")
            else:
                logger.debug(f"Skipping stale world mesh generation {latest_generation} < {curr_gen}")
        except Exception as e:
            logger.error(f"Failed to inject WorldMesh into Blender for container '{active_container.name}': {e}")
        finally:
            _close_progress_reporter(delay_sec=1.5)
    elif needs_voxel_sync:
        try:
            storage = session.get_storage()
            if storage is not None:
                from ...utils.point_cloud import ensure_voxel_child_cloud
                ensure_voxel_child_cloud(active_container, storage=storage, origin_centered=True, initial_hidden=True)

                # Cache the storage under the container/mesh names so the biome
                # panel can restore WORLD even if the initial mesh event arrived
                # before this STREAM_FINISHED event.
                from ...utils.materials.biome.updater import (
                    mark_world_biome,
                    register_object_storage,
                )
                if mark_world_biome is not None:
                    container_name = getattr(active_container, "name", "")
                    if isinstance(container_name, str) and container_name:
                        register_object_storage(container_name, storage)
                        register_object_storage(f"{container_name}_Mesh", storage)
                    container_id = active_container.get("mtk:container_id") if hasattr(active_container, "get") else None
                    if isinstance(container_id, str) and container_id:
                        register_object_storage(container_id, storage)
                    mark_world_biome(active_container, storage)
        except Exception as e:
            logger.debug(f"Failed syncing voxel cloud on event: {e}")

    # Check debounced point cloud sync (only update if storage is fully populated to avoid wiping existing cloud)
    if _pending_cloud_sync_time is not None and time.time() >= _pending_cloud_sync_time:
        _pending_cloud_sync_time = None
        try:
            storage = session.get_storage()
            non_empty_count = getattr(props, "non_empty_sections", 0) if props else 0
            if storage is not None and hasattr(storage, "get_all_non_empty_sections"):
                storage_non_empty = len(storage.get_all_non_empty_sections())
                # Safety barrier: Do NOT overwrite an existing large point cloud if in-memory storage is sparse/unpopulated
                if storage_non_empty > 0 and (non_empty_count == 0 or storage_non_empty >= non_empty_count):
                    from ...utils.point_cloud import ensure_voxel_child_cloud
                    ensure_voxel_child_cloud(active_container, storage=storage, origin_centered=True, initial_hidden=True)
                    logger.debug("Debounced voxel child cloud updated successfully")
                else:
                    logger.debug(f"Skipping point cloud sync: sparse storage ({storage_non_empty}/{non_empty_count} sections)")
        except Exception as e:
            logger.debug(f"Failed debounced voxel cloud sync: {e}")

    # If the session ended (fatal disconnect or explicit stop), clear stale UI state
    # and unregister the timer cleanly. This runs after event processing so the final
    # DISCONNECTED event can never be lost.
    if not session_active:
        _close_progress_reporter()
        _sync_prop("is_connected", False)
        _sync_prop("connection_status", "DISCONNECTED")
        _sync_prop("is_streaming", False)
        if terminal_status:
            _sync_prop("validation_info", terminal_status)
        else:
            last_err = getattr(session, "last_error", "") if session is not None else ""
            _sync_prop("validation_info", last_err or "Disconnected")
        stop_sync_timer()
        return None

    return 0.016  # ~60 fps poll interval


class MOZI_OT_sync_connect(bpy.types.Operator):
    """Connect to Minecraft Live Sync streaming server for the active or specified container."""
    bl_idname = "mozi.sync_connect"
    bl_label = "Connect"
    bl_description = "Connect to Minecraft Live Sync WebSocket Server"
    bl_options = {'REGISTER', 'UNDO'}

    target_container: bpy.props.StringProperty(
        name="Target Container",
        description="Name of the root Empty container to bind",
        default="",
    )

    @classmethod
    def poll(cls, context):
        from ...utils.system import get_prefs

        prefs = get_prefs(context)
        can_run, reason = can_execute_asset_pipeline(prefs)
        if not can_run:
            if hasattr(cls, "poll_message_set"):
                cls.poll_message_set(reason)
            return False
        return True

    def invoke(self, context, event):
        target_obj = None
        if self.target_container and self.target_container in bpy.data.objects:
            target_obj = bpy.data.objects[self.target_container]
        else:
            active_obj = getattr(context, "active_object", None)
            target_obj = resolve_world_root_object(active_obj) if active_obj else None
            if not target_obj:
                target_obj = get_or_create_world_container(context)
            self.target_container = target_obj.name

        session = get_sync_bridge_session()
        curr_active = get_active_sync_container(context.scene)

        # If another container is currently actively syncing, ask for confirmation to switch
        if session.is_active and curr_active and curr_active != target_obj:
            curr_props = getattr(curr_active, "mozi_sync", None)
            if curr_props and (curr_props.is_connected or curr_props.connection_status.startswith("CONNECTING")):
                return context.window_manager.invoke_confirm(
                    self,
                    event,
                    message=f"Container '{curr_active.name}' is actively syncing. Disconnect it and switch to '{target_obj.name}'?",
                )

        return self.execute(context)

    def execute(self, context):
        if not is_sync_available():
            self.report({'ERROR'}, "Native libmtk core is missing or not installed!")
            return {'CANCELLED'}

        target_obj = None
        if self.target_container and self.target_container in bpy.data.objects:
            target_obj = bpy.data.objects[self.target_container]
        else:
            active_obj = getattr(context, "active_object", None)
            target_obj = resolve_world_root_object(active_obj) if active_obj else None
            if not target_obj:
                target_obj = get_or_create_world_container(context)
            self.target_container = target_obj.name

        session = get_sync_bridge_session()
        curr_active = get_active_sync_container(context.scene)

        # If switching from an existing active container, gracefully stop old session and freeze it
        if session.is_active and curr_active and curr_active != target_obj:
            stop_sync_timer()
            session.stop()
            if hasattr(curr_active, "mozi_sync"):
                curr_active.mozi_sync.is_connected = False
                curr_active.mozi_sync.connection_status = "DISCONNECTED"
                curr_active.mozi_sync.validation_info = "Disconnected (switched to another container)"
            logger.info(f"Detached active sync from '{curr_active.name}' to switch to '{target_obj.name}'")

        set_active_sync_container(context.scene, target_obj)

        # A new native session restarts its mesh generation counter at 1. Clear any
        # generation persisted in the .blend from a previous session, otherwise
        # every WORLD_MESH_READY would be treated as stale and silently discarded
        # (the viewport then never receives voxel data until the file is recreated).
        _safe_set_custom_prop(target_obj, "mtk:client_generation", 0)

        props = getattr(target_obj, "mozi_sync", None) or _get_active_props(context, target_obj)
        url = props.url if props and props.url else "ws://127.0.0.1:8765"

        from ...utils.system import get_prefs
        prefs = get_prefs(context)

        # Asset readiness gate: verify valid vanilla client base pack before proceeding
        can_run, reason = can_execute_asset_pipeline(prefs)
        if not can_run:
            self.report({'WARNING'}, reason)
            return {'CANCELLED'}

        # Asset readiness gate
        status = check_asset_cache_status(prefs)
        if status in ("NO_PACKS", "NO_VANILLA"):
            self.report({'WARNING'}, reason)
            return {'CANCELLED'}
        if status in ("MISSING", "STALE"):
            self.report({'INFO'}, f"Asset cache is {status.lower()}; automatically precompiling before Live Sync connection...")
            success, _ = ensure_pipeline_assets_ready_sync(prefs)
            if not success:
                self.report({'ERROR'}, "Failed to precompile assets before connection.")
                return {'CANCELLED'}
            invalidate_asset_cache_memory()
            try:
                reload_atlas_images(prefs)
            except Exception:
                pass

        model_db = load_model_database_from_cache(prefs)
        atlas = load_atlas_from_cache(prefs)
        biome_resolver = load_biome_resolver_from_cache(prefs)

        # Check persisted session state on active container to attempt 0ms reconnect verification
        cached_state = load_persisted_sync_session_state(target_obj)

        # The zero-rebuild fast path may only be used when the scene already holds
        # a populated world mesh. Persisted custom properties survive even if the
        # user deleted the mesh object, so verify the local geometry first.
        local_mesh = find_world_mesh_child(target_obj)
        has_local_mesh = bool(
            local_mesh is not None
            and getattr(local_mesh, "type", "") == "MESH"
            and getattr(getattr(local_mesh, "data", None), "vertices", None) is not None
            and len(local_mesh.data.vertices) > 0
        )
        if not _ZERO_REBUILD_FAST_PATH_ENABLED or not has_local_mesh:
            cached_state = {}
        cached_state_json = None
        if cached_state and not cached_state.get("user_modified", False):
            cached_state_json = cached_state.get("state_json") or None

        try:
            from ...utils.assets.cache_utils import get_cache_dir
            skin_cache = get_cache_dir() / "skins"
            skin_cache.mkdir(parents=True, exist_ok=True)
            session.set_skin_cache_dir(str(skin_cache))
        except Exception as e:
            logger.debug("Failed configuring skin cache dir on connect: %s", e)

        success = session.start(
            url=url,
            auto_reconnect=True,
            max_reconnect_attempts=5,
            model_db=model_db,
            atlas=atlas,
            biome_resolver=biome_resolver,
            auth_token=(getattr(props, "auth_token", "") or None) if props else None,
            cached_state_json=cached_state_json,
        )

        if not success:
            err = session.last_error or "Check system console for details"
            self.report({'ERROR'}, f"Failed to initiate connection to {url}: {err}")
            return {'CANCELLED'}

        if props:
            props.is_connected = False
            props.connection_status = "CONNECTING..."
            props.validation_info = f"Connecting to {url}..."
            props.is_streaming = False

        scene_props = getattr(context.scene, "mozi_sync", None)
        if scene_props:
            scene_props.is_connected = False
            scene_props.connection_status = "CONNECTING..."
            scene_props.validation_info = f"Connecting to {url}..."
            scene_props.is_streaming = False

        start_sync_timer()
        self.report({'INFO'}, f"Connecting Live Sync for '{target_obj.name}' at {url}")
        return {'FINISHED'}


class MOZI_OT_sync_disconnect(bpy.types.Operator):
    """Disconnect from Minecraft Live Sync streaming server."""
    bl_idname = "mozi.sync_disconnect"
    bl_label = "Disconnect"
    bl_description = "Disconnect Live Sync session and stop background listener"
    bl_options = {'REGISTER', 'UNDO'}

    target_container: bpy.props.StringProperty(
        name="Target Container",
        description="Name of the root Empty container to disconnect",
        default="",
    )

    def execute(self, context):
        stop_sync_timer()
        session = get_sync_bridge_session()

        target_obj = None
        if self.target_container and self.target_container in bpy.data.objects:
            target_obj = bpy.data.objects[self.target_container]
        else:
            target_obj = get_active_sync_container(context.scene) or resolve_world_root_object(getattr(context, "active_object", None))

        if target_obj:
            state_json = session.export_persisted_state_json(user_modified=False)
            if isinstance(state_json, str) and state_json:
                persist_sync_session_state(target_obj, state_json)

        session.stop()

        if target_obj and hasattr(target_obj, "mozi_sync"):
            props = target_obj.mozi_sync
            props.is_connected = False
            props.connection_status = "DISCONNECTED"
            props.validation_info = "Disconnected"
            props.is_streaming = False

        scene_props = getattr(context.scene, "mozi_sync", None)
        if scene_props:
            scene_props.is_connected = False
            scene_props.connection_status = "DISCONNECTED"
            scene_props.validation_info = "Disconnected"
            scene_props.is_streaming = False

        set_active_sync_container(context.scene, None)
        self.report({'INFO'}, "Live Sync Disconnected.")
        return {'FINISHED'}


class MOZI_OT_sync_refresh(bpy.types.Operator):
    """Request server to resend active selection snapshot."""
    bl_idname = "mozi.sync_refresh"
    bl_label = "Refresh Data"
    bl_description = "Request a full snapshot resync from the server"
    bl_options = {'REGISTER', 'UNDO'}

    target_container: bpy.props.StringProperty(
        name="Target Container",
        description="Name of the root Empty container to refresh",
        default="",
    )

    def execute(self, context):
        session = get_sync_bridge_session()

        target_obj = None
        if self.target_container and self.target_container in bpy.data.objects:
            target_obj = bpy.data.objects[self.target_container]
        else:
            target_obj = get_active_sync_container(context.scene) or resolve_world_root_object(getattr(context, "active_object", None))

        props = getattr(target_obj, "mozi_sync", None) or getattr(context.scene, "mozi_sync", None)

        # Refresh the UI state from the native session before deciding, so a stale
        # panel (e.g. leftover CONNECTED text after a silent disconnect) cannot
        # produce a misleading "not connected" report.
        session.poll_events()
        is_active = bool(getattr(session, "is_active", False))
        is_connected = bool(getattr(session, "is_connected", False))
        status = str(getattr(session, "connection_status", "") or "DISCONNECTED")

        if not is_active:
            stop_sync_timer()
            if props:
                props.is_connected = False
                props.connection_status = "DISCONNECTED"
                props.is_streaming = False
                props.validation_info = "Disconnected"
            self.report({'WARNING'}, "Live Sync is not connected.")
            return {'CANCELLED'}

        if not is_connected:
            if props:
                props.connection_status = status
                props.is_connected = False
            self.report(
                {'WARNING'},
                f"Live Sync is not ready yet ({status}). Please wait for the connection to be restored.",
            )
            return {'CANCELLED'}

        if props:
            props.is_streaming = True
            props.stream_stage = "sync_request"
            props.stream_message = "Requesting snapshot from server..."
            props.stream_progress_current = 0
            props.stream_progress_total = 100

        reporter = _get_progress_reporter(title="Live Sync: Request")
        reporter.update(0, 100, message="Requesting snapshot from server...")

        if not session.request_resync():
            _close_progress_reporter()
            if props:
                props.is_streaming = False
                props.validation_info = "Failed to send snapshot request"
            self.report({'ERROR'}, "Failed to request a snapshot from the server.")
            return {'CANCELLED'}

        self.report({'INFO'}, "Full snapshot requested from server.")
        return {'FINISHED'}


OPERATOR_CLASSES = (
    MOZI_OT_sync_connect,
    MOZI_OT_sync_disconnect,
    MOZI_OT_sync_refresh,
)

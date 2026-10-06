"""
Operators for connecting, disconnecting, and synchronizing with Live Sync WebSocket server.
Supports multi-container isolation with single active session exclusivity and switching.
"""

from __future__ import annotations

import logging
import time
from typing import Optional
import bpy

try:
    from ...bridge.sync import (
        get_sync_bridge_session,
        is_sync_available,
        load_atlas_from_cache,
        load_model_database_from_cache,
        load_biome_resolver_from_cache,
    )
except (ImportError, ValueError):
    from bridge.sync import (
        get_sync_bridge_session,
        is_sync_available,
        load_atlas_from_cache,
        load_model_database_from_cache,
        load_biome_resolver_from_cache,
    )
from .hierarchy import (
    get_or_create_world_container,
    get_or_create_world_mesh_object,
    resolve_world_root_object,
    update_world_mesh,
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
        try:
            from ...utils.progress import BlenderProgressReporter
        except (ImportError, ValueError):
            from utils.progress import BlenderProgressReporter
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
    if not session.is_active:
        stop_sync_timer()
        return None

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

    events = session.poll_events()
    latest_world_mesh = None
    needs_voxel_sync = False

    for ev in events:
        ev_type = ev.get("type")
        if not ev_type:
            continue

        if ev_type == "WORLD_MESH_READY":
            # Coalesce: only keep newest mesh to prevent Blender event queue choke and OOM
            latest_world_mesh = ev.get("mesh")
            continue

        if ev_type == "STATUS_CHANGE":
            status = ev.get("status", "DISCONNECTED")
            if status != "CONNECTED":
                _close_progress_reporter()
            _sync_prop("connection_status", status)
            _sync_prop("is_connected", (status == "CONNECTED"))
            if status == "CONNECTED":
                _sync_prop("validation_info", "Connected to Live Sync")
            elif status.startswith("DISCONNECTED"):
                _sync_prop("validation_info", status)

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
            tot = ev.get("total_sections", 0)
            non_empty = ev.get("non_empty_sections", 0)
            vol = ev.get("total_volume", 0)
            _sync_prop("total_sections", tot)
            _sync_prop("non_empty_sections", non_empty)
            if tot == non_empty or non_empty == 0:
                _sync_prop("validation_info", f"Sync Handshake: {tot} chunks ({vol:,} blocks)")
            else:
                _sync_prop("validation_info", f"Sync Handshake: {non_empty} active chunks ({tot} covered, {vol:,} blocks)")

        elif ev_type == "DELTA_APPLIED":
            # Schedule debounced point cloud sync (350ms idle) to prevent blocking main thread
            _pending_cloud_sync_time = time.time() + 0.35
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

        elif ev_type == "STREAM_PROGRESS":
            stage = ev.get("stage", "sync")
            curr = ev.get("current", 0)
            tot = ev.get("total", 0)
            msg = ev.get("message", "")
            _sync_prop("is_streaming", True)
            _sync_prop("stream_stage", stage)
            _sync_prop("stream_progress_current", curr)
            _sync_prop("stream_progress_total", tot)
            _sync_prop("stream_message", msg)

            if tot > 0:
                stage_title = (
                    "Live Sync: Download" if stage == "sync_download"
                    else ("Live Sync: Mesh" if stage == "sync_meshing"
                    else ("Live Sync: Request" if stage == "sync_request"
                    else "Live Sync"))
                )
                _get_progress_reporter(title=stage_title).update(curr, tot, message=msg)

        elif ev_type == "STREAM_FINISHED":
            needs_voxel_sync = True
            _pending_cloud_sync_time = None
            built = ev.get("built_sections", 0)
            _sync_prop("last_update_info", f"Stream Complete ({built} active chunks)")
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
            _sync_prop("validation_info", f"Error: {ev.get('message', '')}")

    if latest_world_mesh is not None:
        try:
            world_obj = get_or_create_world_mesh_object(bpy.context, root_container=active_container)
            storage = session.get_storage()
            v_count, f_count = update_world_mesh(
                world_obj,
                latest_world_mesh,
                skip_string_attributes=True,
                storage=storage,
                sync_point_cloud=needs_voxel_sync,
            )
            _sync_prop("point_count", v_count)
            _sync_prop("faces_count", f_count)
            _sync_prop("last_update_info", f"World Mesh updated: {v_count:,} vertices, {f_count:,} faces")
            _sync_prop("is_streaming", False)

            if _progress_reporter is not None:
                _progress_reporter.update(_progress_reporter.total, _progress_reporter.total, message=f"Mesh ready ({v_count:,} v, {f_count:,} f)")
        except Exception as e:
            logger.error(f"Failed to inject WorldMesh into Blender for container '{active_container.name}': {e}")
        finally:
            _close_progress_reporter(delay_sec=1.5)
    elif needs_voxel_sync:
        try:
            storage = session.get_storage()
            if storage is not None:
                try:
                    from ...bridge.point_cloud import ensure_voxel_child_cloud
                except (ImportError, ValueError):
                    from bridge.point_cloud import ensure_voxel_child_cloud
                ensure_voxel_child_cloud(active_container, storage=storage, origin_centered=True, initial_hidden=True)
        except Exception as e:
            logger.debug(f"Failed syncing voxel cloud on event: {e}")

    # Check debounced point cloud sync
    if _pending_cloud_sync_time is not None and time.time() >= _pending_cloud_sync_time:
        _pending_cloud_sync_time = None
        try:
            storage = session.get_storage()
            if storage is not None:
                try:
                    from ...bridge.point_cloud import ensure_voxel_child_cloud
                except (ImportError, ValueError):
                    from bridge.point_cloud import ensure_voxel_child_cloud
                ensure_voxel_child_cloud(active_container, storage=storage, origin_centered=True, initial_hidden=True)
                logger.debug("Debounced voxel child cloud updated successfully")
        except Exception as e:
            logger.debug(f"Failed debounced voxel cloud sync: {e}")

    # If session is disconnected or ended, unregister timer cleanly
    if not session.is_active or (props and not props.is_connected and props.connection_status.startswith("DISCONNECTED")):
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

        props = getattr(target_obj, "mozi_sync", None) or _get_active_props(context, target_obj)
        url = props.url if props and props.url else "ws://127.0.0.1:8765"

        try:
            from ...utils.system import get_prefs
        except (ImportError, ValueError):
            from utils.system import get_prefs
        prefs = get_prefs(context)
        model_db = load_model_database_from_cache(prefs)
        atlas = load_atlas_from_cache(prefs)
        biome_resolver = load_biome_resolver_from_cache(prefs)

        success = session.start(
            url=url,
            auto_reconnect=True,
            max_reconnect_attempts=5,
            model_db=model_db,
            atlas=atlas,
            biome_resolver=biome_resolver,
            unified_mesh=True,
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
        session.stop()

        target_obj = None
        if self.target_container and self.target_container in bpy.data.objects:
            target_obj = bpy.data.objects[self.target_container]
        else:
            target_obj = get_active_sync_container(context.scene) or resolve_world_root_object(getattr(context, "active_object", None))

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
        if not session.is_active:
            self.report({'WARNING'}, "Live Sync is not connected.")
            return {'CANCELLED'}

        target_obj = None
        if self.target_container and self.target_container in bpy.data.objects:
            target_obj = bpy.data.objects[self.target_container]
        else:
            target_obj = get_active_sync_container(context.scene) or resolve_world_root_object(getattr(context, "active_object", None))

        props = getattr(target_obj, "mozi_sync", None) or getattr(context.scene, "mozi_sync", None)
        if props:
            props.is_streaming = True
            props.stream_stage = "sync_request"
            props.stream_message = "Requesting snapshot from server..."
            props.stream_progress_current = 0
            props.stream_progress_total = 100

        reporter = _get_progress_reporter(title="Live Sync: Request")
        reporter.update(0, 100, message="Requesting snapshot from server...")

        session.send_full_sync_request()
        self.report({'INFO'}, "Full snapshot requested from server.")
        return {'FINISHED'}


OPERATOR_CLASSES = (
    MOZI_OT_sync_connect,
    MOZI_OT_sync_disconnect,
    MOZI_OT_sync_refresh,
)

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
from .hierarchy import get_or_create_world_mesh_object, update_world_mesh

logger = logging.getLogger("MoziToolKit.Sync.Connect")

_timer_registered = False
_progress_reporter = None
_delayed_close_callback = None


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
    global _timer_registered, _delayed_close_callback
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
    session = get_sync_bridge_session()
    if not session.is_active:
        stop_sync_timer()
        return None

    props = _get_active_props(bpy.context)
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
            if props:
                props.connection_status = status
                props.is_connected = (status == "CONNECTED")
                if status == "CONNECTED":
                    props.validation_info = "Connected to Live Sync"
                elif status.startswith("DISCONNECTED"):
                    props.validation_info = status

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

        elif ev_type == "DELTA_APPLIED":
            needs_voxel_sync = True
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
            stage = ev.get("stage", "sync")
            curr = ev.get("current", 0)
            tot = ev.get("total", 0)
            msg = ev.get("message", "")
            if props:
                props.is_streaming = True
                props.stream_stage = stage
                props.stream_progress_current = curr
                props.stream_progress_total = tot
                props.stream_message = msg
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
            if props:
                built = ev.get("built_sections", 0)
                props.last_update_info = f"Stream Complete ({built} chunks received)"
                props.is_streaming = False

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

    if latest_world_mesh is not None:
        try:
            world_obj = get_or_create_world_mesh_object(bpy.context)
            storage = session.get_storage()
            v_count, f_count = update_world_mesh(
                world_obj,
                latest_world_mesh,
                skip_string_attributes=True,
                storage=storage,
            )
            if props:
                props.point_count = v_count
                props.faces_count = f_count
                props.last_update_info = f"World Mesh updated: {v_count:,} vertices, {f_count:,} faces"
                props.is_streaming = False
            if _progress_reporter is not None:
                _progress_reporter.update(_progress_reporter.total, _progress_reporter.total, message=f"Mesh ready ({v_count:,} v, {f_count:,} f)")
        except Exception as e:
            logger.error(f"Failed to inject WorldMesh into Blender: {e}")
        finally:
            _close_progress_reporter(delay_sec=1.5)
    elif needs_voxel_sync:
        try:
            storage = session.get_storage()
            if storage is not None:
                world_obj = get_or_create_world_mesh_object(bpy.context)
                try:
                    from ...bridge.point_cloud import ensure_voxel_child_cloud
                except (ImportError, ValueError):
                    from bridge.point_cloud import ensure_voxel_child_cloud
                ensure_voxel_child_cloud(world_obj, storage=storage, origin_centered=True, initial_hidden=True)
        except Exception as e:
            logger.debug(f"Failed syncing voxel cloud on event: {e}")

    # If session is disconnected or ended, unregister timer cleanly
    if not session.is_active or (props and not props.is_connected and props.connection_status.startswith("DISCONNECTED")):
        stop_sync_timer()
        return None

    return 0.016  # ~60 fps poll interval


class MOZI_OT_sync_connect(bpy.types.Operator):
    """Connect to Minecraft Live Sync streaming server."""
    bl_idname = "mozi.sync_connect"
    bl_label = "Connect"
    bl_description = "Connect to Minecraft Live Sync WebSocket Server"

    def execute(self, context):
        if not is_sync_available():
            self.report({'ERROR'}, "Native libmtk core is missing or not installed!")
            return {'CANCELLED'}

        props = _get_active_props(context)
        url = props.url if props else "ws://127.0.0.1:8765"

        # Attempt to load prebaked model database, texture atlas, and biome resolver
        try:
            from ...utils.system import get_prefs
        except (ImportError, ValueError):
            from utils.system import get_prefs
        prefs = get_prefs(context)
        model_db = load_model_database_from_cache(prefs)
        atlas = load_atlas_from_cache(prefs)
        biome_resolver = load_biome_resolver_from_cache(prefs)

        session = get_sync_bridge_session()
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

        start_sync_timer()
        self.report({'INFO'}, f"Connecting to Live Sync at {url}")
        return {'FINISHED'}


class MOZI_OT_sync_disconnect(bpy.types.Operator):
    """Disconnect from Minecraft Live Sync streaming server."""
    bl_idname = "mozi.sync_disconnect"
    bl_label = "Disconnect"
    bl_description = "Disconnect Live Sync session and stop background listener"

    def execute(self, context):
        stop_sync_timer()
        session = get_sync_bridge_session()
        session.stop()

        props = _get_active_props(context)
        if props:
            props.is_connected = False
            props.connection_status = "DISCONNECTED"
            props.validation_info = "Disconnected"
            props.is_streaming = False

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

        props = getattr(context.scene, "mozi_sync", None)
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

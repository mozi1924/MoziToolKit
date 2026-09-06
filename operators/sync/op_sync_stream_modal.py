"""
Modal Stream Runner & User Interaction Lock for Live Sync Full Synchronization.
Absorbs user interaction during full sync / chunk streaming to prevent scene corruption,
while allowing real-time progressive mesh building and 3D Viewport updates.
"""

from __future__ import annotations

import logging
import time
from typing import Optional
import bpy

from ...pipeline.progress import ProgressBar

logger = logging.getLogger("MoziToolKit.LiveSync.Modal")


class MOZI_OT_sync_stream_runner(bpy.types.Operator):
    """Modal operator locking user interaction during Live Sync streaming and full world build."""

    bl_idname = "mozi.sync_stream_runner"
    bl_label = "Live Sync Stream Runner"
    bl_options = {"INTERNAL"}

    target_container: bpy.props.StringProperty(name="Target Container", default="")

    _active_modal: Optional[MOZI_OT_sync_stream_runner] = None
    _active_containers: set[str] = set()

    @classmethod
    def is_running(cls) -> bool:
        return cls._active_modal is not None

    def invoke(self, context, event):
        # Register this container as active streaming
        target_name = self.target_container
        if not target_name:
            target_obj_guess = None
            try:
                from ...utils.live_sync.session import get_target_world_object
                target_obj_guess = get_target_world_object(context)
            except Exception:
                pass
            if target_obj_guess:
                target_name = target_obj_guess.name
                self.target_container = target_name

        if target_name:
            MOZI_OT_sync_stream_runner._active_containers.add(target_name)
            target_obj = bpy.data.objects.get(target_name)
            if target_obj and hasattr(target_obj, "mozi_sync"):
                target_obj.mozi_sync.is_locked = True
        elif hasattr(context.scene, "mozi_sync"):
            context.scene.mozi_sync.is_locked = True

        if MOZI_OT_sync_stream_runner._active_modal is not None:
            # Already running modal lock, container registered
            return {"RUNNING_MODAL"}

        # In headless / background mode, do not invoke modal window events
        is_headless = getattr(bpy.app, "background", False) or not getattr(context, "window", None)
        if is_headless:
            return {"FINISHED"}

        MOZI_OT_sync_stream_runner._active_modal = self
        self._timer = context.window_manager.event_timer_add(0.015, window=context.window)
        context.window_manager.modal_handler_add(self)

        try:
            context.window_manager.cursor_set_wait()
        except Exception:
            pass

        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        try:
            from ...utils.live_sync.session import get_active_session_manager, get_active_sync_props, get_target_world_object
        except (ImportError, ValueError):
            from utils.live_sync.session import get_active_session_manager, get_active_sync_props, get_target_world_object

        session_mgr = get_active_session_manager()

        # Check all tracked streaming containers
        still_active = set()
        for name in list(MOZI_OT_sync_stream_runner._active_containers):
            s = session_mgr.get_session(name)
            if s and s.is_streaming:
                still_active.add(name)
            else:
                # Unset lock for this finished container
                c_obj = bpy.data.objects.get(name)
                if c_obj and hasattr(c_obj, "mozi_sync"):
                    c_obj.mozi_sync.is_locked = False

        # Also check any other session that might have started streaming
        for s in session_mgr.get_all_sessions():
            if s.is_streaming:
                still_active.add(s.target_object_name)

        MOZI_OT_sync_stream_runner._active_containers = still_active

        # If no session is streaming anymore, immediately unlock and finish modal
        if not still_active:
            self._cleanup(context)
            return {"FINISHED"}

        # 1. User cooperative cancellation on ESC
        if event.type == "ESC":
            for s in session_mgr.get_all_sessions():
                if s.is_streaming:
                    s.cancel_streaming(reason="Cancelled by user")
            self._cleanup(context)
            ProgressBar.cancel("Sync cancelled by user.", context=context)
            self.report({'WARNING'}, "Live Sync build cancelled by user.")
            return {"CANCELLED"}

        # 2. Timer Tick: Monitor streaming status
        if event.type == "TIMER":
            if not MOZI_OT_sync_stream_runner._active_containers:
                self._cleanup(context)
                return {"FINISHED"}

            # Keep forcing Object Mode if user attempts mode switch
            if context.mode != "OBJECT":
                try:
                    bpy.ops.object.mode_set(mode='OBJECT')
                except Exception:
                    pass

            return {"RUNNING_MODAL"}

        # 3. Allow 3D Viewport navigation so the user can inspect the world building in real-time
        if event.type in {
            'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE',
            'TRACKPADPAN', 'TRACKPADZOOM', 'NDOF_MOTION'
        }:
            return {"PASS_THROUGH"}

        # 4. User interaction lock: Absorb scene modification clicks and keys
        return {"RUNNING_MODAL"}

    def _cleanup(self, context):
        MOZI_OT_sync_stream_runner._active_modal = None
        if hasattr(self, "_timer") and self._timer and hasattr(context, "window_manager") and context.window_manager:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None

        if hasattr(context, "window_manager") and context.window_manager:
            try:
                context.window_manager.cursor_set_restore()
            except Exception:
                pass

        for name in list(MOZI_OT_sync_stream_runner._active_containers):
            target_obj = bpy.data.objects.get(name)
            if target_obj and hasattr(target_obj, "mozi_sync"):
                target_obj.mozi_sync.is_locked = False
        MOZI_OT_sync_stream_runner._active_containers.clear()

        if hasattr(context, "scene") and hasattr(context.scene, "mozi_sync"):
            context.scene.mozi_sync.is_locked = False


def start_stream_modal_lock(target_container_name: str = "") -> None:
    """Helper to initiate modal user interaction lock if not already running."""
    is_headless = getattr(bpy.app, "background", False) or not getattr(bpy.context, "window", None)
    if is_headless:
        return
    try:
        bpy.ops.mozi.sync_stream_runner("INVOKE_DEFAULT", target_container=target_container_name)
    except Exception as e:
        logger.debug(f"Failed to start stream modal lock: {e}")

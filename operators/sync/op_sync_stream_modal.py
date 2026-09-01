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

    @classmethod
    def is_running(cls) -> bool:
        return cls._active_modal is not None

    def invoke(self, context, event):
        if MOZI_OT_sync_stream_runner._active_modal is not None:
            # Already running modal lock
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

        target_obj = bpy.data.objects.get(self.target_container) if self.target_container else None
        if target_obj and hasattr(target_obj, "mozi_sync"):
            target_obj.mozi_sync.is_locked = True
        elif hasattr(context.scene, "mozi_sync"):
            context.scene.mozi_sync.is_locked = True

        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        try:
            from ...utils.live_sync.session_manager import get_active_session_manager, get_active_sync_props, get_target_world_object
        except (ImportError, ValueError):
            from utils.live_sync.session_manager import get_active_session_manager, get_active_sync_props, get_target_world_object

        session_mgr = get_active_session_manager()
        target_obj = bpy.data.objects.get(self.target_container) if self.target_container else None
        if not target_obj:
            target_obj = get_target_world_object(context)
        session = session_mgr.get_session(target_obj.name) if target_obj else None
        props = get_active_sync_props(context, target_obj=target_obj)

        # If streaming finished or session is invalid, immediately unlock and finish
        if not session or not session.is_streaming:
            self._cleanup(context)
            if props:
                props.is_locked = False
            return {"FINISHED"}

        # 1. User cooperative cancellation on ESC
        if event.type == "ESC":
            if session:
                session.is_streaming = False
                session.pending_full_sync_request = False
            self._cleanup(context)
            if props:
                props.is_locked = False
                props.validation_info = "Streaming cancelled by user."
            ProgressBar.cancel("Sync cancelled by user.", context=context)
            self.report({'WARNING'}, "Live Sync full build cancelled by user.")
            return {"CANCELLED"}

        # 2. Timer Tick: Monitor streaming status
        if event.type == "TIMER":
            if not session or not session.is_streaming:
                self._cleanup(context)
                if props:
                    props.is_locked = False
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

        target_obj = bpy.data.objects.get(self.target_container) if self.target_container else None
        if target_obj and hasattr(target_obj, "mozi_sync"):
            target_obj.mozi_sync.is_locked = False
        elif hasattr(context, "scene") and hasattr(context.scene, "mozi_sync"):
            context.scene.mozi_sync.is_locked = False


def start_stream_modal_lock(target_container_name: str = "") -> None:
    """Helper to initiate modal user interaction lock if not already running."""
    if MOZI_OT_sync_stream_runner.is_running():
        return
    is_headless = getattr(bpy.app, "background", False) or not getattr(bpy.context, "window", None)
    if is_headless:
        return
    try:
        bpy.ops.mozi.sync_stream_runner("INVOKE_DEFAULT", target_container=target_container_name)
    except Exception as e:
        logger.debug(f"Failed to start stream modal lock: {e}")

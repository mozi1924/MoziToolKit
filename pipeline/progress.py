"""
Progress Protocol and Native Status Bar Progress Bar Module for MoziToolKit.

Defines the ProgressUpdate data structure and the global ProgressBar manager
that integrates directly with Blender's native STATUSBAR_HT_header using
layout.progress(type='BAR') to render render-like progress bars at the bottom
status bar of Blender.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
import bpy

logger = logging.getLogger("MoziToolKit.Progress")


@dataclass
class ProgressUpdate:
    """Represents a fine-grained progress update with normalized fraction."""

    current: float
    total: float
    message: str = ""
    fraction: float = 0.0

    def __post_init__(self):
        if self.total > 0:
            self.fraction = max(0.0, min(1.0, float(self.current) / float(self.total)))
        else:
            self.fraction = 0.0


class ProgressBar:
    """
    Global native Status Bar progress manager for MoziToolKit.
    Integrates directly with Blender's native STATUSBAR_HT_header using layout.progress(type='BAR')
    to render render-like progress bars at the bottom status bar of Blender.
    """

    _is_active: bool = False
    _title: str = "MoziToolKit"
    _current: float = 0.0
    _total: float = 100.0
    _fraction: float = 0.0
    _message: str = ""
    _dismiss_timer_registered: bool = False
    _is_header_hooked: bool = False

    @classmethod
    def is_active(cls) -> bool:
        return cls._is_active

    @classmethod
    def get_fraction(cls) -> float:
        return cls._fraction

    @classmethod
    def get_display_text(cls) -> str:
        pct = int(cls._fraction * 100.0)
        if cls._message:
            return f"{cls._title}: {cls._message} ({pct}%)"
        return f"{cls._title}: {pct}%"

    @classmethod
    def begin(
        cls,
        title: str = "MoziToolKit",
        total: float = 100.0,
        message: str = "",
        context: Optional[bpy.types.Context] = None,
    ) -> None:
        """Activate progress bar with initial title, total units, and optional status message."""
        cls._cancel_pending_dismiss()
        cls._title = title or "MoziToolKit"
        cls._current = 0.0
        cls._total = max(1.0, float(total))
        cls._fraction = 0.0
        cls._message = message
        cls._is_active = True

        ctx = context or getattr(bpy, "context", None)
        if ctx and hasattr(ctx, "window_manager") and ctx.window_manager:
            try:
                ctx.window_manager.progress_begin(0, 100)
            except Exception:
                pass

        cls._sync_blender_ui(ctx)

    @classmethod
    def update(
        cls,
        current: float,
        total: Optional[float] = None,
        message: Optional[str] = None,
        context: Optional[bpy.types.Context] = None,
    ) -> None:
        """Update current progress count, total, and message."""
        if total is not None and total > 0:
            cls._total = float(total)
        cls._current = float(current)
        if cls._total > 0:
            cls._fraction = max(0.0, min(1.0, cls._current / cls._total))
        else:
            cls._fraction = 0.0

        if message is not None:
            cls._message = message

        if not cls._is_active:
            cls._is_active = True

        ctx = context or getattr(bpy, "context", None)
        cls._sync_blender_ui(ctx)

    @classmethod
    def step(
        cls,
        delta: float = 1.0,
        message: Optional[str] = None,
        context: Optional[bpy.types.Context] = None,
    ) -> None:
        """Increment progress by delta units."""
        cls.update(cls._current + delta, message=message, context=context)

    @classmethod
    def finish(
        cls,
        message: str = "Complete",
        context: Optional[bpy.types.Context] = None,
        auto_dismiss_delay: float = 0.8,
    ) -> None:
        """Mark progress as completed and schedule automatic dismissal."""
        cls.update(cls._total, message=message, context=context)

        def dismiss():
            cls.end(context)
            return None

        if auto_dismiss_delay > 0 and hasattr(bpy.app, "timers"):
            cls._dismiss_timer_registered = True
            bpy.app.timers.register(dismiss, first_interval=auto_dismiss_delay)
        else:
            cls.end(context)

    @classmethod
    def cancel(
        cls,
        message: str = "Cancelled",
        context: Optional[bpy.types.Context] = None,
    ) -> None:
        """Cancel active progress bar and hide immediately."""
        cls._message = message
        cls._sync_blender_ui(context)
        cls.end(context)

    @classmethod
    def end(cls, context: Optional[bpy.types.Context] = None) -> None:
        """Deactivate progress bar and clear Blender status bar / cursor state."""
        cls._cancel_pending_dismiss()
        cls._is_active = False
        cls._fraction = 0.0
        cls._message = ""

        ctx = context or getattr(bpy, "context", None)
        if ctx:
            if hasattr(ctx, "window_manager") and ctx.window_manager:
                try:
                    ctx.window_manager.progress_end()
                except Exception:
                    pass
            if hasattr(ctx, "workspace") and ctx.workspace:
                try:
                    ctx.workspace.status_text_set(None)
                except Exception:
                    pass

        cls._tag_redraw(ctx)

    @classmethod
    def _cancel_pending_dismiss(cls) -> None:
        cls._dismiss_timer_registered = False

    @classmethod
    def _sync_blender_ui(cls, context: Optional[bpy.types.Context] = None) -> None:
        ctx = context or getattr(bpy, "context", None)
        pct = int(cls._fraction * 100.0)
        if ctx:
            if hasattr(ctx, "window_manager") and ctx.window_manager:
                try:
                    ctx.window_manager.progress_update(pct)
                except Exception:
                    pass
            if hasattr(ctx, "workspace") and ctx.workspace:
                try:
                    ctx.workspace.status_text_set(cls.get_display_text())
                except Exception:
                    pass
        cls._tag_redraw(ctx)

    @classmethod
    def _tag_redraw(cls, context: Optional[bpy.types.Context] = None) -> None:
        ctx = context or getattr(bpy, "context", None)
        if not ctx:
            return
        wm = getattr(ctx, "window_manager", None)
        if wm and hasattr(wm, "windows"):
            try:
                for window in wm.windows:
                    if hasattr(window, "screen") and window.screen:
                        for area in window.screen.areas:
                            if area.type in ("STATUSBAR", "VIEW_3D", "PROPERTIES"):
                                area.tag_redraw()
            except Exception:
                pass


def draw_statusbar_progress(self, context):
    """Native Blender STATUSBAR_HT_header draw hook for progress bar."""
    if ProgressBar.is_active():
        layout = self.layout
        row = layout.row(align=True)
        # Render native progress bar widget
        text = ProgressBar.get_display_text()
        row.progress(factor=ProgressBar.get_fraction(), text=text, type="BAR")


def register_progress_header():
    """Register status bar header hook with Blender."""
    if not ProgressBar._is_header_hooked and hasattr(bpy.types, "STATUSBAR_HT_header"):
        try:
            bpy.types.STATUSBAR_HT_header.append(draw_statusbar_progress)
            ProgressBar._is_header_hooked = True
        except Exception as e:
            logger.debug(f"Failed to append to STATUSBAR_HT_header: {e}")


def unregister_progress_header():
    """Unregister status bar header hook from Blender."""
    if ProgressBar._is_header_hooked and hasattr(bpy.types, "STATUSBAR_HT_header"):
        try:
            bpy.types.STATUSBAR_HT_header.remove(draw_statusbar_progress)
        except Exception:
            pass
        finally:
            ProgressBar._is_header_hooked = False

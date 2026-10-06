"""
MoziToolKit Blender UI Progress & Status Bar Manager.

Wraps Blender WindowManager progress bar and Workspace status text APIs
with robust RAII exception safety, preventing frozen progress indicators.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator, Optional

try:
    import bpy
except ImportError:
    bpy = None

try:
    from ..bridge.progress import ProgressReport
except (ImportError, ValueError):
    from bridge.progress import ProgressReport

logger = logging.getLogger("MoziToolKit.Utils.Progress")


class BlenderProgressReporter:
    """
    Manages Blender's native status bar progress bar (`wm.progress_*`)
    and status text (`workspace.status_text_set`).
    """

    def __init__(
        self,
        context: Optional[bpy.types.Context] = None,
        total: int = 100,
        title: str = "MoziToolKit",
    ) -> None:
        self.context = context or (bpy.context if bpy is not None else None)
        self.total = max(1, total)
        self.title = title
        self._is_active = False

    def start(self, total: Optional[int] = None) -> None:
        """Initializes the window manager progress bar."""
        if self.context is None:
            return

        if total is not None and total > 0:
            self.total = total

        wm = getattr(self.context, "window_manager", None)
        if wm and hasattr(wm, "progress_begin"):
            try:
                wm.progress_begin(0, self.total)
                self._is_active = True
            except Exception as e:
                logger.debug(f"Failed to begin window manager progress: {e}")

    def update(
        self,
        current: int,
        total: Optional[int] = None,
        message: str = "",
    ) -> None:
        """Updates the progress bar fill and status bar description text."""
        if self.context is None:
            return

        if total is not None and total > 0:
            self.total = total

        if not self._is_active:
            self.start(self.total)

        wm = getattr(self.context, "window_manager", None)
        if wm and hasattr(wm, "progress_update"):
            try:
                wm.progress_update(current)
            except Exception:
                pass

        # Workspace status bar text update
        workspace = getattr(self.context, "workspace", None)
        if workspace and hasattr(workspace, "status_text_set"):
            pct = (current / self.total * 100.0) if self.total > 0 else 0.0
            if message:
                text = f"{self.title}: {message} ({current}/{self.total}, {pct:.0f}%)"
            else:
                text = f"{self.title} ({current}/{self.total}, {pct:.0f}%)"
            try:
                workspace.status_text_set(text)
            except Exception:
                pass

        # Trigger area redrawing for status bar & active windows
        self._tag_redraw()

    def _tag_redraw(self) -> None:
        """Forces viewport and status bar redraws to ensure the progress bar reflects immediately."""
        try:
            wm = getattr(self.context, "window_manager", None)
            if not wm and bpy is not None:
                wm = getattr(bpy.context, "window_manager", None)
            if wm:
                for win in getattr(wm, "windows", []):
                    screen = getattr(win, "screen", None)
                    if screen:
                        for area in getattr(screen, "areas", []):
                            if hasattr(area, "type") and area.type in ("STATUSBAR", "INFO", "VIEW_3D"):
                                area.tag_redraw()
        except Exception:
            pass

    def on_progress(self, report: ProgressReport) -> None:
        """Direct bridge callback matching ProgressCallback signature."""
        self.update(report.current, report.total, report.message)

    def close(self) -> None:
        """Terminates the progress report and clears status bar text."""
        if self.context is None:
            return

        wm = getattr(self.context, "window_manager", None)
        if wm and hasattr(wm, "progress_end") and self._is_active:
            try:
                wm.progress_end()
            except Exception:
                pass

        workspace = getattr(self.context, "workspace", None)
        if workspace and hasattr(workspace, "status_text_set"):
            try:
                workspace.status_text_set(None)
            except Exception:
                pass

        self._tag_redraw()
        self._is_active = False


@contextmanager
def blender_progress_scope(
    context: Optional[bpy.types.Context] = None,
    total: int = 100,
    title: str = "MoziToolKit",
) -> Generator[BlenderProgressReporter, None, None]:
    """
    Context manager ensuring progress bars and status bar texts are cleanly
    terminated even if an unhandled exception or user cancellation occurs.
    """
    reporter = BlenderProgressReporter(context=context, total=total, title=title)
    reporter.start()
    try:
        yield reporter
    finally:
        reporter.close()

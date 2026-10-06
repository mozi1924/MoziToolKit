"""
MoziToolKit Asynchronous Modal Worker & Progress Pipeline.

Provides non-blocking background task execution for heavy Rust calculations
(voxel meshing, save scanning, world ingestion) coupled with 60FPS smooth
Blender status bar updates via Modal Operators.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable, Dict, Optional, Tuple

try:
    import bpy
except ImportError:
    bpy = None

try:
    from ..bridge.progress import ProgressReport
    from .progress import BlenderProgressReporter
except (ImportError, ValueError):
    from bridge.progress import ProgressReport
    from utils.progress import BlenderProgressReporter

logger = logging.getLogger("MoziToolKit.Utils.AsyncTask")


class AsyncTask:
    """
    Manages a background worker thread and a thread-safe communication queue.
    Executes heavy calculations outside the Blender UI main thread.
    """

    def __init__(
        self,
        target: Callable[..., Any],
        args: Tuple[Any, ...] = (),
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.queue: queue.Queue = queue.Queue()
        self.result: Any = None
        self.error: Optional[Exception] = None
        self.is_done: bool = False
        self.is_cancelled: bool = False
        self._thread: Optional[threading.Thread] = None

    def _progress_callback(self, report: ProgressReport) -> None:
        if not self.is_cancelled:
            self.queue.put(("PROGRESS", report))

    def _worker_entry(self) -> None:
        try:
            kwargs = dict(self.kwargs)
            kwargs["progress_callback"] = self._progress_callback
            self.result = self.target(*self.args, **kwargs)
        except Exception as e:
            logger.exception("Error in background async worker: %s", e)
            self.error = e
        finally:
            self.is_done = True
            self.queue.put(("DONE", None))

    def start(self) -> None:
        """Starts execution in a daemon background worker thread."""
        self._thread = threading.Thread(target=self._worker_entry, daemon=True)
        self._thread.start()

    def run_sync(self) -> Any:
        """Synchronously executes in the calling thread (for headless/testing)."""
        self._worker_entry()
        if self.error is not None:
            raise self.error
        return self.result

    def cancel(self) -> None:
        """Marks the task as cancelled."""
        self.is_cancelled = True


class ModalTaskRunner:
    """
    Orchestrates the lifecycle of a Blender Modal Operator managing an AsyncTask.
    Dispatches 60FPS progress updates to BlenderProgressReporter and injects results
    safely on the main thread.
    """

    def __init__(
        self,
        operator: Any,
        context: Any,
        task: AsyncTask,
        reporter: Optional[BlenderProgressReporter] = None,
        on_success: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        title: str = "MoziToolKit",
        poll_interval: float = 0.016,
        force_modal: bool = False,
    ) -> None:
        self.operator = operator
        self.context = context
        self.task = task
        self.reporter = reporter or BlenderProgressReporter(context=context, title=title)
        self.on_success = on_success
        self.on_error = on_error
        self.poll_interval = poll_interval
        self.force_modal = force_modal
        self._timer: Optional[Any] = None
        self._cleaned_up: bool = False

    def start(self) -> set[str]:
        """
        Initiates the modal lifecycle. Automatically falls back to synchronous execution
        if running in background / headless CLI mode without a window manager.
        """
        # Headless / CLI fallback
        is_background = False
        if not self.force_modal and bpy is not None and hasattr(bpy, "app"):
            bg_val = getattr(bpy.app, "background", False)
            if isinstance(bg_val, bool):
                is_background = bg_val
        has_window = hasattr(self.context, "window") and self.context.window is not None
        has_wm = hasattr(self.context, "window_manager") and self.context.window_manager is not None

        if (is_background or not has_window or not has_wm) and not self.force_modal:
            logger.debug("Executing task synchronously (headless / background mode).")
            try:
                self.reporter.start()
                res = self.task.run_sync()
                if self.on_success:
                    self.on_success(res)
                return {"FINISHED"}
            except Exception as e:
                if self.on_error:
                    self.on_error(e)
                else:
                    self.operator.report({"ERROR"}, str(e))
                return {"CANCELLED"}
            finally:
                self.cleanup()

        # UI Mode: Launch background thread & register modal event timer
        self.reporter.start()
        self.task.start()

        wm = self.context.window_manager
        self._timer = wm.event_timer_add(self.poll_interval, window=self.context.window)
        wm.modal_handler_add(self.operator)
        return {"RUNNING_MODAL"}

    def modal(self, event: Any) -> set[str]:
        """Handles Blender modal loop events."""
        if event.type == "TIMER":
            # 1. Drain progress reports and update status bar with the latest report
            latest_report: Optional[ProgressReport] = None
            while True:
                try:
                    kind, payload = self.task.queue.get_nowait()
                    if kind == "PROGRESS":
                        latest_report = payload
                except queue.Empty:
                    break

            if latest_report is not None:
                self.reporter.on_progress(latest_report)

            # 2. Check if background thread has finished
            if self.task.is_done:
                self.cleanup()
                if self.task.error is not None:
                    if self.on_error:
                        self.on_error(self.task.error)
                    else:
                        self.operator.report({"ERROR"}, f"Task failed: {self.task.error}")
                    return {"CANCELLED"}

                try:
                    if self.on_success:
                        self.on_success(self.task.result)
                    return {"FINISHED"}
                except Exception as e:
                    logger.exception("Failed during main-thread on_success injection: %s", e)
                    self.operator.report({"ERROR"}, f"Scene injection failed: {e}")
                    return {"CANCELLED"}

            return {"RUNNING_MODAL"}

        if event.type in {"ESC"}:
            logger.info("User cancelled modal task via ESC.")
            self.task.cancel()
            self.cleanup()
            self.operator.report({"WARNING"}, "Operation cancelled by user.")
            return {"CANCELLED"}

        return {"PASS_THROUGH"}

    def cleanup(self) -> None:
        """Safely removes timer and closes progress reporter."""
        if self._cleaned_up:
            return
        self._cleaned_up = True

        if self._timer is not None:
            try:
                wm = getattr(self.context, "window_manager", None)
                if wm and hasattr(wm, "event_timer_remove"):
                    wm.event_timer_remove(self._timer)
            except Exception as e:
                logger.debug("Failed removing modal event timer: %s", e)
            self._timer = None

        if self.reporter is not None:
            try:
                self.reporter.close()
            except Exception as e:
                logger.debug("Failed closing progress reporter: %s", e)

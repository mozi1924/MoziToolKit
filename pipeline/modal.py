"""
Modal Pipeline Runner Module for MoziToolKit.

Provides non-blocking modal execution for long-running pipeline tasks with:
1. Native Blender status bar progress bar (wm.progress_begin / progress_update / progress_end).
2. User input locking (absorbing non-timer, non-ESC events to prevent scene corruption).
3. Graceful cooperative cancellation on ESC key.
4. Automatic fallback to synchronous execution in background / headless test environments.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import bpy
from .context import PipelineContext
from .pipeline import Pipeline
from .progress import ProgressUpdate, ProgressBar
from .step import StepResult, StepStatus


class MOZI_OT_modal_pipeline_runner(bpy.types.Operator):
    """Internal modal operator driving pipeline execution with progress bar and input lock."""

    bl_idname = "mozi.modal_pipeline_runner"
    bl_label = "Mozi Pipeline Runner"
    bl_options = {"INTERNAL"}

    runner_id: bpy.props.StringProperty(name="Runner ID", default="", options={"HIDDEN"})

    _active_runners: Dict[str, Any] = {}

    @classmethod
    def is_running(cls) -> bool:
        """Check whether a modal pipeline runner is currently executing."""
        return bool(cls._active_runners)

    def invoke(self, context, event):
        runner_id = self.runner_id
        runner_data = self._active_runners.get(runner_id)

        if not runner_data:
            self._cleanup(context)
            return {"CANCELLED"}

        wm = context.window_manager
        title = runner_data.get("title", "MoziToolKit")
        ProgressBar.begin(title=title, total=100.0, message="", context=context)
        try:
            wm.cursor_set_wait()
        except Exception:
            pass

        timer = wm.event_timer_add(0.001, window=context.window)
        runner_data["timer"] = timer
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        return self.invoke(context, None)

    def modal(self, context, event):
        runner_id = self.runner_id
        runner_data = self._active_runners.get(runner_id)

        if not runner_data:
            self._cleanup(context)
            return {"CANCELLED"}

        ctx: PipelineContext = runner_data["ctx"]
        generator = runner_data["generator"]
        on_finish = runner_data.get("on_finish")
        title = runner_data.get("title", "MoziToolKit")

        # 1. Cooperative user cancellation on ESC
        if event.type == "ESC":
            ctx.is_cancelled = True
            self._drain_generator(generator)
            ProgressBar.cancel("Operation cancelled by user.", context=context)
            self._cleanup(context)
            res = StepResult.cancelled("Operation cancelled by user.")
            ctx.report("WARNING", res.message)
            if on_finish:
                on_finish(res, ctx)
            for level, msg in ctx.reports:
                self.report({level}, msg)
            return {"CANCELLED"}

        # 2. Timer tick: advance pipeline execution by one chunk
        if event.type == "TIMER":
            try:
                item = next(generator)

                if isinstance(item, ProgressUpdate):
                    pct = int(item.fraction * 100.0)
                    ProgressBar.update(current=pct, total=100.0, message=item.message, context=context)
                    return {"RUNNING_MODAL"}

                elif isinstance(item, StepResult):
                    # ``Pipeline.execute_iter`` yields its final result before
                    # returning. Exhaust it before dropping the last runner
                    # reference, otherwise Python closes the suspended
                    # generator at ``yield last_result`` and a debugger shows
                    # a misleading GeneratorExit.
                    self._drain_generator(generator)
                    ProgressBar.finish(item.message if item.is_success else "Failed", context=context)
                    self._cleanup(context)
                    if on_finish:
                        on_finish(item, ctx)
                    for level, msg in ctx.reports:
                        self.report({level}, msg)
                    return {"FINISHED"} if item.is_success else {"CANCELLED"}

            except StopIteration:
                ProgressBar.finish("Finished", context=context)
                self._cleanup(context)
                res = StepResult.success("Pipeline finished.")
                if on_finish:
                    on_finish(res, ctx)
                for level, msg in ctx.reports:
                    self.report({level}, msg)
                return {"FINISHED"}

            except Exception as e:
                ProgressBar.cancel(f"Error: {e}", context=context)
                self._cleanup(context)
                err_res = StepResult.failed(f"Pipeline error: {e}")
                ctx.report("ERROR", err_res.message)
                if on_finish:
                    on_finish(err_res, ctx)
                for level, msg in ctx.reports:
                    self.report({level}, msg)
                return {"CANCELLED"}

        # 3. Lock user interaction: consume all clicks/keys so scene isn't altered during execution
        return {"RUNNING_MODAL"}

    @staticmethod
    def _drain_generator(generator) -> None:
        """Advance a completed/cancelled pipeline generator to its return."""
        try:
            while True:
                next(generator)
        except StopIteration:
            pass

    def _cleanup(self, context):
        runner_id = self.runner_id
        runner_data = self._active_runners.pop(runner_id, None)

        if runner_data:
            timer = runner_data.get("timer")
            if timer and hasattr(context, "window_manager") and context.window_manager:
                try:
                    context.window_manager.event_timer_remove(timer)
                except Exception:
                    pass

        ProgressBar.end(context=context)

        if hasattr(context, "window_manager") and context.window_manager:
            try:
                context.window_manager.cursor_set_restore()
            except Exception:
                pass


def run_pipeline_modal(
    pipeline: Pipeline,
    context: bpy.types.Context,
    params: Optional[Dict[str, Any]] = None,
    target_objects: Optional[List[bpy.types.Object]] = None,
    on_finish: Optional[Callable[[StepResult, PipelineContext], None]] = None,
    title: str = "MoziToolKit",
) -> Tuple[StepResult, PipelineContext]:
    """
    Execute a pipeline with responsive non-blocking UI modal progress in interactive Blender,
    or execute synchronously when running headless/in unit tests.
    """
    ctx = PipelineContext(
        context=context,
        params=params,
        target_objects=target_objects,
    )

    # Prevent concurrent pipeline executions from corrupting the scene
    if MOZI_OT_modal_pipeline_runner.is_running():
        msg = "Another pipeline operation is currently in progress. Please wait for it to finish or press ESC to cancel."
        ctx.report("WARNING", msg)
        err_res = StepResult.failed(msg)
        if on_finish:
            on_finish(err_res, ctx)
        return err_res, ctx

    # In background mode, headless, or context without active window, run synchronously
    is_headless = getattr(bpy.app, "background", False) or not getattr(context, "window", None)
    if is_headless:
        result = pipeline.execute(ctx)
        if on_finish:
            on_finish(result, ctx)
        return result, ctx

    import uuid
    runner_id = str(uuid.uuid4())
    generator = pipeline.execute_iter(ctx)

    MOZI_OT_modal_pipeline_runner._active_runners[runner_id] = {
        "ctx": ctx,
        "generator": generator,
        "on_finish": on_finish,
        "title": title,
    }

    try:
        bpy.ops.mozi.modal_pipeline_runner("INVOKE_DEFAULT", runner_id=runner_id)
        return StepResult.success("Modal pipeline started."), ctx
    except Exception as e:
        # Clean up runner registration on invocation failure
        MOZI_OT_modal_pipeline_runner._active_runners.pop(runner_id, None)
        # Fallback to sync if modal invocation fails
        result = pipeline.execute(ctx)
        if on_finish:
            on_finish(result, ctx)
        return result, ctx

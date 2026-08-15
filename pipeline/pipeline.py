"""
Pipeline Engine Module for MoziToolKit

Defines the Pipeline class which sequences and executes PipelineStep modules.
"""

from typing import Iterator, List, Optional, Union
from .context import PipelineContext
from .progress import ProgressUpdate
from .step import PipelineStep, StepResult, StepStatus


class Pipeline:
    """Represents a sequential execution pipeline composed of step modules."""

    def __init__(self, name: str, description: str = "", steps: Optional[List[PipelineStep]] = None):
        self.name = name
        self.description = description
        self.steps: List[PipelineStep] = steps or []

    def add_step(self, step: PipelineStep) -> "Pipeline":
        self.steps.append(step)
        return self

    def execute(self, ctx: PipelineContext) -> StepResult:
        if not self.steps:
            return StepResult.skipped(f"Pipeline '{self.name}' has no steps to execute.")

        last_result = StepResult.success()

        for step in self.steps:
            if ctx.is_cancelled:
                cancel_res = StepResult.cancelled("Pipeline execution cancelled by user.")
                ctx.report("WARNING", cancel_res.message)
                return cancel_res

            try:
                res = step.execute(ctx)
                if res.message:
                    level = "INFO" if res.is_success else ("WARNING" if res.status == StepStatus.CANCELLED else "ERROR")
                    ctx.report(level, res.message)

                if res.status == StepStatus.FAILED:
                    return res

                if res.status == StepStatus.CANCELLED:
                    return res

                last_result = res
            except Exception as e:
                err_msg = f"Error in pipeline step '{step.name}': {e}"
                ctx.report("ERROR", err_msg)
                return StepResult.failed(err_msg)

        return last_result

    def execute_iter(self, ctx: PipelineContext) -> Iterator[Union[ProgressUpdate, StepResult]]:
        """Iteratively execute pipeline steps with fine-grained progress and cooperative cancellation."""
        if not self.steps:
            res = StepResult.skipped(f"Pipeline '{self.name}' has no steps to execute.")
            yield res
            return

        num_steps = len(self.steps)
        last_result: StepResult = StepResult.success()

        for step_idx, step in enumerate(self.steps):
            if ctx.is_cancelled:
                cancel_res = StepResult.cancelled("Pipeline execution cancelled by user.")
                ctx.report("WARNING", cancel_res.message)
                yield cancel_res
                return

            step_base_fraction = step_idx / num_steps
            step_weight = 1.0 / num_steps

            try:
                for item in step.execute_iter(ctx):
                    if ctx.is_cancelled:
                        cancel_res = StepResult.cancelled("Pipeline execution cancelled by user.")
                        ctx.report("WARNING", cancel_res.message)
                        yield cancel_res
                        return

                    if isinstance(item, ProgressUpdate):
                        global_fraction = step_base_fraction + item.fraction * step_weight
                        global_update = ProgressUpdate(
                            current=global_fraction * 100.0,
                            total=100.0,
                            message=item.message,
                            fraction=global_fraction,
                        )
                        if ctx.progress_callback:
                            ctx.progress_callback(global_update)
                        yield global_update
                    elif isinstance(item, StepResult):
                        last_result = item
                        if item.message:
                            level = "INFO" if item.is_success else ("WARNING" if item.status == StepStatus.CANCELLED else "ERROR")
                            ctx.report(level, item.message)

                        if item.status in (StepStatus.FAILED, StepStatus.CANCELLED):
                            yield item
                            return
            except Exception as e:
                err_msg = f"Error in pipeline step '{step.name}': {e}"
                ctx.report("ERROR", err_msg)
                yield StepResult.failed(err_msg)
                return

        final_update = ProgressUpdate(
            current=100.0,
            total=100.0,
            message=f"Pipeline '{self.name}' finished.",
            fraction=1.0,
        )
        if ctx.progress_callback:
            ctx.progress_callback(final_update)
        yield final_update
        yield last_result

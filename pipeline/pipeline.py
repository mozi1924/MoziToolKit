"""
Pipeline Engine Module for MoziToolKit

Defines the Pipeline class which sequences and executes PipelineStep modules.
"""

from typing import List, Optional
from .context import PipelineContext
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

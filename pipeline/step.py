"""
Pipeline Step Base Class Module for MoziToolKit

Defines the abstract interface and result status for modular pipeline steps.
"""

from enum import Enum, auto
from typing import Any, Dict
from .context import PipelineContext


class StepStatus(Enum):
    SUCCESS = auto()
    CANCELLED = auto()
    SKIPPED = auto()
    FAILED = auto()


class StepResult:
    """Represents the execution result of a single pipeline step."""

    def __init__(self, status: StepStatus, message: str = "", data: Dict[str, Any] = None):
        self.status = status
        self.message = message
        self.data = data or {}

    @classmethod
    def success(cls, message: str = "", data: Dict[str, Any] = None) -> "StepResult":
        return cls(StepStatus.SUCCESS, message, data)

    @classmethod
    def cancelled(cls, message: str = "") -> "StepResult":
        return cls(StepStatus.CANCELLED, message)

    @classmethod
    def skipped(cls, message: str = "") -> "StepResult":
        return cls(StepStatus.SKIPPED, message)

    @classmethod
    def failed(cls, message: str = "") -> "StepResult":
        return cls(StepStatus.FAILED, message)

    @property
    def is_success(self) -> bool:
        return self.status == StepStatus.SUCCESS


class PipelineStep:
    """Abstract Base Class for all pipeline steps/modules."""

    name: str = "Base Step"
    description: str = "Base pipeline step module"

    def __init__(self, **params):
        self.params = params

    def get_param(self, ctx: PipelineContext, key: str, default: Any = None) -> Any:
        if key in self.params:
            return self.params[key]
        return ctx.get_param(key, default)

    def execute(self, ctx: PipelineContext) -> StepResult:
        raise NotImplementedError("PipelineStep subclasses must implement execute()")

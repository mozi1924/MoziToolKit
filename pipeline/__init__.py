"""
MoziToolKit Pipeline Framework Package

Provides modular step building blocks (PipelineStep) and preset pipelines (Pipeline).
"""

from .context import PipelineContext
from .pipeline import Pipeline
from .progress import ProgressUpdate
from .step import PipelineStep, StepResult, StepStatus
from .modal import MOZI_OT_modal_pipeline_runner, run_pipeline_modal
from .presets import PRESET_PIPELINES, get_preset_pipeline, run_preset_pipeline

__all__ = [
    "PipelineContext",
    "Pipeline",
    "ProgressUpdate",
    "PipelineStep",
    "StepResult",
    "StepStatus",
    "MOZI_OT_modal_pipeline_runner",
    "run_pipeline_modal",
    "PRESET_PIPELINES",
    "get_preset_pipeline",
    "run_preset_pipeline",
]

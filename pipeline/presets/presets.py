"""
Preset Pipelines Registry Module for MoziToolKit

Defines and registers hardcoded preset pipelines corresponding to plugin features.
"""

from typing import Dict, List, Optional, Tuple
import bpy
from ..context import PipelineContext
from ..pipeline import Pipeline
from ..step import StepResult, StepStatus
from ..steps import (
    AdaptivePixelSplitStep,
    AutoExtrudeRepairStep,
    ClearCustomNormalsStep,
    RandomExtrudeStep,
    ScaleUVStep,
    SelectHardEdgesStep,
    SelectTransparentFacesStep,
    TextureInterpolationStep,
    StepReplaceMaterial,
)


def create_preset_pipelines() -> Dict[str, Pipeline]:
    """Instantiate all hardcoded preset pipelines."""
    return {
        "adaptive_pixel_split": Pipeline(
            name="Adaptive Pixel Split Preset",
            description="Pipeline for adaptive pixel splitting faces according to texture resolution",
            steps=[AdaptivePixelSplitStep()],
        ),
        "auto_extrude_repair": Pipeline(
            name="Auto Extrude Repair Preset",
            description="Pipeline for repairing side face UVs and Mean Crease from extrusion",
            steps=[AutoExtrudeRepairStep()],
        ),
        "clear_custom_normals": Pipeline(
            name="Clear Custom Normals Preset",
            description="Pipeline for clearing custom split normals and custom_normal attributes",
            steps=[ClearCustomNormalsStep()],
        ),
        "random_extrude": Pipeline(
            name="Random Extrude Preset",
            description="Pipeline for extruding selected faces individually with random heights and UV repair",
            steps=[RandomExtrudeStep()],
        ),
        "select_hard_edges": Pipeline(
            name="Select Hard Edges Preset",
            description="Pipeline for selecting boundary and sharp threshold edges",
            steps=[SelectHardEdgesStep()],
        ),
        "set_texture_interpolation_closest": Pipeline(
            name="Texture Interpolation Preset",
            description="Pipeline for setting image texture node interpolation to Closest",
            steps=[TextureInterpolationStep()],
        ),
        "scale_uv": Pipeline(
            name="Scale UV Preset",
            description="Pipeline for scaling individual UV faces in place",
            steps=[ScaleUVStep()],
        ),
        "select_transparent_faces": Pipeline(
            name="Select Transparent Faces Preset",
            description="Pipeline for selecting faces mapped to transparent texture pixels",
            steps=[SelectTransparentFacesStep()],
        ),
        "replace_material": Pipeline(
            name="Replace Material Preset",
            description="Pipeline for replacing materials from Minecraft Java Resource Pack",
            steps=[StepReplaceMaterial()],
        ),
    }



PRESET_PIPELINES: Dict[str, Pipeline] = create_preset_pipelines()


def get_preset_pipeline(name: str) -> Optional[Pipeline]:
    """Retrieve a registered preset pipeline by name."""
    return PRESET_PIPELINES.get(name)


def run_preset_pipeline(
    name: str,
    context: bpy.types.Context,
    params: Optional[dict] = None,
    target_objects: Optional[List[bpy.types.Object]] = None,
) -> Tuple[StepResult, PipelineContext]:
    """
    Run a hardcoded preset pipeline by name with given parameters.

    :param name: Identifier of the preset pipeline.
    :param context: Current Blender context.
    :param params: Optional parameters dictionary overriding step defaults.
    :param target_objects: Optional explicit target objects list.
    :return: Tuple of (StepResult, PipelineContext)
    """
    pipeline = get_preset_pipeline(name)
    ctx = PipelineContext(context=context, params=params, target_objects=target_objects)

    if not pipeline:
        err_msg = f"Preset pipeline '{name}' not found."
        ctx.report("ERROR", err_msg)
        return StepResult.failed(err_msg), ctx

    result = pipeline.execute(ctx)
    return result, ctx

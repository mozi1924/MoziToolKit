"""
Texture Interpolation Pipeline Step
"""

import bpy
from ..context import PipelineContext
from ..step import PipelineStep, StepResult

try:
    from ...utils.materials import set_materials_texture_interpolation_closest
except (ImportError, ValueError):
    from utils.materials import set_materials_texture_interpolation_closest


class TextureInterpolationStep(PipelineStep):
    name = "Set Image Texture Interpolation"
    description = "Set interpolation of all image texture nodes in selected objects' materials to Closest"

    def execute(self, ctx: PipelineContext) -> StepResult:
        targets = ctx.target_objects
        if not targets:
            return StepResult.cancelled("No objects selected.")

        mat_count, node_count = set_materials_texture_interpolation_closest(targets)

        if mat_count == 0:
            msg = "No materials found on selected objects"
        elif node_count == 0:
            msg = f"Processed {mat_count} material(s), all image texture nodes are already Closest"
        else:
            msg = f"Set {node_count} image texture node(s) to Closest interpolation across {mat_count} material(s)"

        ctx.set_data("texture_interpolation_stats", {"materials": mat_count, "nodes": node_count})
        return StepResult.success(msg, {"material_count": mat_count, "node_count": node_count})

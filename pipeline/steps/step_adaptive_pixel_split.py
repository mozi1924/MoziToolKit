"""
Adaptive Pixel Split Pipeline Step
"""

import bpy
from ..context import PipelineContext
from ..step import PipelineStep, StepResult

try:
    from ...utils.mesh import set_select_mode
    from ...utils.pixel_split import SplitConfig, process_adaptive_pixel_split
except (ImportError, ValueError):
    from utils.mesh import set_select_mode
    from utils.pixel_split import SplitConfig, process_adaptive_pixel_split


class AdaptivePixelSplitStep(PipelineStep):
    name = "Adaptive Pixel Split"
    description = "Subdivide or adjust mesh faces to match texture pixel resolution"

    def execute(self, ctx: PipelineContext) -> StepResult:
        mesh_objs = ctx.target_objects
        if not mesh_objs:
            return StepResult.cancelled("No mesh objects selected.")

        selection_scope = self.get_param(ctx, "selection_scope", "SELECTED")
        auto_resolution = self.get_param(ctx, "auto_resolution", True)
        resolution_width = self.get_param(ctx, "resolution_width", 64)
        resolution_height = self.get_param(ctx, "resolution_height", 64)
        pixels_per_face = self.get_param(ctx, "pixels_per_face", 1)

        initial_mode = ctx.context.mode

        if initial_mode != "EDIT_MESH":
            if ctx.context.active_object not in mesh_objs:
                ctx.context.view_layer.objects.active = mesh_objs[0]
            bpy.ops.object.mode_set(mode="EDIT")

        set_select_mode(ctx.context, "FACE")

        config = SplitConfig(
            auto_resolution=auto_resolution,
            manual_resolution=(resolution_width, resolution_height),
            pixels_per_face=pixels_per_face,
            selection_scope=selection_scope,
        )

        total_initial = 0
        total_final = 0

        for obj in mesh_objs:
            stats = process_adaptive_pixel_split(ctx.context, config, target_obj=obj)
            total_initial += stats.get("initial_faces", 0)
            total_final += stats.get("final_faces", 0)

        if initial_mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="OBJECT")

        msg = f"Adaptive Pixel Split ({len(mesh_objs)} mesh object(s)): {total_initial} face(s) -> {total_final} face(s)"
        ctx.set_data("pixel_split_stats", {"initial": total_initial, "final": total_final})
        return StepResult.success(msg, {"initial_faces": total_initial, "final_faces": total_final})

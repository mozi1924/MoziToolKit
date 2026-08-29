"""
Adaptive Pixel Split Pipeline Step
"""

from typing import Iterator, Union
import bpy
from ..context import PipelineContext
from ..progress import ProgressUpdate
from ..step import PipelineStep, StepResult

from ...utils.mesh import set_select_mode
from ...utils.pixel_split import SplitConfig, process_adaptive_pixel_split


class AdaptivePixelSplitStep(PipelineStep):
    name = "Adaptive Pixel Split"
    description = "Subdivide or adjust mesh faces to match texture pixel resolution"

    def execute_iter(self, ctx: PipelineContext) -> Iterator[Union[ProgressUpdate, StepResult]]:
        mesh_objs = ctx.target_objects
        if not mesh_objs:
            yield StepResult.cancelled("No mesh objects selected.")
            return

        selection_scope = self.get_param(ctx, "selection_scope", "SELECTED")
        auto_resolution = self.get_param(ctx, "auto_resolution", True)
        resolution_width = self.get_param(ctx, "resolution_width", 64)
        resolution_height = self.get_param(ctx, "resolution_height", 64)
        pixels_per_face = self.get_param(ctx, "pixels_per_face", 1)

        initial_active_obj = ctx.context.view_layer.objects.active
        initial_mode = initial_active_obj.mode if initial_active_obj else "OBJECT"

        if initial_mode != "EDIT":
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
        num_objs = len(mesh_objs)

        try:
            for idx, obj in enumerate(mesh_objs):
                if ctx.is_cancelled:
                    yield StepResult.cancelled("Adaptive pixel split cancelled by user.")
                    return

                yield ProgressUpdate(
                    current=idx,
                    total=num_objs,
                    message=f"Adaptive pixel split: processing {obj.name} ({idx + 1}/{num_objs})...",
                )

                stats = process_adaptive_pixel_split(ctx.context, config, target_obj=obj)
                total_initial += stats.get("initial_faces", 0)
                total_final += stats.get("final_faces", 0)
        finally:
            if initial_mode != "EDIT":
                try:
                    bpy.ops.object.mode_set(mode=initial_mode)
                except Exception:
                    pass
            if initial_active_obj and initial_active_obj.name in ctx.context.view_layer.objects:
                try:
                    ctx.context.view_layer.objects.active = initial_active_obj
                except Exception:
                    pass

        ctx.set_data("pixel_split_stats", {"initial": total_initial, "final": total_final})
        yield StepResult.success(
            f"Adaptive pixel split: {total_initial} face(s) -> {total_final} face(s)",
            {"initial_faces": total_initial, "final_faces": total_final},
        )

"""
Random Extrude Pipeline Step
"""

import bmesh
import bpy
from ..context import PipelineContext
from ..step import PipelineStep, StepResult

try:
    from ...utils.mesh import poll_edit_mesh, process_random_extrude
except (ImportError, ValueError):
    from utils.mesh import poll_edit_mesh, process_random_extrude


class RandomExtrudeStep(PipelineStep):
    name = "Random Extrude"
    description = "Extrude selected faces individually along face normals with random height and UV repair"

    def execute(self, ctx: PipelineContext) -> StepResult:
        if not poll_edit_mesh(ctx.context):
            return StepResult.cancelled("Must be in Edit Mode with a Mesh object active.")

        obj = ctx.active_object
        if not obj or obj.type != "MESH":
            return StepResult.cancelled("No active mesh object.")

        min_height = self.get_param(ctx, "min_height", 0.1)
        max_height = self.get_param(ctx, "max_height", 1.0)
        seed = self.get_param(ctx, "seed", 0)
        noise_mode = self.get_param(ctx, "noise_mode", "RANDOM")
        noise_scale = self.get_param(ctx, "noise_scale", 1.0)
        repair_uv = self.get_param(ctx, "repair_uv", True)
        uv_mode = self.get_param(ctx, "uv_mode", "SMART")
        add_mean_crease = self.get_param(ctx, "add_mean_crease", False)
        crease_value = self.get_param(ctx, "crease_value", 1.0)

        bm = bmesh.from_edit_mesh(obj.data)

        extruded_count, repaired_count = process_random_extrude(
            bm,
            min_height=min_height,
            max_height=max_height,
            seed=seed,
            noise_mode=noise_mode,
            noise_scale=noise_scale,
            repair_uv=repair_uv,
            uv_mode=uv_mode,
            add_crease=add_mean_crease,
            crease_val=crease_value,
        )

        if extruded_count > 0:
            bmesh.update_edit_mesh(obj.data)
            msg = f"Random extruded {extruded_count} face(s) (repaired {repaired_count} side face UV/creases)"
        else:
            msg = "No selected faces to extrude"

        ctx.set_data("extruded_faces_count", extruded_count)
        ctx.set_data("repaired_faces_count", repaired_count)
        return StepResult.success(msg, {"extruded_count": extruded_count, "repaired_count": repaired_count})

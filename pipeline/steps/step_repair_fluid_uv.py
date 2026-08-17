"""
Repair Fluid UV Pipeline Step
"""

import bpy
from ..context import PipelineContext
from ..step import PipelineStep, StepResult

try:
    from ...utils.mesh import (
        bmesh_context,
        poll_edit_mesh,
        repair_face_fluid_uv,
        process_mesh_fluid_uv_repairs,
    )
except (ImportError, ValueError):
    from utils.mesh import (
        bmesh_context,
        poll_edit_mesh,
        repair_face_fluid_uv,
        process_mesh_fluid_uv_repairs,
    )


class RepairFluidUVStep(PipelineStep):
    name = "Repair Fluid UV"
    description = "Repair inverted UV height mapping on sloped fluid side faces"

    def execute(self, ctx: PipelineContext) -> StepResult:
        if not poll_edit_mesh(ctx.context):
            return StepResult.cancelled("Must be in Edit Mode with a Mesh object active.")

        selection_scope = self.get_param(ctx, "selection_scope", "SELECTED")

        repaired_count = 0
        with bmesh_context(ctx.context) as (obj, bm):
            uv_layer = bm.loops.layers.uv.verify()

            selected_faces = [f for f in bm.faces if f.select]
            if selection_scope == "SELECTED":
                if not selected_faces:
                    return StepResult.cancelled("No faces selected to repair fluid UV.")
                target_faces = selected_faces
                force_repair = True
            elif selection_scope == "ALL":
                target_faces = list(bm.faces)
                force_repair = False
            else:  # AUTO
                target_faces = selected_faces if selected_faces else list(bm.faces)
                force_repair = bool(selected_faces)

            repaired_count = process_mesh_fluid_uv_repairs(
                bm=bm,
                uv_layer=uv_layer,
                target_faces=target_faces,
                force=force_repair,
            )

        if repaired_count == 0:
            if selection_scope == "SELECTED":
                msg = "No sloped fluid UV issues found or selected faces are not suitable quads."
            else:
                msg = "No inverted fluid UV faces detected in mesh."
            ctx.set_data("repaired_fluid_uv_count", 0)
            return StepResult.success(msg, {"repaired_faces_count": 0})

        msg = f"Successfully repaired fluid UV for {repaired_count} face(s)."
        ctx.set_data("repaired_fluid_uv_count", repaired_count)
        return StepResult.success(msg, {"repaired_faces_count": repaired_count})

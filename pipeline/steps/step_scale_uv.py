"""
Scale UV Faces Pipeline Step
"""

import bpy
from ..context import PipelineContext
from ..step import PipelineStep, StepResult

from ...utils.mesh import bmesh_context, poll_edit_mesh, get_face_uv_center


class ScaleUVStep(PipelineStep):
    name = "Scale UV Faces"
    description = "Scale individual UV faces in place around their UV center"

    def execute(self, ctx: PipelineContext) -> StepResult:
        if not poll_edit_mesh(ctx.context):
            return StepResult.cancelled("Must be in Edit Mode with a Mesh object active.")

        scale_factor = self.get_param(ctx, "scale_factor", 0.8)
        selection_scope = self.get_param(ctx, "selection_scope", "AUTO")

        scaled_faces_count = 0
        with bmesh_context(ctx.context) as (obj, bm):
            uv_layer = bm.loops.layers.uv.verify()

            selected_faces = [f for f in bm.faces if f.select]
            if selection_scope == "SELECTED":
                target_faces = selected_faces
            elif selection_scope == "ALL":
                target_faces = list(bm.faces)
            else:  # AUTO: use selected if present, else fallback to all
                target_faces = selected_faces if selected_faces else list(bm.faces)

            if not target_faces:
                return StepResult.cancelled("No faces available to scale UV.")

            for face in target_faces:
                uv_center = get_face_uv_center(face, uv_layer)
                for loop in face.loops:
                    uv = loop[uv_layer].uv
                    loop[uv_layer].uv = uv_center + (uv - uv_center) * scale_factor
                scaled_faces_count += 1

        is_selected_only = bool(selected_faces and selection_scope != "ALL")
        scope_desc = "selected " if is_selected_only else ""
        msg = f"Scaled UV for {scaled_faces_count} {scope_desc}face(s) by factor {scale_factor:.3f}"
        ctx.set_data("scaled_uv_faces_count", scaled_faces_count)
        return StepResult.success(msg, {"scaled_faces_count": scaled_faces_count, "scale_factor": scale_factor})

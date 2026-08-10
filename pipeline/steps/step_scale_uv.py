"""
Scale UV Faces Pipeline Step
"""

import bpy
from ..context import PipelineContext
from ..step import PipelineStep, StepResult

try:
    from ...utils.mesh import bmesh_context, poll_edit_mesh
    from ...utils.uv import get_face_uv_center
except (ImportError, ValueError):
    from utils.mesh import bmesh_context, poll_edit_mesh
    from utils.uv import get_face_uv_center


class ScaleUVStep(PipelineStep):
    name = "Scale UV Faces"
    description = "Scale individual UV faces in place around their UV center"

    def execute(self, ctx: PipelineContext) -> StepResult:
        if not poll_edit_mesh(ctx.context):
            return StepResult.cancelled("Must be in Edit Mode with a Mesh object active.")

        scale_factor = self.get_param(ctx, "scale_factor", 0.8)

        scaled_faces_count = 0
        with bmesh_context(ctx.context) as (obj, bm):
            uv_layer = bm.loops.layers.uv.verify()

            for face in bm.faces:
                uv_center = get_face_uv_center(face, uv_layer)
                for loop in face.loops:
                    uv = loop[uv_layer].uv
                    loop[uv_layer].uv = uv_center + (uv - uv_center) * scale_factor
                scaled_faces_count += 1

        msg = f"Scaled UV for {scaled_faces_count} face(s) by factor {scale_factor:.3f}"
        ctx.set_data("scaled_uv_faces_count", scaled_faces_count)
        return StepResult.success(msg, {"scaled_faces_count": scaled_faces_count, "scale_factor": scale_factor})

"""
Select Hard & Sharp Edges Pipeline Step
"""

import math
import bpy
from ..context import PipelineContext
from ..step import PipelineStep, StepResult

try:
    from ...utils.mesh import bmesh_context, is_hard_edge, poll_edit_mesh, set_select_mode
except (ImportError, ValueError):
    from utils.mesh import bmesh_context, is_hard_edge, poll_edit_mesh, set_select_mode


class SelectHardEdgesStep(PipelineStep):
    name = "Select Hard & Sharp Edges"
    description = "Select boundary edges, sharp marked edges, and edges exceeding sharp angle threshold"

    def execute(self, ctx: PipelineContext) -> StepResult:
        if not poll_edit_mesh(ctx.context):
            return StepResult.cancelled("Must be in Edit Mode with a Mesh object active.")

        sharp_angle = self.get_param(ctx, "sharp_angle", 30.0)
        set_select_mode(ctx.context, "EDGE")

        selected_count = 0
        with bmesh_context(ctx.context) as (obj, bm):
            sharp_angle_rad = math.radians(sharp_angle)

            for edge in bm.edges:
                is_hard = is_hard_edge(edge, sharp_angle_rad)
                edge.select = is_hard
                if is_hard:
                    selected_count += 1

        msg = f"Selected {selected_count} hard/sharp edge(s)"
        ctx.set_data("selected_edges_count", selected_count)
        return StepResult.success(msg, {"selected_edges_count": selected_count})

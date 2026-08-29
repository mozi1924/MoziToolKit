from typing import Iterator, Union
import bmesh
import bpy
from ..context import PipelineContext
from ..progress import ProgressUpdate
from ..step import PipelineStep, StepResult

from ...utils.mesh import poll_edit_mesh
from ...utils.extrude_repair import repair_extruded_side_faces


class AutoExtrudeRepairStep(PipelineStep):
    name = "Auto Extrude Repair"
    description = "Repair UV overlap and add Mean Crease to extruded side faces"

    def execute_iter(self, ctx: PipelineContext) -> Iterator[Union[ProgressUpdate, StepResult]]:
        if not poll_edit_mesh(ctx.context):
            yield StepResult.cancelled("Must be in Edit Mode with a Mesh object active.")
            return

        obj = ctx.active_object
        if not obj or obj.type != "MESH":
            yield StepResult.cancelled("No active mesh object.")
            return

        yield ProgressUpdate(0.1, 1.0, f"Auto Extrude Repair: analyzing {obj.name}...")

        if ctx.is_cancelled:
            yield StepResult.cancelled("Auto extrude repair cancelled by user.")
            return

        repair_uv = self.get_param(ctx, "repair_uv", True)
        add_mean_crease = self.get_param(ctx, "add_mean_crease", False)
        crease_value = self.get_param(ctx, "crease_value", 1.0)
        uv_mode = self.get_param(ctx, "uv_mode", "SMART")
        only_collapsed = self.get_param(ctx, "only_collapsed", False)
        smart_side_face_indices = self.get_param(ctx, "smart_side_face_indices", None)

        bm = bmesh.from_edit_mesh(obj.data)

        count = repair_extruded_side_faces(
            bm,
            obj=obj,
            context=ctx.context,
            repair_uv=repair_uv,
            add_crease=add_mean_crease,
            crease_val=crease_value,
            uv_mode=uv_mode,
            only_collapsed=only_collapsed,
            smart_side_face_indices=smart_side_face_indices,
        )

        if count > 0:
            bmesh.update_edit_mesh(obj.data)
            msg = f"Repaired {count} extruded side faces"
        else:
            msg = "No extruded side faces to repair"

        yield ProgressUpdate(1.0, 1.0, f"Auto Extrude Repair: completed ({msg})")
        ctx.set_data("repaired_faces_count", count)
        yield StepResult.success(msg, {"repaired_count": count})


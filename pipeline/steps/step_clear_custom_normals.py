"""
Clear Custom Normals Pipeline Step
"""

import bpy
from ..context import PipelineContext
from ..step import PipelineStep, StepResult


class ClearCustomNormalsStep(PipelineStep):
    name = "Clear Custom Normals"
    description = "Delete custom_normal attribute and clear custom split normals for selected mesh objects"

    def execute(self, ctx: PipelineContext) -> StepResult:
        selected_mesh_objs = ctx.target_objects
        if not selected_mesh_objs:
            return StepResult.cancelled("No mesh objects selected.")

        saved_mode = ctx.context.mode
        saved_active = ctx.context.view_layer.objects.active

        if saved_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        cleared_count = 0

        try:
            for obj in selected_mesh_objs:
                mesh = obj.data
                had_custom = False

                attrs_to_remove = [
                    attr
                    for attr in mesh.attributes
                    if "custom_normal" in attr.name.lower()
                    or "custom normal" in attr.name.lower()
                    or attr.name.lower().replace("_", "").replace(" ", "") == "customnormal"
                ]
                for attr in attrs_to_remove:
                    mesh.attributes.remove(attr)
                    had_custom = True

                if mesh.has_custom_normals:
                    ctx.context.view_layer.objects.active = obj
                    bpy.ops.mesh.customdata_custom_splitnormals_clear()
                    had_custom = True

                if had_custom:
                    cleared_count += 1
        finally:
            if saved_active and saved_active in ctx.context.view_layer.objects.values():
                ctx.context.view_layer.objects.active = saved_active

            if saved_mode != "OBJECT":
                mode_to_set = "EDIT" if saved_mode == "EDIT_MESH" else saved_mode
                try:
                    bpy.ops.object.mode_set(mode=mode_to_set)
                except Exception:
                    pass

        if cleared_count == 0:
            msg = "No custom normals found on selected objects"
        else:
            msg = f"Cleared custom normals from {cleared_count} object(s)"

        ctx.set_data("cleared_normals_count", cleared_count)
        return StepResult.success(msg, {"cleared_count": cleared_count})

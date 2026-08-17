import bpy
from ...utils.mesh import poll_edit_mesh
from ...utils.system import register_menu_item


@register_menu_item(views=["uv", "mesh"])
class MOZI_OT_repair_fluid_uv(bpy.types.Operator):
    """Repair inverted UV mapping on sloped fluid side faces"""

    bl_idname = "mozi.repair_fluid_uv"
    bl_label = "Repair Fluid UV"
    bl_options = {"REGISTER", "UNDO"}

    selection_scope: bpy.props.EnumProperty(
        name="Selection Scope",
        description="Faces to repair fluid UV on",
        items=[
            ("SELECTED", "Selected Faces", "Only repair currently selected faces"),
            ("ALL", "All Similar Faces", "Scan and repair all inverted fluid faces in mesh"),
        ],
        default="SELECTED",
    )

    @classmethod
    def poll(cls, context):
        return poll_edit_mesh(context)

    def execute(self, context):
        params = {
            "selection_scope": self.selection_scope,
        }
        from ...pipeline.presets import run_preset_pipeline

        res, ctx = run_preset_pipeline("repair_fluid_uv", context, params)
        for level, msg in ctx.reports:
            self.report({level}, msg)

        if not res.is_success:
            return {"CANCELLED"}
        return {"FINISHED"}

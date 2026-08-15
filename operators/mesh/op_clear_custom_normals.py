import bpy
from ...utils.system import register_menu_item


@register_menu_item(views=["mesh", "object"])
class MOZI_OT_clear_custom_normals(bpy.types.Operator):
    """Delete custom_normal attribute and clear custom split normals for selected mesh objects"""

    bl_idname = "mozi.clear_custom_normals"
    bl_label = "Clear Custom Normals"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode in ("OBJECT", "EDIT_MESH") and any(
            o.type == "MESH" for o in context.selected_objects
        )

    def execute(self, context):
        from ...pipeline.presets import run_preset_pipeline

        res, ctx = run_preset_pipeline("clear_custom_normals", context)
        for level, msg in ctx.reports:
            self.report({level}, msg)

        if not res.is_success:
            return {"CANCELLED"}
        return {"FINISHED"}

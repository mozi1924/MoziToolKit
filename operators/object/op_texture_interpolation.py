import bpy
from ...utils.material import set_materials_texture_interpolation_closest
from ...utils.menu_config import register_menu_item


@register_menu_item(views=["object"])
class MOZI_OT_set_texture_interpolation_closest(bpy.types.Operator):
    """Set interpolation of all image texture nodes in selected objects' materials to Closest for pixel art"""

    bl_idname = "mozi.set_texture_interpolation_closest"
    bl_label = "Set Image Interpolation to Closest"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.selected_objects)

    def execute(self, context):
        from ...pipeline.presets import run_preset_pipeline

        res, ctx = run_preset_pipeline("set_texture_interpolation_closest", context)
        for level, msg in ctx.reports:
            self.report({level}, msg)

        if not res.is_success:
            return {"CANCELLED"}
        return {"FINISHED"}

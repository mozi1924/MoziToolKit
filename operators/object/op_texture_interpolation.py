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
        mat_count, node_count = set_materials_texture_interpolation_closest(context.selected_objects)

        if mat_count == 0:
            self.report({"WARNING"}, "No materials found on selected objects")
        elif node_count == 0:
            self.report({"INFO"}, f"Processed {mat_count} material(s), all image texture nodes are already Closest")
        else:
            self.report({"INFO"}, f"Set {node_count} image texture node(s) to Closest interpolation across {mat_count} material(s)")

        return {"FINISHED"}

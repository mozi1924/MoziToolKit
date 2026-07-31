import bpy
from ..operators.object.op_texture_interpolation import MOZI_OT_set_texture_interpolation_closest


class MOZI_MT_object_context_menu(bpy.types.Menu):
    bl_label = "MoziToolKit"
    bl_idname = "MOZI_MT_object_context_menu"

    def draw(self, context):
        layout = self.layout
        layout.operator(MOZI_OT_set_texture_interpolation_closest.bl_idname)


def draw_object_context_menu_func(self, context):
    self.layout.separator()
    self.layout.menu("MOZI_MT_object_context_menu", text="MoziToolKit", icon="TOOL_SETTINGS")


def register():
    if hasattr(bpy.types, "VIEW3D_MT_object"):
        bpy.types.VIEW3D_MT_object.append(draw_object_context_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_object_context_menu"):
        bpy.types.VIEW3D_MT_object_context_menu.append(draw_object_context_menu_func)


def unregister():
    if hasattr(bpy.types, "VIEW3D_MT_object_context_menu"):
        bpy.types.VIEW3D_MT_object_context_menu.remove(draw_object_context_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_object"):
        bpy.types.VIEW3D_MT_object.remove(draw_object_context_menu_func)

import bpy
from ..operators.mesh.op_adaptive_pixel_split import MOZI_OT_adaptive_pixel_split
from ..operators.object.op_texture_interpolation import MOZI_OT_set_texture_interpolation_closest


class MOZI_MT_object_menu(bpy.types.Menu):
    bl_label = "MoziToolKit"
    bl_idname = "MOZI_MT_object_menu"

    def draw(self, context):
        layout = self.layout
        layout.operator(MOZI_OT_adaptive_pixel_split.bl_idname)
        layout.operator(MOZI_OT_set_texture_interpolation_closest.bl_idname)


def draw_object_workspace_menu_func(self, context):
    self.layout.separator()
    self.layout.menu("MOZI_MT_object_menu", text="MoziToolKit", icon="TOOL_SETTINGS")


from ..utils.menu_config import load_config


def draw_object_menu_func(self, context):
    config = load_config()
    items = config.get("object", [])
    if not items:
        return
    self.layout.separator()
    self.layout.label(text="MoziToolKit")
    for item in items:
        if item.get("enabled", True):
            op_id = item.get("operator")
            label = item.get("label")
            if op_id:
                if label:
                    self.layout.operator(op_id, text=label)
                else:
                    self.layout.operator(op_id)



def register():
    if hasattr(bpy.types, "VIEW3D_MT_object"):
        bpy.types.VIEW3D_MT_object.append(draw_object_workspace_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_object_context_menu"):
        bpy.types.VIEW3D_MT_object_context_menu.append(draw_object_menu_func)


def unregister():
    if hasattr(bpy.types, "VIEW3D_MT_object_context_menu"):
        bpy.types.VIEW3D_MT_object_context_menu.remove(draw_object_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_object"):
        bpy.types.VIEW3D_MT_object.remove(draw_object_workspace_menu_func)

import bpy
from ..operators.uv.op_scale_uv import MOZI_OT_scale_uv
from ..operators.uv.op_select_transparent_faces import MOZI_OT_select_transparent_faces
from ..operators.mesh.op_adaptive_pixel_split import MOZI_OT_adaptive_pixel_split


class MOZI_MT_uv_menu(bpy.types.Menu):
    bl_label = "MoziToolKit"
    bl_idname = "MOZI_MT_uv_menu"

    def draw(self, context):
        layout = self.layout
        layout.operator(MOZI_OT_adaptive_pixel_split.bl_idname)
        layout.operator(MOZI_OT_scale_uv.bl_idname)
        layout.operator(MOZI_OT_select_transparent_faces.bl_idname)


def draw_uv_workspace_menu_func(self, context):
    self.layout.separator()
    self.layout.menu("MOZI_MT_uv_menu", text="MoziToolKit", icon="TOOL_SETTINGS")


def draw_uv_menu_func(self, context):
    self.layout.separator()
    self.layout.label(text="MoziToolKit")
    self.layout.operator(MOZI_OT_adaptive_pixel_split.bl_idname)
    self.layout.operator(MOZI_OT_scale_uv.bl_idname)
    self.layout.operator(MOZI_OT_select_transparent_faces.bl_idname)


def register():
    if hasattr(bpy.types, "IMAGE_MT_uvs"):
        bpy.types.IMAGE_MT_uvs.append(draw_uv_workspace_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_uvs"):
        bpy.types.VIEW3D_MT_uvs.append(draw_uv_workspace_menu_func)
    if hasattr(bpy.types, "IMAGE_MT_uvs_context_menu"):
        bpy.types.IMAGE_MT_uvs_context_menu.append(draw_uv_menu_func)


def unregister():
    if hasattr(bpy.types, "IMAGE_MT_uvs_context_menu"):
        bpy.types.IMAGE_MT_uvs_context_menu.remove(draw_uv_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_uvs"):
        bpy.types.VIEW3D_MT_uvs.remove(draw_uv_workspace_menu_func)
    if hasattr(bpy.types, "IMAGE_MT_uvs"):
        bpy.types.IMAGE_MT_uvs.remove(draw_uv_workspace_menu_func)

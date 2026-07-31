import bpy
from ..operators.uv.op_scale_uv import MOZI_OT_scale_uv
from ..operators.uv.op_select_transparent_faces import MOZI_OT_select_transparent_faces


def menu_func(self, context):
    self.layout.separator()
    self.layout.operator(MOZI_OT_scale_uv.bl_idname)
    self.layout.operator(MOZI_OT_select_transparent_faces.bl_idname)



def register():
    if hasattr(bpy.types, "IMAGE_MT_uvs"):
        bpy.types.IMAGE_MT_uvs.append(menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_uvs"):
        bpy.types.VIEW3D_MT_uvs.append(menu_func)


def unregister():
    if hasattr(bpy.types, "IMAGE_MT_uvs"):
        bpy.types.IMAGE_MT_uvs.remove(menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_uvs"):
        bpy.types.VIEW3D_MT_uvs.remove(menu_func)

import bpy
from ..operators.mesh.op_select_edges import MOZI_OT_select_hard_edges
from ..operators.uv.op_select_transparent_faces import MOZI_OT_select_transparent_faces


def draw_mesh_select_menu_func(self, context):
    self.layout.separator()
    self.layout.label(text="MoziToolKit")
    self.layout.operator(MOZI_OT_select_hard_edges.bl_idname)
    self.layout.operator(MOZI_OT_select_transparent_faces.bl_idname)


def draw_uv_select_menu_func(self, context):
    self.layout.separator()
    self.layout.label(text="MoziToolKit")
    self.layout.operator(MOZI_OT_select_transparent_faces.bl_idname)


def register():
    if hasattr(bpy.types, "VIEW3D_MT_select_edit_mesh"):
        bpy.types.VIEW3D_MT_select_edit_mesh.append(draw_mesh_select_menu_func)
    if hasattr(bpy.types, "IMAGE_MT_select_edit"):
        bpy.types.IMAGE_MT_select_edit.append(draw_uv_select_menu_func)


def unregister():
    if hasattr(bpy.types, "IMAGE_MT_select_edit"):
        bpy.types.IMAGE_MT_select_edit.remove(draw_uv_select_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_select_edit_mesh"):
        bpy.types.VIEW3D_MT_select_edit_mesh.remove(draw_mesh_select_menu_func)

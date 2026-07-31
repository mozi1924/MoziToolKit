import bpy
from ..operators.mesh.op_select_edges import MOZI_OT_select_hard_edges


def menu_func(self, context):
    self.layout.separator()
    self.layout.operator(MOZI_OT_select_hard_edges.bl_idname)


def register():
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh_edges"):
        bpy.types.VIEW3D_MT_edit_mesh_edges.append(menu_func)


def unregister():
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh_edges"):
        bpy.types.VIEW3D_MT_edit_mesh_edges.remove(menu_func)

import bpy
from ..operators.mesh.op_select_edges import MOZI_OT_select_hard_edges
from ..operators.uv.op_select_transparent_faces import MOZI_OT_select_transparent_faces


class MOZI_MT_mesh_context_menu(bpy.types.Menu):
    bl_label = "MoziToolKit"
    bl_idname = "MOZI_MT_mesh_context_menu"

    def draw(self, context):
        layout = self.layout
        layout.operator(MOZI_OT_select_hard_edges.bl_idname)
        layout.operator(MOZI_OT_select_transparent_faces.bl_idname)


def draw_edge_menu_func(self, context):
    self.layout.separator()
    self.layout.operator(MOZI_OT_select_hard_edges.bl_idname)


def draw_mesh_context_menu_func(self, context):
    self.layout.separator()
    self.layout.menu("MOZI_MT_mesh_context_menu", text="MoziToolKit", icon="TOOL_SETTINGS")


def register():
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh_edges"):
        bpy.types.VIEW3D_MT_edit_mesh_edges.append(draw_edge_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh_context_menu"):
        bpy.types.VIEW3D_MT_edit_mesh_context_menu.append(draw_mesh_context_menu_func)


def unregister():
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh_context_menu"):
        bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(draw_mesh_context_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh_edges"):
        bpy.types.VIEW3D_MT_edit_mesh_edges.remove(draw_edge_menu_func)

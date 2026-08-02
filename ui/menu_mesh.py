import bpy
from ..operators.mesh.op_select_edges import MOZI_OT_select_hard_edges
from ..operators.mesh.op_adaptive_pixel_split import MOZI_OT_adaptive_pixel_split
from ..operators.uv.op_select_transparent_faces import MOZI_OT_select_transparent_faces


class MOZI_MT_mesh_menu(bpy.types.Menu):
    bl_label = "MoziToolKit"
    bl_idname = "MOZI_MT_mesh_menu"

    def draw(self, context):
        layout = self.layout
        layout.operator(MOZI_OT_adaptive_pixel_split.bl_idname)
        layout.operator(MOZI_OT_select_hard_edges.bl_idname)
        layout.operator(MOZI_OT_select_transparent_faces.bl_idname)


class MOZI_MT_mesh_edge_menu(bpy.types.Menu):
    bl_label = "MoziToolKit"
    bl_idname = "MOZI_MT_mesh_edge_menu"

    def draw(self, context):
        layout = self.layout
        layout.operator(MOZI_OT_select_hard_edges.bl_idname)


class MOZI_MT_mesh_face_menu(bpy.types.Menu):
    bl_label = "MoziToolKit"
    bl_idname = "MOZI_MT_mesh_face_menu"

    def draw(self, context):
        layout = self.layout
        layout.operator(MOZI_OT_adaptive_pixel_split.bl_idname)
        layout.operator(MOZI_OT_select_transparent_faces.bl_idname)


def draw_mesh_workspace_menu_func(self, context):
    self.layout.separator()
    self.layout.menu("MOZI_MT_mesh_menu", text="MoziToolKit", icon="TOOL_SETTINGS")


def draw_edge_workspace_menu_func(self, context):
    self.layout.separator()
    self.layout.menu("MOZI_MT_mesh_edge_menu", text="MoziToolKit", icon="TOOL_SETTINGS")


def draw_face_workspace_menu_func(self, context):
    self.layout.separator()
    self.layout.menu("MOZI_MT_mesh_face_menu", text="MoziToolKit", icon="TOOL_SETTINGS")


from ..utils.menu_config import load_config


def draw_mesh_menu_func(self, context):
    config = load_config()
    items = config.get("mesh", [])
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



def draw_edge_menu_func(self, context):
    self.layout.separator()
    self.layout.label(text="MoziToolKit")
    self.layout.operator(MOZI_OT_select_hard_edges.bl_idname)


def draw_face_menu_func(self, context):
    self.layout.separator()
    self.layout.label(text="MoziToolKit")
    self.layout.operator(MOZI_OT_adaptive_pixel_split.bl_idname)
    self.layout.operator(MOZI_OT_select_transparent_faces.bl_idname)


def register():
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh"):
        bpy.types.VIEW3D_MT_edit_mesh.append(draw_mesh_workspace_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh_edges"):
        bpy.types.VIEW3D_MT_edit_mesh_edges.append(draw_edge_workspace_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh_faces"):
        bpy.types.VIEW3D_MT_edit_mesh_faces.append(draw_face_workspace_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh_context_menu"):
        bpy.types.VIEW3D_MT_edit_mesh_context_menu.append(draw_mesh_menu_func)


def unregister():
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh_context_menu"):
        bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(draw_mesh_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh_faces"):
        bpy.types.VIEW3D_MT_edit_mesh_faces.remove(draw_face_workspace_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh_edges"):
        bpy.types.VIEW3D_MT_edit_mesh_edges.remove(draw_edge_workspace_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh"):
        bpy.types.VIEW3D_MT_edit_mesh.remove(draw_mesh_workspace_menu_func)

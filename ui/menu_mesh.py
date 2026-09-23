"""
MoziToolKit 3D View Mesh Edit Mode Menus & Context Menu Integration.
"""

from __future__ import annotations

import bpy

try:
    from ..utils.system import draw_dynamic_menu
except (ImportError, ValueError):
    from utils.system import draw_dynamic_menu


class MOZI_MT_mesh_menu(bpy.types.Menu):
    bl_label = "MoziToolKit"
    bl_idname = "MOZI_MT_mesh_menu"

    def draw(self, context):
        layout = self.layout
        layout.operator("mozi.adaptive_pixel_split")
        layout.operator("mozi.auto_extrude_repair")
        layout.operator("mozi.random_extrude")
        layout.operator("mozi.cull_mesh_faces")
        layout.separator()
        layout.operator("mozi.clear_custom_normals")


class MOZI_MT_mesh_edge_menu(bpy.types.Menu):
    bl_label = "MoziToolKit"
    bl_idname = "MOZI_MT_mesh_edge_menu"

    def draw(self, context):
        layout = self.layout
        layout.operator("mozi.select_hard_edges")


class MOZI_MT_mesh_face_menu(bpy.types.Menu):
    bl_label = "MoziToolKit"
    bl_idname = "MOZI_MT_mesh_face_menu"

    def draw(self, context):
        layout = self.layout
        layout.operator("mozi.adaptive_pixel_split")
        layout.operator("mozi.auto_extrude_repair")
        layout.operator("mozi.random_extrude")
        layout.operator("mozi.cull_mesh_faces")



def draw_mesh_workspace_menu_func(self, context):
    self.layout.separator()
    self.layout.menu("MOZI_MT_mesh_menu", text="MoziToolKit", icon="TOOL_SETTINGS")


def draw_edge_workspace_menu_func(self, context):
    self.layout.separator()
    self.layout.menu("MOZI_MT_mesh_edge_menu", text="MoziToolKit", icon="TOOL_SETTINGS")


def draw_face_workspace_menu_func(self, context):
    self.layout.separator()
    self.layout.menu("MOZI_MT_mesh_face_menu", text="MoziToolKit", icon="TOOL_SETTINGS")


def draw_mesh_menu_func(self, context):
    draw_dynamic_menu(self.layout, "mesh")


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
        try:
            bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(draw_mesh_menu_func)
        except Exception:
            pass
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh_faces"):
        try:
            bpy.types.VIEW3D_MT_edit_mesh_faces.remove(draw_face_workspace_menu_func)
        except Exception:
            pass
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh_edges"):
        try:
            bpy.types.VIEW3D_MT_edit_mesh_edges.remove(draw_edge_workspace_menu_func)
        except Exception:
            pass
    if hasattr(bpy.types, "VIEW3D_MT_edit_mesh"):
        try:
            bpy.types.VIEW3D_MT_edit_mesh.remove(draw_mesh_workspace_menu_func)
        except Exception:
            pass

"""
MoziToolKit 3D View and UV Select Menus Integration.
"""

from __future__ import annotations

import bpy


class MOZI_MT_select_mesh_menu(bpy.types.Menu):
    bl_label = "MoziToolKit"
    bl_idname = "MOZI_MT_select_mesh_menu"

    def draw(self, context):
        layout = self.layout
        layout.operator("mozi.select_hard_edges")


class MOZI_MT_select_uv_menu(bpy.types.Menu):
    bl_label = "MoziToolKit"
    bl_idname = "MOZI_MT_select_uv_menu"

    def draw(self, context):
        layout = self.layout


def draw_mesh_select_workspace_menu_func(self, context):
    self.layout.separator()
    self.layout.menu("MOZI_MT_select_mesh_menu", text="MoziToolKit", icon="TOOL_SETTINGS")


def draw_uv_select_workspace_menu_func(self, context):
    self.layout.separator()
    self.layout.menu("MOZI_MT_select_uv_menu", text="MoziToolKit", icon="TOOL_SETTINGS")


def register():
    if hasattr(bpy.types, "VIEW3D_MT_select_edit_mesh"):
        bpy.types.VIEW3D_MT_select_edit_mesh.append(draw_mesh_select_workspace_menu_func)
    if hasattr(bpy.types, "IMAGE_MT_select_edit"):
        bpy.types.IMAGE_MT_select_edit.append(draw_uv_select_workspace_menu_func)


def unregister():
    if hasattr(bpy.types, "IMAGE_MT_select_edit"):
        try:
            bpy.types.IMAGE_MT_select_edit.remove(draw_uv_select_workspace_menu_func)
        except Exception:
            pass
    if hasattr(bpy.types, "VIEW3D_MT_select_edit_mesh"):
        try:
            bpy.types.VIEW3D_MT_select_edit_mesh.remove(draw_mesh_select_workspace_menu_func)
        except Exception:
            pass

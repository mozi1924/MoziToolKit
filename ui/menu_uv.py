"""
MoziToolKit UV Editor Menus & Context Menu Integration.
"""

from __future__ import annotations

import bpy

try:
    from ..utils.system import draw_dynamic_menu
except (ImportError, ValueError):
    from utils.system import draw_dynamic_menu


class MOZI_MT_uv_menu(bpy.types.Menu):
    bl_label = "MoziToolKit"
    bl_idname = "MOZI_MT_uv_menu"

    def draw(self, context):
        layout = self.layout
        layout.operator("mozi.scale_uv")


def draw_uv_workspace_menu_func(self, context):
    self.layout.separator()
    self.layout.menu("MOZI_MT_uv_menu", text="MoziToolKit", icon="TOOL_SETTINGS")


def draw_uv_menu_func(self, context):
    draw_dynamic_menu(self.layout, "uv")


def register():
    if hasattr(bpy.types, "IMAGE_MT_uvs"):
        bpy.types.IMAGE_MT_uvs.append(draw_uv_workspace_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_uvs"):
        bpy.types.VIEW3D_MT_uvs.append(draw_uv_workspace_menu_func)
    if hasattr(bpy.types, "IMAGE_MT_uvs_context_menu"):
        bpy.types.IMAGE_MT_uvs_context_menu.append(draw_uv_menu_func)


def unregister():
    if hasattr(bpy.types, "IMAGE_MT_uvs_context_menu"):
        try:
            bpy.types.IMAGE_MT_uvs_context_menu.remove(draw_uv_menu_func)
        except Exception:
            pass
    if hasattr(bpy.types, "VIEW3D_MT_uvs"):
        try:
            bpy.types.VIEW3D_MT_uvs.remove(draw_uv_workspace_menu_func)
        except Exception:
            pass
    if hasattr(bpy.types, "IMAGE_MT_uvs"):
        try:
            bpy.types.IMAGE_MT_uvs.remove(draw_uv_workspace_menu_func)
        except Exception:
            pass

"""
MoziToolKit 3D View Object Mode Menus & Context Menu Integration.
"""

from __future__ import annotations

import bpy

try:
    from ..utils.system import draw_dynamic_menu
except (ImportError, ValueError):
    from utils.system import draw_dynamic_menu


class MOZI_MT_object_menu(bpy.types.Menu):
    bl_label = "MoziToolKit"
    bl_idname = "MOZI_MT_object_menu"

    def draw(self, context):
        layout = self.layout
        layout.operator("mozi.replace_material")
        layout.operator("mozi.restore_materials_from_attributes")
        layout.operator("mozi.set_texture_interpolation_closest")
        layout.operator("mozi.clear_custom_normals")


def draw_object_workspace_menu_func(self, context):
    self.layout.separator()
    self.layout.menu("MOZI_MT_object_menu", text="MoziToolKit", icon="TOOL_SETTINGS")


def draw_object_menu_func(self, context):
    draw_dynamic_menu(self.layout, "object")


def draw_add_menu_func(self, context):
    self.layout.separator()
    self.layout.operator("mozi.add_yefira_world", text="Yefira World", icon="WORLD")


def register():
    if hasattr(bpy.types, "VIEW3D_MT_object"):
        bpy.types.VIEW3D_MT_object.append(draw_object_workspace_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_object_context_menu"):
        bpy.types.VIEW3D_MT_object_context_menu.append(draw_object_menu_func)
    if hasattr(bpy.types, "VIEW3D_MT_add"):
        bpy.types.VIEW3D_MT_add.append(draw_add_menu_func)


def unregister():
    if hasattr(bpy.types, "VIEW3D_MT_add"):
        try:
            bpy.types.VIEW3D_MT_add.remove(draw_add_menu_func)
        except Exception:
            pass
    if hasattr(bpy.types, "VIEW3D_MT_object_context_menu"):
        try:
            bpy.types.VIEW3D_MT_object_context_menu.remove(draw_object_menu_func)
        except Exception:
            pass
    if hasattr(bpy.types, "VIEW3D_MT_object"):
        try:
            bpy.types.VIEW3D_MT_object.remove(draw_object_workspace_menu_func)
        except Exception:
            pass

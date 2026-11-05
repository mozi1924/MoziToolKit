"""
MoziToolKit File > Export Menu Integration.
"""

from __future__ import annotations

import bpy


def menu_func_export(self, context):
    from ..i18n import tr
    self.layout.operator(
        "mozi.export_scene",
        text=tr("MTK Scene Interchange (.mtkscene)"),
        icon="SCENE_DATA",
    )


def register():
    if bpy and hasattr(bpy.types, "TOPBAR_MT_file_export"):
        bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    if bpy and hasattr(bpy.types, "TOPBAR_MT_file_export"):
        try:
            bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
        except Exception:
            pass

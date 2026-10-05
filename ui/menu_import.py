"""
MoziToolKit File > Import Menu Integration.
"""

from __future__ import annotations

try:
    import bpy
except ImportError:
    bpy = None


def menu_func_import(self, context):
    self.layout.operator(
        "mtk.import_minecraft_save",
        text="Minecraft World / Save (.mca / level.dat)",
        icon="WORLD",
    )


def register():
    if bpy and hasattr(bpy.types, "TOPBAR_MT_file_import"):
        bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    if bpy and hasattr(bpy.types, "TOPBAR_MT_file_import"):
        try:
            bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
        except Exception:
            pass

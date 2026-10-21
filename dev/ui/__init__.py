"""
MoziToolKit Dev UI Package.
"""

import bpy
from .panel import VIEW3D_PT_mtk_dev_panel

CLASSES = [
    VIEW3D_PT_mtk_dev_panel,
]


def register():
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

"""
MoziToolKit Scene Operators Subpackage.
"""

from .op_export_scene import MOZI_OT_export_scene
from .op_import_scene import MOZI_OT_import_scene

OPERATOR_CLASSES = (
    MOZI_OT_export_scene,
    MOZI_OT_import_scene,
)

__all__ = [
    "OPERATOR_CLASSES",
    "MOZI_OT_export_scene",
    "MOZI_OT_import_scene",
    "register",
    "unregister",
]


def register():
    for cls in OPERATOR_CLASSES:
        import bpy
        if bpy and hasattr(bpy, "utils"):
            try:
                bpy.utils.register_class(cls)
            except (ValueError, Exception):
                pass


def unregister():
    for cls in reversed(OPERATOR_CLASSES):
        import bpy
        if bpy and hasattr(bpy, "utils"):
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass

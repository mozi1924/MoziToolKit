"""
UV operators package registration.
"""

import bpy
from .op_repair_fluid_uv import MOZI_OT_repair_fluid_uv
from .op_scale_uv import MOZI_OT_scale_uv
from .op_select_transparent_faces import MOZI_OT_select_transparent_faces

classes = (
    MOZI_OT_repair_fluid_uv,
    MOZI_OT_scale_uv,
    MOZI_OT_select_transparent_faces,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass



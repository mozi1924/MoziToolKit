"""
MoziToolKit Dev Operators Package.
"""

import bpy
from .op_debug_world import MOZI_OT_dev_load_debug_world
from .op_benchmark import MOZI_OT_dev_mesh_benchmark

CLASSES = [
    MOZI_OT_dev_load_debug_world,
    MOZI_OT_dev_mesh_benchmark,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

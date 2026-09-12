"""
MoziToolKit Operators Root.
"""

import bpy
from .op_precompile import OPERATORS_CLASSES


def register():
    for cls in OPERATORS_CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(OPERATORS_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

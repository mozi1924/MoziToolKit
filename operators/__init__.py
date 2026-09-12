"""
MoziToolKit Operators Root.
"""

import bpy
from .op_precompile import OPERATORS_CLASSES as PRECOMPILE_CLASSES
from .op_materials import OPERATORS_CLASSES as MATERIAL_CLASSES

ALL_OPERATORS = PRECOMPILE_CLASSES + MATERIAL_CLASSES


def register():
    for cls in ALL_OPERATORS:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(ALL_OPERATORS):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass


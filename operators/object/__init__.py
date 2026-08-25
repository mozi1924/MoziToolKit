"""
Object operators package registration.
"""

import bpy
from .op_replace_material import MOZI_OT_replace_material
from .op_texture_interpolation import MOZI_OT_set_texture_interpolation_closest

classes = (
    MOZI_OT_replace_material,
    MOZI_OT_set_texture_interpolation_closest,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

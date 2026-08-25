"""
Mesh operators package registration.
"""

import bpy
from .op_adaptive_pixel_split import MOZI_OT_adaptive_pixel_split
from .op_auto_extrude_repair import (
    MOZI_PG_auto_extrude_repair,
    MOZI_OT_auto_extrude_repair,
    register as register_auto_extrude_repair,
    unregister as unregister_auto_extrude_repair,
)
from .op_clear_custom_normals import MOZI_OT_clear_custom_normals
from .op_random_extrude import MOZI_OT_random_extrude
from .op_select_edges import MOZI_OT_select_hard_edges

classes = (
    MOZI_PG_auto_extrude_repair,
    MOZI_OT_adaptive_pixel_split,
    MOZI_OT_auto_extrude_repair,
    MOZI_OT_clear_custom_normals,
    MOZI_OT_random_extrude,
    MOZI_OT_select_hard_edges,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_auto_extrude_repair()


def unregister():
    unregister_auto_extrude_repair()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

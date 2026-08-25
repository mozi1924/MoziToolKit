"""
Misc operators package registration.
"""

import bpy
from .op_dependencies import (
    MOZI_OT_check_dependencies,
    MOZI_OT_open_preferences,
    MOZI_OT_clear_cache,
    MOZI_OT_open_cache_folder,
)

classes = (
    MOZI_OT_check_dependencies,
    MOZI_OT_open_preferences,
    MOZI_OT_clear_cache,
    MOZI_OT_open_cache_folder,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

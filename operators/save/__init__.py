"""
MoziToolKit Save Operators Subpackage.
"""

from .op_import_save import OPERATOR_CLASSES as IMPORT_CLASSES, MTK_OT_import_minecraft_save
from .op_refresh_save import OPERATOR_CLASSES as REFRESH_CLASSES, MOZI_OT_refresh_save_mesh
from .op_relink_save import OPERATOR_CLASSES as RELINK_CLASSES, MOZI_OT_relink_save_folder
from .op_save_actions import (
    OPERATOR_CLASSES as ACTION_CLASSES,
    MOZI_OT_save_load_yefira_selection,
    MOZI_OT_save_reset_settings,
)
from .properties import (
    MoziSaveProperties,
    get_save_properties,
    sync_save_properties_from_object,
    sync_save_properties_to_custom_props,
    register as register_properties,
    unregister as unregister_properties,
)
from .utils import is_save_root_container, is_save_child_object, resolve_save_container

OPERATOR_CLASSES = IMPORT_CLASSES + REFRESH_CLASSES + RELINK_CLASSES + ACTION_CLASSES

__all__ = [
    "OPERATOR_CLASSES",
    "MTK_OT_import_minecraft_save",
    "MOZI_OT_refresh_save_mesh",
    "MOZI_OT_relink_save_folder",
    "MOZI_OT_save_load_yefira_selection",
    "MOZI_OT_save_reset_settings",
    "MoziSaveProperties",
    "get_save_properties",
    "sync_save_properties_from_object",
    "sync_save_properties_to_custom_props",
    "is_save_root_container",
    "is_save_child_object",
    "resolve_save_container",
    "register",
    "unregister",
]


def register():
    register_properties()
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
    unregister_properties()

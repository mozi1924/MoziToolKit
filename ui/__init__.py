"""
MoziToolKit UI Package Registration
"""

import bpy
from .preferences import (
    MOZI_PG_resource_pack_entry,
    MOZI_PG_context_menu_item,
    MOZI_PG_available_menu_item,
    MOZI_UL_resource_packs_list,
    MOZI_UL_added_items_list,
    MOZI_UL_unadded_items_list,
    MOZI_OT_pack_add,
    MOZI_OT_pack_remove,
    MOZI_OT_pack_move,
    MOZI_OT_menu_add_item,
    MOZI_OT_menu_remove_item,
    MOZI_OT_menu_move_item,
    MOZI_OT_menu_reset_config,
    MOZI_OT_menu_export_config,
    MOZI_OT_menu_import_config,
    MOZI_AddonPreferences,
)

classes = (
    # PropertyGroups
    MOZI_PG_resource_pack_entry,
    MOZI_PG_context_menu_item,
    MOZI_PG_available_menu_item,
    # UILists
    MOZI_UL_resource_packs_list,
    MOZI_UL_added_items_list,
    MOZI_UL_unadded_items_list,
    # Preferences Operators
    MOZI_OT_pack_add,
    MOZI_OT_pack_remove,
    MOZI_OT_pack_move,
    MOZI_OT_menu_add_item,
    MOZI_OT_menu_remove_item,
    MOZI_OT_menu_move_item,
    MOZI_OT_menu_reset_config,
    MOZI_OT_menu_export_config,
    MOZI_OT_menu_import_config,
    # Preferences
    MOZI_AddonPreferences,
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




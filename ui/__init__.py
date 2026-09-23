"""
MoziToolKit UI Package Registration
"""

from __future__ import annotations

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
from .menu_mesh import (
    MOZI_MT_mesh_menu,
    MOZI_MT_mesh_edge_menu,
    MOZI_MT_mesh_face_menu,
    MOZI_PT_auto_extrude_repair_settings,
    register as register_menu_mesh,
    unregister as unregister_menu_mesh,
)
from .menu_object import (
    MOZI_MT_object_menu,
    register as register_menu_object,
    unregister as unregister_menu_object,
)
from .menu_select import (
    MOZI_MT_select_mesh_menu,
    MOZI_MT_select_uv_menu,
    register as register_menu_select,
    unregister as unregister_menu_select,
)
from .menu_uv import (
    MOZI_MT_uv_menu,
    register as register_menu_uv,
    unregister as unregister_menu_uv,
)
from .panel_biome import (
    register as register_panel_biome,
    unregister as unregister_panel_biome,
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
    # Menus
    MOZI_MT_mesh_menu,
    MOZI_MT_mesh_edge_menu,
    MOZI_MT_mesh_face_menu,
    MOZI_MT_object_menu,
    MOZI_MT_select_mesh_menu,
    MOZI_MT_select_uv_menu,
    MOZI_MT_uv_menu,
    # Panels
    MOZI_PT_auto_extrude_repair_settings,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    register_menu_mesh()
    register_menu_object()
    register_menu_select()
    register_menu_uv()
    register_panel_biome()


def unregister():
    unregister_panel_biome()
    unregister_menu_uv()
    unregister_menu_select()
    unregister_menu_object()
    unregister_menu_mesh()

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

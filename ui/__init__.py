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
    MOZI_OT_precompile_cache,
    MOZI_AddonPreferences,
)
from .panel_sync import (
    MOZI_UL_sync_palette_list,
    MOZI_UL_sync_delta_list,
    MOZI_PT_live_sync,
    MOZI_PT_live_sync_data,
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
    # PropertyGroups (must register before AddonPreferences and UI elements that reference them)
    MOZI_PG_resource_pack_entry,
    MOZI_PG_context_menu_item,
    MOZI_PG_available_menu_item,
    # UILists
    MOZI_UL_resource_packs_list,
    MOZI_UL_added_items_list,
    MOZI_UL_unadded_items_list,
    MOZI_UL_sync_palette_list,
    MOZI_UL_sync_delta_list,
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
    MOZI_OT_precompile_cache,
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
    MOZI_PT_live_sync,
    MOZI_PT_live_sync_data,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    register_panel_biome()
    register_menu_mesh()
    register_menu_object()
    register_menu_select()
    register_menu_uv()


def unregister():
    unregister_menu_uv()
    unregister_menu_select()
    unregister_menu_object()
    unregister_menu_mesh()
    unregister_panel_biome()

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass



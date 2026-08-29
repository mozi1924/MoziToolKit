"""
Live Sync operators and properties registration.
"""

import bpy
from .properties import (
    MoziSyncPaletteItem,
    MoziSyncDeltaItem,
    MoziSyncSceneProperties,
    register as register_sync_props,
    unregister as unregister_sync_props,
)
from .op_sync_connect import (
    MOZI_OT_sync_connect,
    MOZI_OT_sync_disconnect,
    MOZI_OT_sync_refresh,
    unregister as unregister_sync_connect,
)
from .op_sync_rebuild import MOZI_OT_sync_rebuild_world
from .op_sync_clear_history import MOZI_OT_sync_clear_history
from .op_sync_create_world import MOZI_OT_add_yefira_world

classes = (
    MoziSyncPaletteItem,
    MoziSyncDeltaItem,
    MoziSyncSceneProperties,
    MOZI_OT_sync_connect,
    MOZI_OT_sync_disconnect,
    MOZI_OT_sync_refresh,
    MOZI_OT_sync_rebuild_world,
    MOZI_OT_sync_clear_history,
    MOZI_OT_add_yefira_world,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_sync_props()


def unregister():
    unregister_sync_connect()
    unregister_sync_props()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

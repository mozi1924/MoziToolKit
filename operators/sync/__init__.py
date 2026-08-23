"""
MoziToolKit Live Sync Operators and Scene Properties Registration.
"""

from __future__ import annotations

import bpy

from .properties import (
    MoziSyncDeltaItem,
    MoziSyncPaletteItem,
    MoziSyncSceneProperties,
)
from .op_sync_connect import (
    MOZI_OT_sync_connect,
    MOZI_OT_sync_disconnect,
    MOZI_OT_sync_refresh,
    trigger_point_cloud_update,
)
from .op_sync_rebuild import MOZI_OT_sync_rebuild_world
from .op_sync_clear_history import MOZI_OT_sync_clear_history


def register():
    bpy.types.Scene.mozi_sync = bpy.props.PointerProperty(type=MoziSyncSceneProperties)
    # Backward compatibility alias
    bpy.types.Scene.yefira = bpy.props.PointerProperty(type=MoziSyncSceneProperties)


def unregister():
    if hasattr(bpy.types.Scene, "yefira"):
        del bpy.types.Scene.yefira
    if hasattr(bpy.types.Scene, "mozi_sync"):
        del bpy.types.Scene.mozi_sync


__all__ = (
    "MoziSyncPaletteItem",
    "MoziSyncDeltaItem",
    "MoziSyncSceneProperties",
    "MOZI_OT_sync_connect",
    "MOZI_OT_sync_disconnect",
    "MOZI_OT_sync_refresh",
    "MOZI_OT_sync_rebuild_world",
    "MOZI_OT_sync_clear_history",
    "trigger_point_cloud_update",
    "register",
    "unregister",
)

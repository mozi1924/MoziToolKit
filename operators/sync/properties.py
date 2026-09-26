"""
Properties definition for Live Sync real-time synchronization state.
"""

from __future__ import annotations

import logging
import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

logger = logging.getLogger("MoziToolKit.Sync.Properties")


class MoziSyncPaletteItem(bpy.types.PropertyGroup):
    """Single item in the block palette."""
    name: StringProperty(name="BlockState", default="")
    block_count: IntProperty(name="Count", default=0)


class MoziSyncDeltaItem(bpy.types.PropertyGroup):
    """Single modification log entry in delta history."""
    pos_str: StringProperty(name="Position", default="")
    block_state: StringProperty(name="BlockState", default="")
    time_str: StringProperty(name="Time", default="")


class MoziSyncProperties(bpy.types.PropertyGroup):
    """Scene and object level properties for Live Sync state tracking and UI binding."""

    url: StringProperty(
        name="Server URL",
        description="WebSocket address of the Live Sync streaming server",
        default="ws://127.0.0.1:8765",
    )

    is_connected: BoolProperty(
        name="Is Connected",
        description="Whether Live Sync client is actively connected",
        default=False,
    )

    connection_status: StringProperty(
        name="Connection Status",
        default="DISCONNECTED",
    )

    has_selection: BoolProperty(
        name="Has Selection",
        default=False,
    )

    # World bounds (in block coordinates)
    min_x: IntProperty(name="Min X", default=0)
    min_y: IntProperty(name="Min Y", default=0)
    min_z: IntProperty(name="Min Z", default=0)
    size_x: IntProperty(name="Size X", default=0)
    size_y: IntProperty(name="Size Y", default=0)
    size_z: IntProperty(name="Size Z", default=0)

    total_blocks: IntProperty(name="Total Blocks", default=0)

    # Geometry statistics
    point_count: IntProperty(name="Vertices", default=0)
    faces_count: IntProperty(name="Faces", default=0)

    # Verification and status messages
    sync_verified: BoolProperty(name="Sync Verified", default=False)
    validation_info: StringProperty(name="Validation Status", default="Ready to connect")
    last_update_info: StringProperty(name="Last Update", default="No updates received yet.")

    # Streaming progress
    stream_progress_current: IntProperty(name="Stream Current", default=0)
    stream_progress_total: IntProperty(name="Stream Total", default=0)
    stream_message: StringProperty(name="Stream Message", default="")

    # Lists
    palette_list: CollectionProperty(type=MoziSyncPaletteItem)
    palette_active_index: IntProperty(name="Active Palette Index", default=0)

    delta_history: CollectionProperty(type=MoziSyncDeltaItem)
    delta_active_index: IntProperty(name="Active Delta Index", default=0)


@bpy.app.handlers.persistent
def _on_blend_file_pre_load(dummy=None):
    """Disconnect Live Sync client before loading a new blend file."""
    try:
        from ...bridge.sync import get_sync_bridge_session
        get_sync_bridge_session().stop()
    except Exception as e:
        logger.debug(f"Error disconnecting sync on file load: {e}")


@bpy.app.handlers.persistent
def _on_blend_file_loaded(dummy=None):
    """Reset properties upon file load."""
    try:
        for scene in bpy.data.scenes:
            if hasattr(scene, "mozi_sync"):
                props = scene.mozi_sync
                props.is_connected = False
                props.connection_status = "DISCONNECTED"
                props.validation_info = "Ready to connect"
    except Exception as e:
        logger.debug(f"Error resetting properties: {e}")


CLASSES = (
    MoziSyncPaletteItem,
    MoziSyncDeltaItem,
    MoziSyncProperties,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mozi_sync = PointerProperty(type=MoziSyncProperties)
    bpy.types.Object.mozi_sync = PointerProperty(type=MoziSyncProperties)

    if _on_blend_file_pre_load not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_on_blend_file_pre_load)
    if _on_blend_file_loaded not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_blend_file_loaded)


def unregister():
    if _on_blend_file_pre_load in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_on_blend_file_pre_load)
    if _on_blend_file_loaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_blend_file_loaded)

    if hasattr(bpy.types.Object, "mozi_sync"):
        del bpy.types.Object.mozi_sync
    if hasattr(bpy.types.Scene, "mozi_sync"):
        del bpy.types.Scene.mozi_sync

    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

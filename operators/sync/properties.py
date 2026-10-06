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
    __slots__ = ()

    name: StringProperty(name="BlockState", default="")
    block_count: IntProperty(name="Count", default=0)


class MoziSyncDeltaItem(bpy.types.PropertyGroup):
    """Single modification log entry in delta history."""
    __slots__ = ()

    pos_str: StringProperty(name="Position", default="")
    block_state: StringProperty(name="BlockState", default="")
    time_str: StringProperty(name="Time", default="")


class MoziSyncProperties(bpy.types.PropertyGroup):
    """Scene and object level properties for Live Sync state tracking and UI binding."""
    __slots__ = ()

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
    total_sections: IntProperty(name="Total Sections", default=0)
    non_empty_sections: IntProperty(name="Active Sections", default=0)

    # Geometry statistics
    point_count: IntProperty(name="Vertices", default=0)
    faces_count: IntProperty(name="Faces", default=0)

    # Verification and status messages
    sync_verified: BoolProperty(name="Sync Verified", default=False)
    validation_info: StringProperty(name="Validation Status", default="Ready to connect")
    last_update_info: StringProperty(name="Last Update", default="No updates received yet.")

    # Streaming progress
    is_streaming: BoolProperty(name="Is Streaming", default=False)
    stream_stage: StringProperty(name="Stream Stage", default="")
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
    """Disconnect Live Sync client, cancel timers, and reset session before loading a new blend file."""
    try:
        try:
            from .op_sync_connect import stop_sync_timer
        except (ImportError, ValueError):
            from operators.sync.op_sync_connect import stop_sync_timer
        stop_sync_timer()
    except Exception as e:
        logger.debug(f"Error stopping sync timer on file pre-load: {e}")

    try:
        try:
            from ...bridge.sync import reset_sync_bridge_session
        except (ImportError, ValueError):
            from bridge.sync import reset_sync_bridge_session
        reset_sync_bridge_session()
    except Exception as e:
        logger.debug(f"Error resetting sync session on file pre-load: {e}")


def get_active_sync_container(scene: Optional[bpy.types.Scene] = None) -> Optional[bpy.types.Object]:
    """Resolves the currently active Live Sync Empty root container object."""
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    if not scene:
        return None
    container_name = getattr(scene, "mozi_active_sync_container_name", "")
    if container_name and container_name in bpy.data.objects:
        obj = bpy.data.objects[container_name]
        try:
            from .hierarchy import is_yefira_root_object
            if is_yefira_root_object(obj):
                return obj
        except Exception:
            return obj

    # Fallback: find any connected container or container tagged with sync
    objs = bpy.data.objects.values() if hasattr(bpy.data.objects, "values") else bpy.data.objects
    for obj in objs:
        if isinstance(obj, str):
            obj = bpy.data.objects.get(obj)
        if obj is None:
            continue
        if getattr(obj, "type", "") == 'EMPTY' and (
            (hasattr(obj, "get") and obj.get("mtk:is_yefira_world")) or getattr(obj, "name", "").startswith("Yefira_World")
        ):
            props = getattr(obj, "mozi_sync", None)
            if props and getattr(props, "is_connected", False):
                return obj
    return None


def set_active_sync_container(scene: Optional[bpy.types.Scene], container: Optional[bpy.types.Object]) -> None:
    """Sets or clears the active Live Sync container for the scene."""
    if not scene:
        return
    if hasattr(scene, "mozi_active_sync_container_name"):
        scene.mozi_active_sync_container_name = container.name if container else ""
    else:
        try:
            scene["mozi_active_sync_container_name"] = container.name if container else ""
        except Exception:
            pass


@bpy.app.handlers.persistent
def _on_blend_file_loaded(dummy=None):
    """Reset properties across all scenes and objects upon file load."""
    try:
        for scene in bpy.data.scenes:
            if hasattr(scene, "mozi_sync"):
                props = scene.mozi_sync
                props.is_connected = False
                props.connection_status = "DISCONNECTED"
                props.validation_info = "Ready to connect"
                props.is_streaming = False
            if hasattr(scene, "mozi_active_sync_container_name"):
                scene.mozi_active_sync_container_name = ""
        for obj in bpy.data.objects:
            if hasattr(obj, "mozi_sync"):
                props = obj.mozi_sync
                props.is_connected = False
                props.connection_status = "DISCONNECTED"
                props.is_streaming = False
    except Exception as e:
        logger.debug(f"Error resetting properties on file load: {e}")


CLASSES = (
    MoziSyncPaletteItem,
    MoziSyncDeltaItem,
    MoziSyncProperties,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mozi_sync = PointerProperty(type=MoziSyncProperties)
    bpy.types.Scene.mozi_active_sync_container_name = StringProperty(
        name="Active Sync Container",
        description="Name of the root Empty container actively bound to Live Sync",
        default="",
    )
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

    try:
        try:
            from .op_sync_connect import stop_sync_timer
        except (ImportError, ValueError):
            from operators.sync.op_sync_connect import stop_sync_timer
        stop_sync_timer()
    except Exception:
        pass

    try:
        try:
            from ...bridge.sync import reset_sync_bridge_session
        except (ImportError, ValueError):
            from bridge.sync import reset_sync_bridge_session
        reset_sync_bridge_session()
    except Exception:
        pass

    if hasattr(bpy.types.Object, "mozi_sync"):
        del bpy.types.Object.mozi_sync
    if hasattr(bpy.types.Scene, "mozi_sync"):
        del bpy.types.Scene.mozi_sync
    if hasattr(bpy.types.Scene, "mozi_active_sync_container_name"):
        del bpy.types.Scene.mozi_active_sync_container_name

    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

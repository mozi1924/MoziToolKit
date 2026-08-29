"""
Scene Properties and PropertyGroups for MoziToolKit Live Sync and Yefira DCC compatibility.
"""

import logging
import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, PointerProperty, StringProperty

logger = logging.getLogger("MoziToolKit.LiveSync")


class MoziSyncPaletteItem(bpy.types.PropertyGroup):
    """Single item in the Minecraft block state palette."""
    state_str: StringProperty(name="Block State", default="")


class MoziSyncDeltaItem(bpy.types.PropertyGroup):
    """Single entry in the live delta change history log."""
    timestamp: StringProperty(name="Time", default="")
    pos_str: StringProperty(name="Position", default="")
    block_state: StringProperty(name="Block State", default="")


class MoziSyncSceneProperties(bpy.types.PropertyGroup):
    """Live Sync scene settings, network state, and world metrics."""
    url: StringProperty(
        name="Server URL",
        description="WebSocket address of Yefira / Mozi Live Sync server",
        default="ws://localhost:8765",
    )
    is_connected: BoolProperty(
        name="Is Connected",
        description="Whether Live Sync client is currently connected",
        default=False,
        options={'SKIP_SAVE'},
    )
    connection_status: StringProperty(
        name="Status",
        description="Live Sync connection status message",
        default="DISCONNECTED",
        options={'SKIP_SAVE'},
    )
    show_3d_bbox: BoolProperty(
        name="Show 3D BBox",
        description="Visualize selection bounding box in 3D Viewport",
        default=True,
    )
    filter_air: BoolProperty(
        name="Filter Air",
        description="Exclude air blocks from the point cloud to optimize point count",
        default=True,
    )

    # Selection Bounds
    has_selection: BoolProperty(name="Has Selection", default=False)
    min_x: IntProperty(name="Min X", default=0)
    min_y: IntProperty(name="Min Y", default=0)
    min_z: IntProperty(name="Min Z", default=0)
    max_x: IntProperty(name="Max X", default=0)
    max_y: IntProperty(name="Max Y", default=0)
    max_z: IntProperty(name="Max Z", default=0)
    size_x: IntProperty(name="Size X", default=0)
    size_y: IntProperty(name="Size Y", default=0)
    size_z: IntProperty(name="Size Z", default=0)
    total_blocks: IntProperty(name="Total Blocks", default=0)
    palette_count: IntProperty(name="Palette Count", default=0)
    update_counter: IntProperty(name="Update Counter", default=0)

    # Point Cloud & Geometry Nodes Metrics
    point_count: IntProperty(name="Point Count", default=0)
    cubes_count: IntProperty(name="Cubes Count", default=0)
    props_count: IntProperty(name="Props Count", default=0)
    fluids_count: IntProperty(name="Fluids Count", default=0)
    sync_verified: BoolProperty(name="Sync Verified", default=False, options={'SKIP_SAVE'})
    validation_info: StringProperty(name="Validation Status", default="Pending validation...", options={'SKIP_SAVE'})
    last_update_info: StringProperty(name="Last Update", default="No updates received yet.", options={'SKIP_SAVE'})

    # Lists
    palette_list: CollectionProperty(type=MoziSyncPaletteItem)
    palette_active_index: IntProperty(name="Active Palette Index", default=0)
    delta_history: CollectionProperty(type=MoziSyncDeltaItem)
    delta_active_index: IntProperty(name="Active Delta Index", default=0)


@bpy.app.handlers.persistent
def _on_blend_file_pre_load(dummy=None):
    """Disconnect Live Sync client and free preloaded resources before loading a new project or file."""
    try:
        try:
            from .op_sync_connect import cleanup_sync_state
        except (ImportError, ValueError):
            from operators.sync.op_sync_connect import cleanup_sync_state
        cleanup_sync_state()
    except Exception as e:
        logger.debug(f"Error in Live Sync pre-load handler: {e}")


@bpy.app.handlers.persistent
def _on_blend_file_loaded(dummy=None):
    """Ensure runtime connection properties and background sync states are strictly reset upon loading any .blend file."""
    try:
        try:
            from .op_sync_connect import cleanup_sync_state
        except (ImportError, ValueError):
            from operators.sync.op_sync_connect import cleanup_sync_state
        cleanup_sync_state()
    except Exception as e:
        logger.debug(f"Error in Live Sync post-load cleanup: {e}")

    for scene in bpy.data.scenes:
        if hasattr(scene, "mozi_sync"):
            props = scene.mozi_sync
            props.is_connected = False
            props.connection_status = "DISCONNECTED"
            props.sync_verified = False
            props.validation_info = "Ready to connect"


@bpy.app.handlers.persistent
def _on_depsgraph_update_post(scene, depsgraph):
    """Detect when a Yefira World empty object is renamed, and automatically update child section and mesh names."""
    try:
        for obj in scene.objects:
            if obj.type == 'EMPTY' and (obj.get("mtk:is_yefira_world") or any(c.get("mtk:section_pos") is not None for c in obj.children)):
                last_name = obj.get("mtk:last_name")
                if last_name and last_name != obj.name:
                    try:
                        from ...utils.live_sync.mesh_builder import sync_child_section_names
                    except (ImportError, ValueError):
                        from utils.live_sync.mesh_builder import sync_child_section_names
                    sync_child_section_names(obj)
                    obj["mtk:last_name"] = obj.name
                elif not last_name:
                    obj["mtk:last_name"] = obj.name
    except Exception as e:
        logger.debug(f"Error in Live Sync rename handler: {e}")


def register():
    bpy.types.Scene.mozi_sync = PointerProperty(type=MoziSyncSceneProperties)
    if _on_blend_file_pre_load not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_on_blend_file_pre_load)
    if _on_blend_file_loaded not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_blend_file_loaded)
    if _on_depsgraph_update_post not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update_post)


def unregister():
    if _on_depsgraph_update_post in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update_post)
    if _on_blend_file_pre_load in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_on_blend_file_pre_load)
    if _on_blend_file_loaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_blend_file_loaded)
    if hasattr(bpy.types.Scene, "mozi_sync"):
        try:
            del bpy.types.Scene.mozi_sync
        except Exception:
            pass


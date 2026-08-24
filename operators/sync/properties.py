"""
Scene Properties and PropertyGroups for MoziToolKit Live Sync and Yefira DCC compatibility.
"""

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, PointerProperty, StringProperty


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
    )
    connection_status: StringProperty(
        name="Status",
        description="Live Sync connection status message",
        default="DISCONNECTED",
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
    sync_verified: BoolProperty(name="Sync Verified", default=False)
    validation_info: StringProperty(name="Validation Status", default="Pending validation...")
    last_update_info: StringProperty(name="Last Update", default="No updates received yet.")

    # Lists
    palette_list: CollectionProperty(type=MoziSyncPaletteItem)
    palette_active_index: IntProperty(name="Active Palette Index", default=0)
    delta_history: CollectionProperty(type=MoziSyncDeltaItem)
    delta_active_index: IntProperty(name="Active Delta Index", default=0)


def register():
    bpy.types.Scene.mozi_sync = PointerProperty(type=MoziSyncSceneProperties)


def unregister():
    if hasattr(bpy.types.Scene, "mozi_sync"):
        try:
            del bpy.types.Scene.mozi_sync
        except Exception:
            pass


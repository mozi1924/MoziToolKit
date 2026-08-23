"""
Operator to rebuild and optimize the Minecraft procedural world point cloud and Geometry Nodes.
"""

from __future__ import annotations

import bpy
from .op_sync_connect import trigger_point_cloud_update, clear_sync_caches
from ...utils.live_sync.point_cloud import clear_state_cache


class MOZI_OT_sync_rebuild_world(bpy.types.Operator):
    bl_idname = "mozi.sync_rebuild_world"
    bl_label = "Rebuild World"
    bl_description = "Force rebuild Yefira_World point cloud, materials, and Geometry Nodes"

    def execute(self, context):
        clear_sync_caches()
        clear_state_cache()
        trigger_point_cloud_update(context, force_gn_setup=True)
        self.report({'INFO'}, "Rebuilt Live Sync procedural world.")
        return {'FINISHED'}


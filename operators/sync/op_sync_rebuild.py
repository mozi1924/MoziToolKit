"""
Operator to rebuild and optimize the Minecraft procedural world point cloud and Geometry Nodes.
"""

from __future__ import annotations

import bpy
from .op_sync_connect import trigger_point_cloud_update


class MOZI_OT_sync_rebuild_world(bpy.types.Operator):
    bl_idname = "mozi.sync_rebuild_world"
    bl_label = "Rebuild World"
    bl_description = "Force rebuild Yefira_World point cloud, materials, and Geometry Nodes"

    def execute(self, context):
        trigger_point_cloud_update(context)
        self.report({'INFO'}, "Rebuilt Live Sync procedural world.")
        return {'FINISHED'}

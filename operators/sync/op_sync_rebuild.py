"""
Operator to rebuild and optimize the Minecraft procedural direct world mesh.
"""

from __future__ import annotations

import bpy
from .op_sync_connect import trigger_mesh_sync, clear_sync_caches


class MOZI_OT_sync_rebuild_world(bpy.types.Operator):
    bl_idname = "mozi.sync_rebuild_world"
    bl_label = "Rebuild World"
    bl_description = "Force rebuild Yefira_World mesh hierarchy, chunk materials, and UV mapping"

    def execute(self, context):
        clear_sync_caches()
        trigger_mesh_sync(context, force_full_rebuild=True)
        self.report({'INFO'}, "Rebuilt Live Sync direct world mesh.")
        return {'FINISHED'}


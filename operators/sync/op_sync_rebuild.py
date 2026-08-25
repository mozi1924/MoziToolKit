"""
Operator to rebuild and optimize the Minecraft procedural direct world mesh.
"""

from __future__ import annotations

import bpy
from .op_sync_connect import trigger_mesh_sync, clear_sync_caches, restore_sync_state_from_scene
from ...utils.live_sync.storage import voxel_storage


class MOZI_OT_sync_rebuild_world(bpy.types.Operator):
    bl_idname = "mozi.sync_rebuild_world"
    bl_label = "Rebuild World"
    bl_description = "Reconstruct meshes, face culling, UV maps, and material slots purely from local voxel data"

    def execute(self, context):
        if voxel_storage.size_x == 0:
            restore_sync_state_from_scene(context)

        if voxel_storage.size_x == 0 and not voxel_storage.block_map:
            self.report({'WARNING'}, "No voxel data in memory. Connect to server or click Refresh first.")
            return {'CANCELLED'}

        clear_sync_caches()
        trigger_mesh_sync(context, force_full_rebuild=True)
        self.report({'INFO'}, "Reconstructed meshes and material bindings from local voxel data.")
        return {'FINISHED'}


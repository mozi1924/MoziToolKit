"""
Operator to trigger on-demand rebuild of the unified world mesh.
"""

from __future__ import annotations

import logging
import bpy

try:
    from ...bridge.sync import get_sync_bridge_session
except (ImportError, ValueError):
    from bridge.sync import get_sync_bridge_session
from .hierarchy import get_or_create_world_mesh_object, update_world_mesh

logger = logging.getLogger("MoziToolKit.Sync.Rebuild")


class MOZI_OT_sync_rebuild_world(bpy.types.Operator):
    """Re-mesh the active world from in-memory voxel storage."""
    bl_idname = "mozi.sync_rebuild_world"
    bl_label = "Rebuild World Mesh"
    bl_description = "Force re-meshing the entire synchronized world from voxel storage"

    def execute(self, context):
        session = get_sync_bridge_session()
        mesh_data = session.get_world_mesh()
        if not mesh_data or mesh_data.vertex_count == 0:
            self.report({'WARNING'}, "Voxel storage is empty or no geometry generated.")
            return {'CANCELLED'}

        world_obj = get_or_create_world_mesh_object(context)
        v_count, f_count = update_world_mesh(world_obj, mesh_data)

        props = getattr(context.scene, "mozi_sync", None)
        if props:
            props.point_count = v_count
            props.faces_count = f_count
            props.last_update_info = f"Rebuilt World Mesh: {v_count:,} vertices, {f_count:,} faces"

        self.report({'INFO'}, f"World mesh rebuilt: {v_count:,} vertices, {f_count:,} faces")
        return {'FINISHED'}


OPERATOR_CLASSES = (
    MOZI_OT_sync_rebuild_world,
)

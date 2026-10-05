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


from typing import Optional

try:
    from ...utils.async_task import AsyncTask, ModalTaskRunner
    from ...utils.progress import BlenderProgressReporter
except (ImportError, ValueError):
    from utils.async_task import AsyncTask, ModalTaskRunner
    from utils.progress import BlenderProgressReporter


class MOZI_OT_sync_rebuild_world(bpy.types.Operator):
    """Re-mesh the active world from in-memory voxel storage."""
    bl_idname = "mozi.sync_rebuild_world"
    bl_label = "Rebuild World Mesh"
    bl_description = "Force re-meshing the entire synchronized world from voxel storage"

    run_async: bpy.props.BoolProperty(
        name="Run Asynchronously",
        description="Run re-meshing in non-blocking background thread with live status bar progress",
        default=True,
        options={"HIDDEN"},
    )

    _runner: Optional[ModalTaskRunner] = None

    def execute(self, context):
        session = get_sync_bridge_session()
        if not session.is_active:
            self.report({'WARNING'}, "Live Sync session is not active.")
            return {'CANCELLED'}

        def do_rebuild(progress_callback=None):
            return session.get_world_mesh()

        def on_success(mesh_data):
            if not mesh_data or mesh_data.vertex_count == 0:
                self.report({'WARNING'}, "Voxel storage is empty or no geometry generated.")
                return

            world_obj = get_or_create_world_mesh_object(context)
            storage = session.get_storage()
            v_count, f_count = update_world_mesh(world_obj, mesh_data, storage=storage)

            props = getattr(context.scene, "mozi_sync", None)
            if props:
                props.point_count = v_count
                props.faces_count = f_count
                props.last_update_info = f"Rebuilt World Mesh: {v_count:,} vertices, {f_count:,} faces"

            self.report({'INFO'}, f"World mesh rebuilt: {v_count:,} vertices, {f_count:,} faces")

        # Synchronous fallback for CLI / tests when run_async is False
        if not self.run_async:
            try:
                mesh_data = do_rebuild()
                on_success(mesh_data)
                return {'FINISHED'}
            except Exception as e:
                self.report({'ERROR'}, f"Failed rebuilding world mesh: {e}")
                return {'CANCELLED'}

        # Non-blocking modal execution
        task = AsyncTask(target=do_rebuild)
        reporter = BlenderProgressReporter(context=context, total=100, title="Rebuilding World Mesh")
        self._runner = ModalTaskRunner(
            operator=self,
            context=context,
            task=task,
            reporter=reporter,
            on_success=on_success,
            title="Rebuilding World Mesh",
        )
        return self._runner.start()

    def modal(self, context, event):
        if self._runner is not None:
            return self._runner.modal(event)
        return {'FINISHED'}


OPERATOR_CLASSES = (
    MOZI_OT_sync_rebuild_world,
)

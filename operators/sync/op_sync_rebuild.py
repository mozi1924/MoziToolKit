"""
Operator to trigger on-demand rebuild of the unified world mesh.
"""

from __future__ import annotations

import logging
import bpy

try:
    from ...bridge.sync import get_sync_bridge_session
    from ...utils.assets import (
        can_execute_asset_pipeline,
        check_asset_cache_status,
        ensure_pipeline_assets_ready_sync,
    )
except (ImportError, ValueError):
    from bridge.sync import get_sync_bridge_session
    from utils.assets import (
        can_execute_asset_pipeline,
        check_asset_cache_status,
        ensure_pipeline_assets_ready_sync,
    )
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

    target_container: bpy.props.StringProperty(
        name="Target Container",
        description="Name of the root container to rebuild",
        default="",
    )

    run_async: bpy.props.BoolProperty(
        name="Run Asynchronously",
        description="Run re-meshing in non-blocking background thread with live status bar progress",
        default=True,
        options={"HIDDEN"},
    )

    _runner: Optional[ModalTaskRunner] = None

    @classmethod
    def poll(cls, context):
        prefs = None
        try:
            from ...utils.system import get_prefs
            prefs = get_prefs(context)
        except Exception:
            try:
                from utils.system import get_prefs
                prefs = get_prefs(context)
            except Exception:
                pass
        can_run, reason = can_execute_asset_pipeline(prefs)
        if not can_run:
            if hasattr(cls, "poll_message_set"):
                cls.poll_message_set(reason)
            return False
        return True

    def execute(self, context):
        prefs = None
        try:
            from ...utils.system import get_prefs
            prefs = get_prefs(context)
        except Exception:
            try:
                from utils.system import get_prefs
                prefs = get_prefs(context)
            except Exception:
                pass

        can_run, reason = can_execute_asset_pipeline(prefs)
        if not can_run:
            self.report({'WARNING'}, reason)
            return {'CANCELLED'}

        session = get_sync_bridge_session()
        if not session.is_active:
            self.report({'WARNING'}, "Live Sync session is not active.")
            return {'CANCELLED'}

        target_container_name = self.target_container

        # Check and hot-reload dirty asset cache before remeshing
        dirty = False
        if hasattr(session, "check_and_reload_dirty_cache"):
            try:
                dirty = session.check_and_reload_dirty_cache(prefs=prefs)
                if dirty:
                    logger.info("Dirty asset cache detected: hot-reloaded assets and cleared mesh cache before rebuild.")
            except Exception as e:
                logger.warning("Failed dirty cache check: %s", e)

        if not dirty:
            # If session is actively connected and atlas is present in memory, the cache is already verified.
            # Only perform the expensive full resource pack stack scan if session is uninitialized or missing assets.
            if not getattr(session, "is_active", False) or getattr(session, "atlas", None) is None:
                status = check_asset_cache_status(prefs)
                if status in ("MISSING", "STALE"):
                    ensure_pipeline_assets_ready_sync(prefs)
                    dirty = True
                    if hasattr(session, "check_and_reload_dirty_cache"):
                        session.check_and_reload_dirty_cache(prefs=prefs, force=True)

        def do_rebuild(progress_callback=None):
            return session.get_world_mesh()

        def on_success(mesh_data):
            if not mesh_data or mesh_data.vertex_count == 0:
                self.report({'WARNING'}, "Voxel storage is empty or no geometry generated.")
                return

            target_root = None
            if target_container_name and target_container_name in bpy.data.objects:
                target_root = bpy.data.objects[target_container_name]
            world_obj = get_or_create_world_mesh_object(context, root_container=target_root)
            storage = session.get_storage()

            if getattr(mesh_data, "profile", None) is not None:
                try:
                    from ...dev.profile_tracker import record_operation_profile
                    record_operation_profile("Sync Rebuild Mesh", mesh_data.profile)
                except Exception:
                    pass

            v_count, f_count = update_world_mesh(
                world_obj,
                mesh_data,
                storage=storage,
                sync_point_cloud=True,
                atlas=getattr(session, "atlas", None),
            )

            root_obj = target_root or world_obj
            props = getattr(root_obj, "mozi_sync", None) or getattr(context.scene, "mozi_sync", None)
            info_suffix = " (Assets Hot-Reloaded)" if dirty else ""
            if props:
                props.point_count = v_count
                props.faces_count = f_count
                props.last_update_info = f"Rebuilt World Mesh: {v_count:,} vertices, {f_count:,} faces{info_suffix}"

            self.report({'INFO'}, f"World mesh rebuilt{info_suffix}: {v_count:,} vertices, {f_count:,} faces")

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

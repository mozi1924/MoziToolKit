"""
MoziToolKit Operator: Refresh Minecraft Save Model.

Seamlessly reloads voxel chunk geometry from local MCA/NBT files using stored
AABB selection coordinates, updating mesh and companion point cloud in-place.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

try:
    import bpy
    from bpy.props import BoolProperty
except ImportError:
    bpy = None

try:
    from ...bridge.save import (
        apply_imported_save_to_blender,
        load_and_mesh_minecraft_save,
    )
    from ...utils.async_task import AsyncTask, ModalTaskRunner
    from ...utils.progress import BlenderProgressReporter, blender_progress_scope
    from ...utils.system.dependencies import get_prefs
    from ...utils.system.save_registry import get_save_registry
except (ImportError, ValueError):
    from bridge.save import (
        apply_imported_save_to_blender,
        load_and_mesh_minecraft_save,
    )
    from utils.async_task import AsyncTask, ModalTaskRunner
    from utils.progress import BlenderProgressReporter, blender_progress_scope
    from utils.system.dependencies import get_prefs
    from utils.system.save_registry import get_save_registry

from .utils import resolve_save_container

logger = logging.getLogger("MoziToolKit.Operators.Save.Refresh")


class MOZI_OT_refresh_save_mesh(bpy.types.Operator):
    """Seamlessly re-reads Minecraft save files and updates the existing mesh in-place"""

    bl_idname = "mozi.refresh_save_mesh"
    bl_label = "Refresh Save Model"
    bl_description = "Reload Minecraft chunk geometry and refresh this container's mesh in-place"
    bl_options = {"REGISTER", "UNDO"}

    run_async: BoolProperty(
        name="Run Asynchronously",
        description="Run calculation in non-blocking background thread with live status bar progress",
        default=True,
        options={"HIDDEN"},
    )  # type: ignore

    _runner: Optional[ModalTaskRunner] = None

    @classmethod
    def poll(cls, context):
        if not context:
            return False
        active = getattr(context, "active_object", None)
        root, mesh, _ = resolve_save_container(active)
        target = root or mesh
        if not target or not hasattr(target, "get"):
            return False
        return bool(target.get("mozi_save_uuid") or target.get("mtk:container_id"))

    def execute(self, context):
        active = getattr(context, "active_object", None)
        root, mesh, cloud = resolve_save_container(active)
        target = root or mesh
        if not target or not hasattr(target, "get"):
            self.report({"WARNING"}, "No valid Minecraft Save container or mesh selected.")
            return {"CANCELLED"}

        save_uuid = str(target.get("mozi_save_uuid") or target.get("mtk:container_id") or "")
        registry = get_save_registry()
        world_dir = registry.get_world_dir(save_uuid)

        if not world_dir or not world_dir.exists():
            self.report(
                {"WARNING"},
                f"Local save path for '{target.get('mtk_world_name', 'Save')}' not found. "
                "Please click 'Relink Save Folder' to associate your local world folder.",
            )
            # Try to invoke relink operator directly if in UI mode
            if hasattr(bpy.ops.mozi, "relink_save_folder"):
                try:
                    return bpy.ops.mozi.relink_save_folder('INVOKE_DEFAULT', target_uuid=save_uuid)
                except Exception:
                    pass
            return {"CANCELLED"}

        dimension = str(target.get("mtk_dimension", "overworld"))
        min_block = tuple(target.get("mtk_min_coord", (-64, -64, -64)))
        max_block = tuple(target.get("mtk_max_coord", (64, 320, 64)))
        enable_ao = bool(target.get("mtk_enable_ao", True))
        mesh_fluids = bool(target.get("mtk_mesh_fluids", True))
        weld_vertices = bool(target.get("mtk_weld_vertices", True))
        origin_centered = bool(target.get("mtk_origin_centered", True))
        level_name = str(target.get("mtk_world_name", "Minecraft World"))
        prefs = get_prefs(context)

        # Synchronous mode (headless / tests)
        if not self.run_async:
            try:
                with blender_progress_scope(context, total=100, title=f"Refreshing {level_name}") as reporter:
                    mesh_data, meta, storage, elapsed_ms = load_and_mesh_minecraft_save(
                        world_dir=world_dir,
                        dimension=dimension,
                        min_block=min_block,
                        max_block=max_block,
                        prefs=prefs,
                        enable_ao=enable_ao,
                        mesh_fluids=mesh_fluids,
                        weld_vertices=weld_vertices,
                        origin_centered=origin_centered,
                        progress_callback=reporter.on_progress,
                    )

                    obj, stats = apply_imported_save_to_blender(
                        mesh_data=mesh_data,
                        meta=meta,
                        storage=storage,
                        elapsed_ms=elapsed_ms,
                        world_dir=world_dir,
                        dimension=dimension,
                        min_block=min_block,
                        max_block=max_block,
                        context=context,
                        prefs=prefs,
                        origin_centered=origin_centered,
                        reuse_existing=True,
                        enable_ao=enable_ao,
                        mesh_fluids=mesh_fluids,
                        weld_vertices=weld_vertices,
                        target_root=root,
                    )

                self.report(
                    {"INFO"},
                    f"Refreshed '{stats['level_name']}': "
                    f"{stats['polygon_count']:,} faces, {stats['voxel_count']:,} voxels "
                    f"in {stats['elapsed_ms']}ms",
                )
                return {"FINISHED"}
            except Exception as e:
                logger.exception("Failed refreshing save model")
                self.report({"ERROR"}, f"Save refresh failed: {e}")
                return {"CANCELLED"}

        # Asynchronous non-blocking modal execution
        task = AsyncTask(
            target=load_and_mesh_minecraft_save,
            kwargs={
                "world_dir": world_dir,
                "dimension": dimension,
                "min_block": min_block,
                "max_block": max_block,
                "prefs": prefs,
                "enable_ao": enable_ao,
                "mesh_fluids": mesh_fluids,
                "weld_vertices": weld_vertices,
                "origin_centered": origin_centered,
            },
        )

        def on_success(result):
            mesh_data, meta, storage, elapsed_ms = result
            obj, stats = apply_imported_save_to_blender(
                mesh_data=mesh_data,
                meta=meta,
                storage=storage,
                elapsed_ms=elapsed_ms,
                world_dir=world_dir,
                dimension=dimension,
                min_block=min_block,
                max_block=max_block,
                context=context,
                prefs=prefs,
                origin_centered=origin_centered,
                reuse_existing=True,
                enable_ao=enable_ao,
                mesh_fluids=mesh_fluids,
                weld_vertices=weld_vertices,
                target_root=root,
            )
            self.report(
                {"INFO"},
                f"Refreshed '{stats['level_name']}': "
                f"{stats['polygon_count']:,} faces, {stats['voxel_count']:,} voxels "
                f"in {stats['elapsed_ms']}ms",
            )

        reporter = BlenderProgressReporter(context=context, total=100, title=f"Refreshing {level_name}")
        self._runner = ModalTaskRunner(
            operator=self,
            context=context,
            task=task,
            reporter=reporter,
            on_success=on_success,
            title=f"Refreshing {level_name}",
        )
        return self._runner.start()

    def modal(self, context, event):
        if self._runner is not None:
            return self._runner.modal(event)
        return {"FINISHED"}


OPERATOR_CLASSES = (
    MOZI_OT_refresh_save_mesh,
)

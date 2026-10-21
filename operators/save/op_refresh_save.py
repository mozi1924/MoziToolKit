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

from ...bridge.assets import reload_atlas_images
from ...bridge.world import prepare_world_mesh_context
from ...bridge.save import load_and_mesh_minecraft_save
from ...utils.assets import (
    can_execute_asset_pipeline,
    prepare_asset_context,
    check_asset_cache_status,
    ensure_pipeline_assets_ready_sync,
    run_task_with_asset_guard,
)
from ...utils.save import apply_imported_save_to_blender
from ...utils.async_task import AsyncTask, ModalTaskRunner
from ...utils.progress import BlenderProgressReporter, blender_progress_scope
from ...utils.system.dependencies import get_prefs
from ...utils.system.save_registry import get_save_registry

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
        if not bool(target.get("mozi_save_uuid") or target.get("mtk:container_id")):
            return False

        prefs = get_prefs(context)
        can_run, reason = can_execute_asset_pipeline(prefs)
        if not can_run:
            if hasattr(cls, "poll_message_set"):
                cls.poll_message_set(reason)
            return False
        return True

    def execute(self, context):
        active = getattr(context, "active_object", None)
        root, mesh, cloud = resolve_save_container(active)
        target = root or mesh
        if not target or not hasattr(target, "get"):
            self.report({"WARNING"}, "No valid Minecraft Save container or mesh selected.")
            return {"CANCELLED"}

        prefs = get_prefs(context)

        # Asset readiness gate: verify valid vanilla client base pack before proceeding
        can_run, reason = can_execute_asset_pipeline(prefs)
        if not can_run:
            self.report({"WARNING"}, reason)
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
        enable_ctm = bool(target.get("mtk_enable_ctm", True))
        enable_animated_textures = bool(target.get("mtk_enable_animated_textures", True))
        level_name = str(target.get("mtk_world_name", "Minecraft World"))

        # Asset readiness gate. All bpy-touching work stays on this main thread;
        # the worker below only receives resolved assets and plain values.
        status = check_asset_cache_status(prefs)
        if status in ("NO_PACKS", "NO_VANILLA"):
            self.report({"WARNING"}, reason)
            return {"CANCELLED"}
        if status in ("MISSING", "STALE"):
            try:
                self.report({"INFO"}, f"Asset cache is {status.lower()}; automatically precompiling before refreshing...")
                success, _ = ensure_pipeline_assets_ready_sync(prefs)
            except Exception as e:
                self.report({"ERROR"}, f"Failed to precompile assets: {e}")
                return {"CANCELLED"}
            if not success:
                self.report({"ERROR"}, "Failed to precompile assets.")
                return {"CANCELLED"}
            status = "READY"

        asset_context = prepare_asset_context(prefs)
        mesh_context = prepare_world_mesh_context(prefs)

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
                        enable_ctm=enable_ctm,
                        enable_animated_textures=enable_animated_textures,
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
                        enable_ctm=enable_ctm,
                        enable_animated_textures=enable_animated_textures,
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

        # Asynchronous non-blocking modal execution with asset guard
        task = AsyncTask(
            target=run_task_with_asset_guard,
            kwargs={
                "target_func": load_and_mesh_minecraft_save,
                "target_kwargs": {
                    "world_dir": world_dir,
                    "dimension": dimension,
                    "min_block": min_block,
                    "max_block": max_block,
                    "prefs": prefs,
                    "enable_ao": enable_ao,
                    "mesh_fluids": mesh_fluids,
                    "weld_vertices": weld_vertices,
                    "origin_centered": origin_centered,
                    "enable_ctm": enable_ctm,
                    "enable_animated_textures": mesh_context["enable_animated_textures"],
                    "model_db": mesh_context["model_db"],
                    "atlas": mesh_context["atlas"],
                    "biome_resolver": mesh_context["biome_resolver"],
                    "ctm_solver": mesh_context["ctm_solver"] if enable_ctm else None,
                    "num_threads": mesh_context["num_threads"],
                    "resolve_prefs": False,
                    "resolve_ctm": False,
                },
                "prefs": prefs,
                "task_title": f"Refreshing {level_name}",
                "asset_context": asset_context,
            },
        )

        def on_success(result_tuple):
            result, did_precompile = result_tuple
            if did_precompile:
                try:
                    reload_atlas_images(prefs)
                except Exception:
                    pass
            mesh_data, meta, storage, elapsed_ms = result
            if mesh_data is not None and getattr(mesh_data, "profile", None) is not None:
                try:
                    from ...bridge.diagnostics import record_operation_profile
                    record_operation_profile(f"Refresh Save ({dimension})", mesh_data.profile)
                except Exception:
                    pass
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
                enable_ctm=enable_ctm,
                enable_animated_textures=enable_animated_textures,
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

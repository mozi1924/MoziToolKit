"""
MoziToolKit Operator: Import Minecraft World / Save.

Provides an open-folder file dialog with bounded 3D coordinate inputs in the sidebar.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

try:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, IntVectorProperty, StringProperty
    from bpy_extras.io_utils import ImportHelper
except ImportError:
    bpy = None
    ImportHelper = object

try:
    from ...bridge.assets import reload_atlas_images
    from ...bridge.world import prepare_world_mesh_context
    from ...bridge.save import (
        inspect_minecraft_save,
        load_and_mesh_minecraft_save,
    )
    from ...utils.assets import (
        can_execute_asset_pipeline,
        prepare_asset_context,
        check_asset_cache_status,
        ensure_pipeline_assets_ready_sync,
        run_task_with_asset_guard,
    )
    from ...utils.save import (
        apply_imported_save_to_blender,
        import_save_to_blender,
    )
    from ...utils.async_task import AsyncTask, ModalTaskRunner
    from ...utils.progress import BlenderProgressReporter
except (ImportError, ValueError):
    from bridge.assets import reload_atlas_images
    from bridge.world import prepare_world_mesh_context
    from bridge.save import (
        inspect_minecraft_save,
        load_and_mesh_minecraft_save,
    )
    from utils.assets import (
        can_execute_asset_pipeline,
        prepare_asset_context,
        check_asset_cache_status,
        ensure_pipeline_assets_ready_sync,
        run_task_with_asset_guard,
    )
    from utils.save import (
        apply_imported_save_to_blender,
        import_save_to_blender,
    )
    from utils.async_task import AsyncTask, ModalTaskRunner
    from utils.progress import BlenderProgressReporter

logger = logging.getLogger("MoziToolKit.Operators.Save")


class MTK_OT_import_minecraft_save(bpy.types.Operator, ImportHelper):
    """Import Minecraft Java Edition world save folder (.mca / level.dat) within a bounded 3D selection"""

    bl_idname = "mtk.import_minecraft_save"
    bl_label = "Import Minecraft World"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        try:
            from ...utils.system.dependencies import get_prefs
            prefs = get_prefs(context)
        except Exception:
            prefs = None
        can_run, reason = can_execute_asset_pipeline(prefs)
        if not can_run:
            if hasattr(cls, "poll_message_set"):
                cls.poll_message_set(reason)
            return False
        return True

    # Directory picker configuration
    directory: StringProperty(
        name="World Folder",
        description="Select the Minecraft world save folder containing level.dat or region files",
        subtype="DIR_PATH",
    ) # type: ignore

    # Filter out non-folders
    filter_folder: BoolProperty(
        default=True,
        options={"HIDDEN"},
    ) # type: ignore

    dimension: EnumProperty(
        name="Dimension",
        description="World dimension to import from",
        items=[
            ("overworld", "Overworld", "Overworld dimension (region/ or dimensions/minecraft/overworld)"),
            ("the_nether", "The Nether", "Nether dimension (DIM-1/ or dimensions/minecraft/the_nether)"),
            ("the_end", "The End", "The End dimension (DIM1/ or dimensions/minecraft/the_end)"),
        ],
        default="overworld",
    ) # type: ignore

    min_coord: IntVectorProperty(
        name="Min Coordinate",
        description="Minimum block coordinate [X, Y, Z] to import",
        size=3,
        default=(-64, -64, -64),
    ) # type: ignore

    max_coord: IntVectorProperty(
        name="Max Coordinate",
        description="Maximum block coordinate [X, Y, Z] to import",
        size=3,
        default=(64, 320, 64),
    ) # type: ignore

    enable_ao: BoolProperty(
        name="Ambient Occlusion",
        description="Calculate smooth 4-corner ambient occlusion lighting",
        default=True,
    ) # type: ignore

    mesh_fluids: BoolProperty(
        name="Mesh Fluids",
        description="Mesh physically accurate top and side fluid surfaces",
        default=True,
    ) # type: ignore

    weld_vertices: BoolProperty(
        name="Weld Vertices",
        description="Weld adjacent shared coplanar vertices into seamless manifold topology",
        default=True,
    ) # type: ignore

    origin_centered: BoolProperty(
        name="Origin Centered",
        description="Center imported world geometry at the scene origin [0, 0, 0]",
        default=True,
    ) # type: ignore

    enable_ctm: BoolProperty(
        name="Connected Textures (CTM)",
        description="Enable OptiFine / Continuity connected textures during world meshing",
        default=True,
    ) # type: ignore

    enable_animated_textures: BoolProperty(
        name="Animated Textures",
        description="Enable animated texture frame playback for water, lava, fire, portals, and animated blocks",
        default=True,
    ) # type: ignore

    run_async: BoolProperty(
        name="Run Asynchronously",
        description="Run calculation in non-blocking background thread with live status bar progress",
        default=True,
        options={"HIDDEN"},
    ) # type: ignore

    _runner: Optional[ModalTaskRunner] = None

    def draw(self, context):
        try:
            from ...i18n import tr
        except (ImportError, ValueError):
            from i18n import tr
        layout = self.layout

        # 1. Dimension selection
        box_dim = layout.box()
        box_dim.label(text=tr("Dimension"), icon="WORLD")
        box_dim.prop(self, "dimension", text="")

        # 2. 3D Bounding Box selection
        box_coords = layout.box()
        box_coords.label(text=tr("3D Selection Bounds (Blocks)"), icon="SNAP_INCREMENT")
        col_coords = box_coords.column(align=True)
        col_coords.prop(self, "min_coord", text=tr("Min Coordinate"))
        col_coords.prop(self, "max_coord", text=tr("Max Coordinate"))

        # Range preview
        dx = abs(self.max_coord[0] - self.min_coord[0]) + 1
        dy = abs(self.max_coord[1] - self.min_coord[1]) + 1
        dz = abs(self.max_coord[2] - self.min_coord[2]) + 1
        vol = dx * dy * dz
        box_coords.label(
            text=f"{tr('Size')}: {dx} × {dy} × {dz} ({vol:,} {tr('blocks')})",
            icon="INFO",
        )

        # 3. Meshing & Shading Options
        box_mesh = layout.box()
        box_mesh.label(text=tr("Meshing & Shaders"), icon="MATERIAL")
        box_mesh.prop(self, "enable_ao", text=tr("Ambient Occlusion"))
        box_mesh.prop(self, "mesh_fluids", text=tr("Mesh Fluids"))
        box_mesh.prop(self, "weld_vertices", text=tr("Weld Vertices"))
        box_mesh.prop(self, "origin_centered", text=tr("Origin Centered"))
        box_mesh.prop(self, "enable_ctm", text=tr("Connected Textures (CTM)"))
        box_mesh.prop(self, "enable_animated_textures", text=tr("Animated Textures"))

    def execute(self, context):
        target_dir = self.directory or getattr(self, "filepath", "")
        if not target_dir:
            self.report({"ERROR"}, "Please select a valid Minecraft world save folder.")
            return {"CANCELLED"}

        path = Path(target_dir)
        if path.is_file():
            path = path.parent

        if not path.exists():
            self.report({"ERROR"}, f"Folder does not exist: {path}")
            return {"CANCELLED"}

        try:
            from ...utils.system.dependencies import get_prefs
            prefs = get_prefs()
        except Exception:
            prefs = None

        # Asset readiness gate: verify valid vanilla client base pack before proceeding
        can_run, reason = can_execute_asset_pipeline(prefs)
        if not can_run:
            self.report({"WARNING"}, reason)
            return {"CANCELLED"}

        # Asset readiness gate. Precompilation and asset loading touch bpy, so they
        # must run here on the main thread; the AsyncTask below receives only
        # resolved Python/Rust objects.
        status = check_asset_cache_status(prefs)
        if status in ("NO_PACKS", "NO_VANILLA"):
            self.report({"WARNING"}, reason)
            return {"CANCELLED"}
        if status in ("MISSING", "STALE"):
            try:
                self.report({"INFO"}, f"Asset cache is {status.lower()}; automatically precompiling before importing...")
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

        min_c = tuple(self.min_coord)
        max_c = tuple(self.max_coord)

        # Synchronous fallback for CLI / tests when run_async is explicitly False
        if not self.run_async:
            try:
                try:
                    from ...utils.progress import blender_progress_scope
                except (ImportError, ValueError):
                    from utils.progress import blender_progress_scope

                with blender_progress_scope(context, total=100, title=f"Import {self.dimension}") as reporter:
                    obj, stats = import_save_to_blender(
                        world_dir=path,
                        dimension=self.dimension,
                        min_block=min_c,
                        max_block=max_c,
                        context=context,
                        prefs=prefs,
                        enable_ao=self.enable_ao,
                        mesh_fluids=self.mesh_fluids,
                        weld_vertices=self.weld_vertices,
                        origin_centered=self.origin_centered,
                        enable_ctm=self.enable_ctm,
                        enable_animated_textures=self.enable_animated_textures,
                        progress_callback=reporter.on_progress,
                    )

                self.report(
                    {"INFO"},
                    f"Imported '{stats['level_name']}' ({self.dimension}): "
                    f"{stats['polygon_count']:,} faces, {stats['voxel_count']:,} voxels "
                    f"in {stats['elapsed_ms']}ms",
                )
                return {"FINISHED"}
            except Exception as e:
                logger.exception("Failed importing Minecraft world save")
                self.report({"ERROR"}, f"Save import failed: {e}")
                return {"CANCELLED"}

        # Asynchronous non-blocking modal execution (UI mode) with asset guard
        task = AsyncTask(
            target=run_task_with_asset_guard,
            kwargs={
                "target_func": load_and_mesh_minecraft_save,
                "target_kwargs": {
                    "world_dir": path,
                    "dimension": self.dimension,
                    "min_block": min_c,
                    "max_block": max_c,
                    "prefs": prefs,
                    "enable_ao": self.enable_ao,
                    "mesh_fluids": self.mesh_fluids,
                    "weld_vertices": self.weld_vertices,
                    "origin_centered": self.origin_centered,
                    "enable_ctm": self.enable_ctm,
                    "enable_animated_textures": mesh_context["enable_animated_textures"],
                    "model_db": mesh_context["model_db"],
                    "atlas": mesh_context["atlas"],
                    "biome_resolver": mesh_context["biome_resolver"],
                    "ctm_solver": mesh_context["ctm_solver"] if self.enable_ctm else None,
                    "num_threads": mesh_context["num_threads"],
                    "resolve_prefs": False,
                    "resolve_ctm": False,
                },
                "prefs": prefs,
                "task_title": f"Import {self.dimension}",
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
            obj, stats = apply_imported_save_to_blender(
                mesh_data=mesh_data,
                meta=meta,
                storage=storage,
                elapsed_ms=elapsed_ms,
                world_dir=path,
                dimension=self.dimension,
                min_block=min_c,
                max_block=max_c,
                context=context,
                prefs=prefs,
                origin_centered=self.origin_centered,
                enable_ao=self.enable_ao,
                mesh_fluids=self.mesh_fluids,
                weld_vertices=self.weld_vertices,
                enable_ctm=self.enable_ctm,
                enable_animated_textures=self.enable_animated_textures,
            )
            self.report(
                {"INFO"},
                f"Imported '{stats['level_name']}' ({self.dimension}): "
                f"{stats['polygon_count']:,} faces, {stats['voxel_count']:,} voxels "
                f"in {stats['elapsed_ms']}ms",
            )

        reporter = BlenderProgressReporter(context=context, total=100, title=f"Import {self.dimension}")
        self._runner = ModalTaskRunner(
            operator=self,
            context=context,
            task=task,
            reporter=reporter,
            on_success=on_success,
            title=f"Import {self.dimension}",
        )
        return self._runner.start()

    def modal(self, context, event):
        if self._runner is not None:
            return self._runner.modal(event)
        return {"FINISHED"}


OPERATOR_CLASSES = (
    MTK_OT_import_minecraft_save,
)

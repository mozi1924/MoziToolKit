"""
MoziToolKit Dev Operator: Load Embedded Debug World.
"""

from typing import Optional
import bpy
try:
    from ... import bridge
    from ...utils.async_task import AsyncTask, ModalTaskRunner
    from ...utils.progress import BlenderProgressReporter
except (ImportError, ValueError):
    import bridge
    from utils.async_task import AsyncTask, ModalTaskRunner
    from utils.progress import BlenderProgressReporter


class MOZI_OT_dev_load_debug_world(bpy.types.Operator):
    """Mesh and load canonical embedded Minecraft debug world with models and PBR materials into the active scene"""

    bl_idname = "mozi.dev_load_debug_world"
    bl_label = "Load Debug World"
    bl_description = "Mesh and load canonical embedded Minecraft debug world with models and PBR materials into the active scene"
    bl_options = {"REGISTER", "UNDO"}

    enable_ao: bpy.props.BoolProperty(
        name="Smooth AO",
        description="Calculate 4-corner ambient occlusion lighting",
        default=True,
    )

    mesh_fluids: bpy.props.BoolProperty(
        name="Mesh Fluids",
        description="Include physically accurate fluid surfaces",
        default=True,
    )

    weld_vertices: bpy.props.BoolProperty(
        name="Weld Vertices",
        description="Weld adjacent coplanar vertices into manifold topology",
        default=True,
    )

    origin_centered: bpy.props.BoolProperty(
        name="Center Origin",
        description="Center mesh bounds around world origin (0, 0, 0)",
        default=True,
    )

    run_async: bpy.props.BoolProperty(
        name="Run Asynchronously",
        description="Run calculation in non-blocking background thread with live status bar progress",
        default=True,
        options={"HIDDEN"},
    )

    _runner: Optional[ModalTaskRunner] = None

    def execute(self, context):
        if not bridge.is_debug_world_available():
            self.report({"ERROR"}, "libmtk_py debug world capability is unavailable")
            return {"CANCELLED"}

        try:
            from ...utils.system.dependencies import get_prefs
            prefs = get_prefs()
        except Exception:
            prefs = None

        # Synchronous fallback for CLI / tests when run_async is explicitly False
        if not self.run_async:
            try:
                obj, stats = bridge.create_debug_world_object(
                    context=context,
                    name="MTK_Debug_World",
                    prefs=prefs,
                    enable_ao=self.enable_ao,
                    mesh_fluids=self.mesh_fluids,
                    weld_vertices=self.weld_vertices,
                    origin_centered=self.origin_centered,
                )
                poly_count = stats.get("polygon_count", stats.get("quad_count", 0))
                mat_count = stats.get("materials_count", len(obj.data.materials) if obj and obj.data else 0)
                elapsed_ms = stats.get("meshing_time_ms", stats.get("elapsed_ms", 0.0))

                self.report(
                    {"INFO"},
                    f"Loaded Debug World: {poly_count:,} faces, {stats['vertex_count']:,} verts, {mat_count} materials in {elapsed_ms:.1f}ms",
                )
                return {"FINISHED"}
            except Exception as e:
                self.report({"ERROR"}, f"Failed to load debug world: {e}")
                return {"CANCELLED"}

        # Asynchronous non-blocking modal execution (UI mode)
        task = AsyncTask(
            target=bridge.build_debug_world_data,
            kwargs={
                "prefs": prefs,
                "enable_ao": self.enable_ao,
                "mesh_fluids": self.mesh_fluids,
                "weld_vertices": self.weld_vertices,
                "origin_centered": self.origin_centered,
            },
        )

        def on_success(result):
            mesh_data, storage, elapsed_ms = result
            obj, stats = bridge.apply_voxel_mesh_to_blender(
                mesh_data=mesh_data,
                storage=storage,
                elapsed_ms=elapsed_ms,
                context=context,
                name="MTK_Debug_World",
                prefs=prefs,
                origin_centered=self.origin_centered,
            )
            poly_count = stats.get("polygon_count", stats.get("quad_count", 0))
            mat_count = stats.get("materials_count", len(obj.data.materials) if obj and obj.data else 0)
            self.report(
                {"INFO"},
                f"Loaded Debug World: {poly_count:,} faces, {stats['vertex_count']:,} verts, {mat_count} materials in {elapsed_ms:.1f}ms",
            )

        reporter = BlenderProgressReporter(context=context, total=100, title="Load Debug World")
        self._runner = ModalTaskRunner(
            operator=self,
            context=context,
            task=task,
            reporter=reporter,
            on_success=on_success,
            title="Load Debug World",
        )
        return self._runner.start()

    def modal(self, context, event):
        if self._runner is not None:
            return self._runner.modal(event)
        return {"FINISHED"}

"""
MoziToolKit Dev Operator: Mesher Benchmark.
"""

import bpy
from ..api import run_mesher_benchmark
try:
    from ... import bridge
except (ImportError, ValueError):
    try:
        from MoziToolKit import bridge
    except (ImportError, ValueError):
        import bridge


class MOZI_OT_dev_mesh_benchmark(bpy.types.Operator):
    """Run mesher speed benchmark on the embedded 32k-block debug world"""

    bl_idname = "mozi.dev_mesh_benchmark"
    bl_label = "Run Mesher Benchmark"
    bl_description = "Run raw meshing speed benchmark on the embedded 32k-block debug world"
    bl_options = {"REGISTER"}

    iterations: bpy.props.IntProperty(
        name="Iterations",
        description="Number of benchmark iterations to average",
        default=3,
        min=1,
        max=10,
    )

    @classmethod
    def poll(cls, context):
        try:
            from ...utils.system.dependencies import get_prefs
            prefs = get_prefs(context)
        except Exception:
            prefs = None
        return bridge.is_debug_world_available(prefs)

    def execute(self, context):
        try:
            from ...utils.system.dependencies import get_prefs
            prefs = get_prefs(context)
        except Exception:
            prefs = None

        if not bridge.is_debug_world_available(prefs):
            self.report({"ERROR"}, "libmtk_py debug world capability is unavailable or vanilla client assets not configured")
            return {"CANCELLED"}

        try:
            stats = run_mesher_benchmark(iterations=self.iterations, prefs=prefs)
            msg = (
                f"Benchmark: {stats['avg_ms']}ms avg ({stats['quads_per_second']:,} quads/sec) "
                f"[{stats['quad_count']:,} quads]"
            )
            self.report({"INFO"}, msg)
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, f"Benchmark failed: {e}")
            return {"CANCELLED"}


class MOZI_OT_dev_clear_profile(bpy.types.Operator):
    """Clear cached operation profile"""

    bl_idname = "mozi.dev_clear_profile"
    bl_label = "Clear Execution Profile"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        try:
            from ..profile_tracker import clear_last_profile
            clear_last_profile()
        except Exception:
            pass
        return {"FINISHED"}

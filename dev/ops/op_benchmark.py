"""
MoziToolKit Dev Operator: Mesher Benchmark.
"""

import bpy
from ..api import run_mesher_benchmark
from ... import bridge


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

    def execute(self, context):
        if not bridge.is_debug_world_available():
            self.report({"ERROR"}, "libmtk_py debug world capability is unavailable")
            return {"CANCELLED"}

        try:
            stats = run_mesher_benchmark(iterations=self.iterations)
            msg = (
                f"Benchmark: {stats['avg_ms']}ms avg ({stats['quads_per_second']:,} quads/sec) "
                f"[{stats['quad_count']:,} quads]"
            )
            self.report({"INFO"}, msg)
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, f"Benchmark failed: {e}")
            return {"CANCELLED"}

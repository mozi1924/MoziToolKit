"""
Foliage Vertex Groups Pipeline Step for MoziToolKit.

Scans selected mesh objects for foliage metadata in `mtk_source_texture_key`
and creates MTK_Foliage_All, MTK_Foliage_Leaves, MTK_Foliage_Plants vertex groups.
"""

from typing import Iterator, Union

from ..context import PipelineContext
from ..progress import ProgressUpdate
from ..step import PipelineStep, StepResult

try:
    from ...utils.foliage import assign_foliage_vertex_groups
except (ImportError, ValueError):
    from utils.foliage import assign_foliage_vertex_groups


class FoliageVertexGroupsStep(PipelineStep):
    name = "Identify Foliage & Create Vertex Groups"
    description = "Scans mesh metadata to identify leaves and plants and generates vertex groups"

    def execute_iter(self, ctx: PipelineContext) -> Iterator[Union[ProgressUpdate, StepResult]]:
        mesh_objs = [obj for obj in ctx.target_objects if obj.type == 'MESH']
        if not mesh_objs:
            yield StepResult.cancelled("No mesh objects selected.")
            return

        protect_rigid = self.get_param(ctx, "protect_rigid_vertices", True)
        total_objs = len(mesh_objs)
        processed_count = 0
        total_foliage_verts = 0

        for idx, obj in enumerate(mesh_objs):
            if ctx.is_cancelled:
                yield StepResult.cancelled("Operation cancelled by user.")
                return

            yield ProgressUpdate(
                current=idx,
                total=total_objs,
                message=f"Scanning foliage metadata: {obj.name} ({idx + 1}/{total_objs})...",
            )

            res = assign_foliage_vertex_groups(obj, protect_rigid_vertices=protect_rigid)
            if res and res.get("total_foliage_verts", 0) > 0:
                processed_count += 1
                total_foliage_verts += res.get("total_foliage_verts", 0)

        yield ProgressUpdate(
            current=total_objs,
            total=total_objs,
            message="Foliage scanning complete.",
        )

        msg = f"Created foliage vertex groups for {processed_count}/{total_objs} object(s) ({total_foliage_verts} total foliage vertices)."
        ctx.set_data("foliage_processed_objects", processed_count)
        ctx.set_data("foliage_total_verts", total_foliage_verts)
        yield StepResult.success(msg, {"processed_count": processed_count, "total_foliage_verts": total_foliage_verts})

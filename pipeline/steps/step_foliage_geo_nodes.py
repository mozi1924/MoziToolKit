"""
Foliage Geometry Nodes Pipeline Step for MoziToolKit.

Generates the MTK_Foliage_Wiggle geometry node setup and attaches the modifier
to selected objects with configured wind and scope parameters.
"""

from typing import Iterator, Union

from ..context import PipelineContext
from ..progress import ProgressUpdate
from ..step import PipelineStep, StepResult

try:
    from ...utils.foliage import (
        get_or_create_foliage_node_group,
        apply_foliage_modifier,
        SCOPE_TO_GROUP,
        GROUP_NAME_ALL,
    )
except (ImportError, ValueError):
    from utils.foliage import (
        get_or_create_foliage_node_group,
        apply_foliage_modifier,
        SCOPE_TO_GROUP,
        GROUP_NAME_ALL,
    )


class FoliageGeoNodesStep(PipelineStep):
    name = "Setup Foliage Wind Geometry Nodes"
    description = "Creates/updates the MTK_Foliage_Wiggle node group and applies modifier to targets"

    def execute_iter(self, ctx: PipelineContext) -> Iterator[Union[ProgressUpdate, StepResult]]:
        mesh_objs = [obj for obj in ctx.target_objects if obj.type == 'MESH']
        if not mesh_objs:
            yield StepResult.cancelled("No mesh objects selected.")
            return

        rebuild_node_group = self.get_param(ctx, "rebuild_node_group", False)
        target_scope = self.get_param(ctx, "foliage_target_scope", "ALL")
        target_group_name = SCOPE_TO_GROUP.get(target_scope, GROUP_NAME_ALL)

        wind_direction = self.get_param(ctx, "wind_direction", 45.0)
        wiggle_amplitude = self.get_param(ctx, "wiggle_amplitude", 0.06)
        wiggle_speed = self.get_param(ctx, "wiggle_speed", 3.0)
        noise_scale = self.get_param(ctx, "noise_scale", 1.2)

        yield ProgressUpdate(
            current=0.0,
            total=1.0,
            message="Building Foliage Wind Geometry Node Group...",
        )

        ng = get_or_create_foliage_node_group(rebuild=rebuild_node_group)

        total_objs = len(mesh_objs)
        applied_count = 0

        for idx, obj in enumerate(mesh_objs):
            if ctx.is_cancelled:
                yield StepResult.cancelled("Operation cancelled by user.")
                return

            yield ProgressUpdate(
                current=idx,
                total=total_objs,
                message=f"Applying Foliage Wind modifier: {obj.name} ({idx + 1}/{total_objs})...",
            )

            mod = apply_foliage_modifier(
                obj=obj,
                node_group=ng,
                target_scope_group=target_group_name,
                wind_direction=wind_direction,
                wiggle_amplitude=wiggle_amplitude,
                wiggle_speed=wiggle_speed,
                noise_scale=noise_scale,
            )
            if mod:
                applied_count += 1

        yield ProgressUpdate(
            current=total_objs,
            total=total_objs,
            message="Applied foliage wind modifier to all targets.",
        )

        msg = f"Applied Foliage Wind modifier to {applied_count} object(s) with scope '{target_group_name}'."
        ctx.set_data("foliage_applied_modifiers", applied_count)
        yield StepResult.success(msg, {"applied_count": applied_count, "group_name": target_group_name})

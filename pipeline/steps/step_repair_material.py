"""
Pipeline Step for Inspecting and Repairing MoziToolKit Material Shader Nodes.
Repairs LabPBR 1.3 Decoder links, animated UV groups, scheduler drivers, and node templates.
"""

from pathlib import Path
import bpy
from ..step import PipelineStep, StepResult
try:
    from ...utils.zip_resource_pack import ZipResourcePack
    from ...utils.material_builder import repair_material_nodes, inspect_material_nodes
except (ImportError, ValueError):
    from utils.zip_resource_pack import ZipResourcePack
    from utils.material_builder import repair_material_nodes, inspect_material_nodes


class StepRepairMaterial(PipelineStep):
    """Pipeline step to repair and reconstruct damaged LabPBR decoder and animated UV node graphs."""

    name = "repair_material"
    description = "Repair and reconstruct LabPBR and animated UV shader node trees"

    def execute(self, pipeline_context) -> StepResult:
        force_rebuild = pipeline_context.get_param("force_rebuild", False)
        zip_path = pipeline_context.get_param("zip_path", "")
        use_cache = pipeline_context.get_param("use_cache", True)

        pack = None
        if zip_path and Path(zip_path).exists():
            try:
                pack = ZipResourcePack(zip_path, use_cache=use_cache)
            except Exception as e:
                pipeline_context.report("WARNING", f"Could not load resource pack: {e}")

        target_objects = pipeline_context.target_objects
        if not target_objects:
            return StepResult.failed("No objects selected for material repair.")

        materials_to_process = set()
        for obj in target_objects:
            if obj.type == "MESH" and obj.material_slots:
                for slot in obj.material_slots:
                    if slot.material and slot.material.use_nodes:
                        materials_to_process.add(slot.material)

        if not materials_to_process:
            return StepResult.success("No nodal materials found on selected objects.")

        repaired_count = 0
        inspected_count = len(materials_to_process)

        for mat in materials_to_process:
            report = inspect_material_nodes(mat)
            if not report.get("is_healthy") or force_rebuild:
                success = repair_material_nodes(mat, resource_pack=pack, force_rebuild=force_rebuild)
                if success:
                    repaired_count += 1
                    pipeline_context.report("INFO", f"Repaired shader nodes for material '{mat.name}'")
            else:
                # Even if healthy, ensure template versions are up to date
                repair_material_nodes(mat, resource_pack=pack, force_rebuild=False)

        return StepResult.success(
            f"Material repair complete: inspected {inspected_count} material(s), repaired/updated {repaired_count}."
        )

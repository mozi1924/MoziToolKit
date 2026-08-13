import os
from pathlib import Path
import bpy
from ..step import PipelineStep, StepResult
from ...utils.zip_resource_pack import ZipResourcePack
from ...utils.material_builder import rebuild_material


def extract_material_texture_key(mat: bpy.types.Material) -> str:
    """Extract texture basename key from material's existing TexImage nodes or material name."""
    if not mat or not mat.use_nodes or not mat.node_tree:
        return mat.name if mat else ""

    # Strategy 1: Check existing image nodes for image filepaths/names
    for node in mat.node_tree.nodes:
        if node.type == 'TEX_IMAGE' and node.image:
            fp = node.image.filepath or node.image.name
            clean_fp = fp.replace("//textures/", "").replace("//", "")
            basename = os.path.splitext(os.path.basename(clean_fp))[0]
            # Strip Blender duplicate suffix (.001, .002)
            if "." in basename and basename.split(".")[-1].isdigit():
                basename = basename.rsplit(".", 1)[0]
            if basename:
                return basename

    # Strategy 2: Fallback to material name cleaning
    name = mat.name.lower()
    for suffix in ["_all", "_side", "_end", "_top", "_bottom", "_texture", "item_"]:
        name = name.replace(suffix, "")
    return name.strip()


class StepReplaceMaterial(PipelineStep):
    """Pipeline step to parse Minecraft Java resource pack and reconstruct LabPBR materials."""

    name = "replace_material"
    description = "Replace and reconstruct LabPBR materials from Minecraft Java Resource Pack"

    def execute(self, pipeline_context) -> StepResult:
        zip_path = pipeline_context.get_param("zip_path")
        pack_textures = pipeline_context.get_param("pack_textures", True)
        use_cache = pipeline_context.get_param("use_cache", True)

        if not zip_path or not Path(zip_path).exists():
            return StepResult.failed("Resource pack ZIP file not specified or found.")

        target_objects = pipeline_context.target_objects
        if not target_objects:
            return StepResult.failed("No objects selected for material replacement.")

        try:
            pack = ZipResourcePack(zip_path, use_cache=use_cache)
        except Exception as e:
            return StepResult.failed(f"Failed to load resource pack: {e}")

        replaced_count = 0
        processed_materials = set()

        for obj in target_objects:
            if obj.type != 'MESH' or not obj.material_slots:
                continue

            for slot in obj.material_slots:
                mat = slot.material
                if not mat or mat in processed_materials:
                    continue

                processed_materials.add(mat)
                key = extract_material_texture_key(mat)
                tex_info = pack.get_texture_info(key)

                if tex_info:
                    success = rebuild_material(mat, tex_info, pack_textures=pack_textures)
                    if success:
                        replaced_count += 1
                        pipeline_context.report("INFO", f"Replaced material '{mat.name}' with pack texture '{key}'")
                else:
                    pipeline_context.report("WARNING", f"No matching pack texture found for material '{mat.name}' (Key: '{key}')")

        if replaced_count == 0:
            return StepResult.failed("No matching materials found in selected objects for this resource pack.")

        return StepResult.success(f"Successfully replaced {replaced_count} materials.")


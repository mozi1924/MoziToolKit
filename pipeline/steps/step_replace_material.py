from pathlib import Path
import bpy
from ..step import PipelineStep, StepResult
try:
    from ...utils.zip_resource_pack import ZipResourcePack
    from ...utils.material_builder import rebuild_material
    from ...utils.material_matching import extract_material_texture_keys
except (ImportError, ValueError):
    from utils.zip_resource_pack import ZipResourcePack
    from utils.material_builder import rebuild_material
    from utils.material_matching import extract_material_texture_keys


def name_replaced_material(mat: bpy.types.Material, texture_info: dict, pack: ZipResourcePack) -> None:
    """Assign a compact visible identity and durable provenance metadata."""
    namespace = texture_info["namespace"]
    texture_name = texture_info["texture_name"]
    full_hash = pack.pack_hash
    mat.name = f"mtk:{namespace}:{texture_name}:{full_hash[:12]}"
    mat["mtk:source_namespace"] = namespace
    mat["mtk:source_texture"] = texture_name
    mat["mtk:material_id"] = f"{namespace}:{texture_name}"
    mat["mtk:pack_hash"] = full_hash
    mat["mtk:pack_hash_short"] = full_hash[:12]


def find_existing_replacement(texture_info: dict, pack: ZipResourcePack) -> bpy.types.Material | None:
    """Find an existing material datablock matching the exact pack hash and texture key."""
    namespace = texture_info["namespace"]
    texture_name = texture_info["texture_name"]
    for material in bpy.data.materials:
        if (material.get("mtk:source_namespace") == namespace
                and material.get("mtk:source_texture") == texture_name
                and material.get("mtk:pack_hash") == pack.pack_hash):
            return material
    return None


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
        processed_materials = {}
        session_materials = {}

        def get_or_create_replacement_material(texture_info):
            """Reuse material if exact pack hash and texture match; otherwise create a new material."""
            texture_key = (texture_info["namespace"], texture_info["texture_name"])
            
            # Check for matching material in scene (same pack_hash + texture_name)
            canonical_mat = find_existing_replacement(texture_info, pack)
            if not canonical_mat:
                canonical_mat = session_materials.get(texture_key)

            if canonical_mat:
                return canonical_mat, False

            # Create a new independent material datablock for this pack
            mat_name = f"mtk:{texture_info['namespace']}:{texture_info['texture_name']}"
            mat = bpy.data.materials.new(name=mat_name)
            if not rebuild_material(mat, texture_info, pack_textures=pack_textures):
                bpy.data.materials.remove(mat)
                return None, False

            name_replaced_material(mat, texture_info, pack)
            session_materials[texture_key] = mat
            return mat, True

        for obj in target_objects:
            if obj.type != 'MESH' or not obj.material_slots:
                continue

            for slot in obj.material_slots:
                original_mat = slot.material
                if not original_mat:
                    continue

                if original_mat in processed_materials:
                    slot.material = processed_materials[original_mat]
                    continue

                namespace, candidates = extract_material_texture_keys(original_mat)
                key = next((candidate for candidate in candidates
                            if pack.get_texture_info(candidate, namespace)), None)
                tex_info = pack.get_texture_info(key, namespace) if key else None

                # A normal/specular-only entry is not a complete replacement.
                # Leave the material intact unless its exact name resolves to
                # an albedo texture in the chosen resource pack.
                if tex_info and tex_info.get("albedo"):
                    original_name = original_mat.name
                    mat, is_new = get_or_create_replacement_material(tex_info)
                    if mat:
                        slot.material = mat
                        processed_materials[original_mat] = mat
                        if is_new:
                            replaced_count += 1
                            pipeline_context.report("INFO", f"Replaced material '{original_name}' with pack texture '{namespace}:{key}'")
                        else:
                            pipeline_context.report("INFO", f"Reused existing material '{mat.name}' for '{original_name}'")
                    else:
                        pipeline_context.report("WARNING", f"Could not build replacement material for '{original_name}'.")
                else:
                    attempted = ", ".join(f"{namespace}:{candidate}" for candidate in candidates) or "no usable material key"
                    pipeline_context.report("INFO", f"Kept material '{original_mat.name}' unchanged: no exact pack match ({attempted}).")

        if replaced_count == 0 and not processed_materials:
            return StepResult.success("No exact material matches found; selected objects were left unchanged.")

        return StepResult.success(f"Successfully replaced {len(processed_materials)} material slot(s) ({replaced_count} new material(s) created).")



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


def find_existing_replacement(texture_info: dict, pack: ZipResourcePack):
    """Find the canonical material for this exact pack texture, if any."""
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
        replacement_materials = set()
        rebuilt_materials = set()
        selected_objects = set(target_objects)

        def rebuild_replacement_material(material, texture_info):
            """Restore the complete canonical node tree once per datablock.

            A canonical ``mtk:`` material can be reused by many slots.  It
            must still be rebuilt when selected for replacement: reassigning
            the datablock alone leaves any manually broken or stale nodes in
            place.  Tracking rebuilt datablocks avoids doing the same work
            repeatedly for shared slots.
            """
            if material in rebuilt_materials:
                return True
            if not rebuild_material(material, texture_info, pack_textures=pack_textures):
                return False
            name_replaced_material(material, texture_info, pack)
            rebuilt_materials.add(material)
            return True

        def material_is_used_outside_selection(material):
            """Whether changing this datablock would alter an unselected object."""
            for candidate in bpy.data.objects:
                if candidate.type != 'MESH' or candidate in selected_objects:
                    continue
                if any(slot.material == material for slot in candidate.material_slots):
                    return True
            return False

        for obj in target_objects:
            if obj.type != 'MESH' or not obj.material_slots:
                continue

            for slot in obj.material_slots:
                original_mat = slot.material
                if not original_mat:
                    continue

                # A material datablock may be shared by selected and
                # unselected meshes.  Copy it before editing so this operator
                # has no visual side effect outside the selection.
                if original_mat in processed_materials:
                    slot.material = processed_materials[original_mat]
                    continue
                if original_mat in replacement_materials:
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
                    canonical_mat = find_existing_replacement(tex_info, pack)
                    if canonical_mat and canonical_mat != original_mat:
                        # Several Ice Cube face-role materials can point to one
                        # source texture (for example, top/bottom).  Reuse one
                        # material datablock when it is scoped to the current
                        # selection.  Crucially, do not merely assign it:
                        # rebuilding makes replacement a reliable repair
                        # operation for damaged node trees.
                        material_to_assign = canonical_mat
                        if material_is_used_outside_selection(canonical_mat):
                            material_to_assign = canonical_mat.copy()
                        if rebuild_replacement_material(material_to_assign, tex_info):
                            processed_materials[original_mat] = material_to_assign
                            for selected_obj in selected_objects:
                                for selected_slot in selected_obj.material_slots:
                                    if selected_slot.material == original_mat:
                                        selected_slot.material = material_to_assign
                            replaced_count += 1
                            pipeline_context.report("INFO", f"Rebuilt and assigned existing material '{material_to_assign.name}' for '{original_name}'.")
                        else:
                            pipeline_context.report("WARNING", f"Could not rebuild existing material '{material_to_assign.name}' for '{original_name}'.")
                        continue
                    if canonical_mat == original_mat:
                        material_to_rebuild = original_mat
                        if material_is_used_outside_selection(original_mat):
                            material_to_rebuild = original_mat.copy()
                            for selected_obj in selected_objects:
                                for selected_slot in selected_obj.material_slots:
                                    if selected_slot.material == original_mat:
                                        selected_slot.material = material_to_rebuild
                        if rebuild_replacement_material(material_to_rebuild, tex_info):
                            processed_materials[original_mat] = material_to_rebuild
                            replaced_count += 1
                            pipeline_context.report("INFO", f"Rebuilt existing material '{original_name}' from pack texture '{namespace}:{key}'")
                        else:
                            pipeline_context.report("WARNING", f"Could not rebuild existing material '{original_name}'.")
                        continue
                    mat = original_mat
                    if material_is_used_outside_selection(original_mat):
                        mat = original_mat.copy()
                        for selected_obj in selected_objects:
                            for selected_slot in selected_obj.material_slots:
                                if selected_slot.material == original_mat:
                                    selected_slot.material = mat
                    processed_materials[original_mat] = mat
                    replacement_materials.add(mat)
                    success = rebuild_replacement_material(mat, tex_info)
                    if success:
                        replaced_count += 1
                        pipeline_context.report("INFO", f"Replaced material '{original_name}' with pack texture '{namespace}:{key}'")
                else:
                    attempted = ", ".join(f"{namespace}:{candidate}" for candidate in candidates) or "no usable material key"
                    pipeline_context.report("INFO", f"Kept material '{original_mat.name}' unchanged: no exact pack match ({attempted}).")

        if replaced_count == 0:
            return StepResult.success("No exact material matches found; selected objects were left unchanged.")

        return StepResult.success(f"Successfully replaced {replaced_count} materials.")

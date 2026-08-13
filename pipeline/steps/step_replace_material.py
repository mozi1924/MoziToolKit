from pathlib import Path
import bpy
from ..step import PipelineStep, StepResult
from ...utils.zip_resource_pack import ZipResourcePack
from ...utils.material_builder import rebuild_material


def _without_blender_suffix(value: str) -> str:
    """Remove Blender's duplicate suffix, without altering the actual name."""
    if "." in value and value.rsplit(".", 1)[1].isdigit():
        return value.rsplit(".", 1)[0]
    return value


def _ice_cube_name_aliases(name: str) -> list[str]:
    """Return explicit Ice Cube material-name aliases, in priority order.

    Ice Cube names materials after the face/model role (``acacia_log_side``,
    ``ice_all``), while its image node identifies the source texture.  These
    are deterministic suffix conventions, not substring/fuzzy matching.
    """
    aliases = [name]
    for suffix in ("_all", "_side", "_end", "_top", "_bottom", "_front", "_back",
                   "_up", "_down", "_north", "_south", "_east", "_west"):
        if name.endswith(suffix):
            stem = name[:-len(suffix)]
            aliases.append(stem)
            # Ice Cube's *_block_all convention can refer to old vanilla
            # texture names such as magma.png.  Try the literal stem first.
            if suffix == "_all" and stem.endswith("_block"):
                aliases.append(stem[:-len("_block")])
            break
    return aliases


def extract_material_texture_keys(mat: bpy.types.Material) -> tuple[str, list[str]]:
    """Return namespace and ordered exact resource-pack texture candidates."""
    if not mat:
        return "", []
    if mat.get("mtk:source_namespace") and mat.get("mtk:source_texture"):
        return str(mat["mtk:source_namespace"]), [str(mat["mtk:source_texture"])]

    name = _without_blender_suffix(mat.name.strip().lower())
    namespace = "minecraft"
    # Authoring materials can optionally use ``namespace:texture`` before
    # their first conversion.  A plain material name means minecraft.
    if ":" in name:
        namespace, name = name.split(":", 1)

    candidates = []

    # Prefer the image that the material actually uses.  This handles Ice
    # Cube's semantic material names without guessing from arbitrary text.
    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type != 'TEX_IMAGE' or not node.image:
                continue
            filepath = node.image.filepath or node.image.name
            image_name = Path(filepath).name or node.image.name
            image_name = _without_blender_suffix(image_name.lower())
            if image_name.endswith(".png"):
                image_name = image_name[:-4]
            # Ice Cube animation images conventionally end in _0000.
            if len(image_name) > 5 and image_name[-5] == "_" and image_name[-4:].isdigit():
                image_name = image_name[:-5]
            if image_name:
                candidates.append(image_name)

    candidates.extend(_ice_cube_name_aliases(name))
    return namespace, list(dict.fromkeys(candidates))


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
        selected_objects = set(target_objects)

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
                        # material datablock so Blender does not append .001
                        # and provenance names remain stable.
                        processed_materials[original_mat] = canonical_mat
                        for selected_obj in selected_objects:
                            for selected_slot in selected_obj.material_slots:
                                if selected_slot.material == original_mat:
                                    selected_slot.material = canonical_mat
                        replaced_count += 1
                        pipeline_context.report("INFO", f"Assigned existing material '{canonical_mat.name}' for '{original_name}'.")
                        continue
                    if canonical_mat == original_mat:
                        processed_materials[original_mat] = original_mat
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
                    success = rebuild_material(mat, tex_info, pack_textures=pack_textures)
                    if success:
                        name_replaced_material(mat, tex_info, pack)
                        replaced_count += 1
                        pipeline_context.report("INFO", f"Replaced material '{original_name}' with pack texture '{namespace}:{key}'")
                else:
                    attempted = ", ".join(f"{namespace}:{candidate}" for candidate in candidates) or "no usable material key"
                    pipeline_context.report("INFO", f"Kept material '{original_mat.name}' unchanged: no exact pack match ({attempted}).")

        if replaced_count == 0:
            return StepResult.success("No exact material matches found; selected objects were left unchanged.")

        return StepResult.success(f"Successfully replaced {replaced_count} materials.")

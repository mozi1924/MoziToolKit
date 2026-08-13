import json
from pathlib import Path
import bpy
from ..step import PipelineStep, StepResult
try:
    from ...utils.zip_resource_pack import ZipResourcePack, get_cache_dir
    from ...utils.material_builder import rebuild_material
    from ...utils.material_matching import extract_material_texture_keys
    from ...utils.generate_atlas import ATLAS_FORMAT_VERSION, AtlasGenerator
    from ...utils.atlas_builder import build_atlas_material
    from ...utils.atlas_layout import atlas_uv_from_local, face_index_from_normal, static_cell
except (ImportError, ValueError):
    from utils.zip_resource_pack import ZipResourcePack, get_cache_dir
    from utils.material_builder import rebuild_material
    from utils.material_matching import extract_material_texture_keys
    from utils.generate_atlas import ATLAS_FORMAT_VERSION, AtlasGenerator
    from utils.atlas_builder import build_atlas_material
    from utils.atlas_layout import atlas_uv_from_local, face_index_from_normal, static_cell


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
    """Pipeline step to parse Minecraft Java resource pack and reconstruct LabPBR or Atlas materials."""

    name = "replace_material"
    description = "Replace and reconstruct materials from Minecraft Java Resource Pack"

    def execute(self, pipeline_context) -> StepResult:
        zip_path = pipeline_context.get_param("zip_path")
        pack_textures = pipeline_context.get_param("pack_textures", True)
        use_cache = pipeline_context.get_param("use_cache", True)
        material_mode = pipeline_context.get_param("material_mode", "STANDALONE")

        if not zip_path or not Path(zip_path).exists():
            return StepResult.failed("Resource pack ZIP file not specified or found.")

        target_objects = pipeline_context.target_objects
        if not target_objects:
            return StepResult.failed("No objects selected for material replacement.")

        try:
            pack = ZipResourcePack(zip_path, use_cache=use_cache)
        except Exception as e:
            return StepResult.failed(f"Failed to load resource pack: {e}")

        if material_mode == "ATLAS":
            return self._execute_atlas_mode(pipeline_context, pack, target_objects, pack_textures)
        else:
            return self._execute_standalone_mode(pipeline_context, pack, target_objects, pack_textures)

    def _execute_atlas_mode(self, pipeline_context, pack: ZipResourcePack, target_objects, pack_textures: bool) -> StepResult:
        """Execute material replacement in Atlas Mode (single shared atlas material)."""
        cache_root = get_cache_dir()
        atlas_dir = cache_root / pack.pack_hash
        albedo_path = atlas_dir / "atlas_albedo.png"
        mapping_path = atlas_dir / "atlas_mapping.json"

        cache_is_current = False
        if albedo_path.exists() and mapping_path.exists():
            try:
                with open(mapping_path, "r", encoding="utf-8") as fp:
                    cache_is_current = (
                        json.load(fp).get("format_version") == ATLAS_FORMAT_VERSION
                    )
            except (OSError, json.JSONDecodeError):
                cache_is_current = False

        if not cache_is_current:
            pipeline_context.report("INFO", f"Generating Atlas texture for pack hash {pack.pack_hash[:12]}...")
            try:
                gen = AtlasGenerator(pack.extract_dir)
                gen.build(atlas_dir)
            except Exception as e:
                return StepResult.failed(f"Failed to generate Atlas texture: {e}")

        # Build or get single Atlas Material
        atlas_mat_name = f"mtk:atlas:{pack.pack_hash[:12]}"
        atlas_mat = build_atlas_material(atlas_dir, mat_name=atlas_mat_name, pack_textures=pack_textures)

        # Load mapping JSON
        with open(mapping_path, "r", encoding="utf-8") as fp:
            mapping_data = json.load(fp)

        # Construct fast material name lookup dictionary
        mat_id_map = {}
        for mat_entry in mapping_data.get("materials", []):
            mat_name = mat_entry["name"].lower()
            mat_id = mat_entry["material_id"]
            mat_id_map[mat_name] = mat_id
            # Map face texture stems as fallbacks
            for face_tex in mat_entry.get("faces", {}).values():
                if face_tex and face_tex.lower() not in mat_id_map:
                    mat_id_map[face_tex.lower()] = mat_id

        replaced_objects = 0
        atlas_width = float(mapping_data["atlas_width"])
        atlas_height = float(mapping_data["atlas_height"])
        tile_size = float(mapping_data["tile_size"])
        material_columns = int(mapping_data["static_material_columns"])

        for obj in target_objects:
            if obj.type != "MESH" or not obj.data or not obj.material_slots:
                continue

            mesh = obj.data

            # Material Preview / Solid texture mode does not evaluate shader
            # nodes.  Move the object's active UVs into the atlas as well as
            # assigning the face id used by the render-time decoder.
            uv_layer = mesh.uv_layers.active_render or mesh.uv_layers.active
            if uv_layer is None:
                pipeline_context.report(
                    "WARNING",
                    f"'{obj.name}' has no UV map; Atlas UVs could not be written."
                )

            # Fetch or create 'material_id' face attribute
            if "material_id" not in mesh.attributes:
                attr = mesh.attributes.new(name="material_id", type="FLOAT", domain="FACE")
            else:
                attr = mesh.attributes["material_id"]

            mat_ids = [0.0] * len(mesh.polygons)
            resolved_ids = [None] * len(mesh.polygons)
            poly_updated = False

            for poly_idx, poly in enumerate(mesh.polygons):
                if poly.material_index >= len(obj.material_slots):
                    continue
                orig_slot = obj.material_slots[poly.material_index]
                if not orig_slot.material:
                    continue

                namespace, candidates = extract_material_texture_keys(orig_slot.material)
                found_id = None
                for cand in candidates:
                    clean_cand = cand.lower().replace(".png", "")
                    if clean_cand in mat_id_map:
                        found_id = mat_id_map[clean_cand]
                        break

                if found_id is not None:
                    mat_ids[poly_idx] = float(found_id)
                    resolved_ids[poly_idx] = found_id
                    poly_updated = True

            if poly_updated:
                attr.data.foreach_set("value", mat_ids)
                if uv_layer is not None:
                    for poly_idx, material_id in enumerate(resolved_ids):
                        if material_id is None:
                            continue
                        polygon = mesh.polygons[poly_idx]
                        tile_column, tile_row = static_cell(
                            material_id,
                            face_index_from_normal(polygon.normal),
                            material_columns,
                        )
                        for loop_index in polygon.loop_indices:
                            uv = uv_layer.data[loop_index].uv
                            uv.x, uv.y = atlas_uv_from_local(
                                uv.x, uv.y,
                                tile_column=tile_column,
                                tile_row=tile_row,
                                tile_size=tile_size,
                                atlas_width=atlas_width,
                                atlas_height=atlas_height,
                            )

            # Assign single atlas material to all slots (or consolidate to slot 0)
            obj.material_slots[0].material = atlas_mat
            for slot_idx in range(1, len(obj.material_slots)):
                obj.material_slots[slot_idx].material = atlas_mat

            replaced_objects += 1

        return StepResult.success(f"Successfully processed {replaced_objects} object(s) in Atlas Mode.")

    def _execute_standalone_mode(self, pipeline_context, pack: ZipResourcePack, target_objects, pack_textures: bool) -> StepResult:
        """Execute material replacement in traditional Standalone Mode (individual materials)."""
        replaced_count = 0
        processed_materials = {}
        session_materials = {}

        def get_or_create_replacement_material(texture_info):
            texture_key = (texture_info["namespace"], texture_info["texture_name"])
            canonical_mat = find_existing_replacement(texture_info, pack)
            if not canonical_mat:
                canonical_mat = session_materials.get(texture_key)

            if canonical_mat:
                return canonical_mat, False

            mat_name = f"mtk:{texture_info['namespace']}:{texture_info['texture_name']}"
            mat = bpy.data.materials.new(name=mat_name)
            if not rebuild_material(mat, texture_info, pack_textures=pack_textures, pack_hash=pack.pack_hash):
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

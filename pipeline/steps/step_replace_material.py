import json
from pathlib import Path
import bpy
from ..step import PipelineStep, StepResult
try:
    from ...utils.zip_resource_pack import ZipResourcePack, get_cache_dir
    from ...utils.material_builder import rebuild_material
    from ...utils.material_matching import extract_material_texture_keys
    from ...utils.generate_atlas import ATLAS_FORMAT_VERSION, AtlasGenerator
    from ...utils.atlas_builder import build_atlas_chunk_materials
    from ...utils.atlas_layout import atlas_uv_from_local, atlas_uv_from_rect
except (ImportError, ValueError):
    from utils.zip_resource_pack import ZipResourcePack, get_cache_dir
    from utils.material_builder import rebuild_material
    from utils.material_matching import extract_material_texture_keys
    from utils.generate_atlas import ATLAS_FORMAT_VERSION, AtlasGenerator
    from utils.atlas_builder import build_atlas_chunk_materials
    from utils.atlas_layout import atlas_uv_from_local, atlas_uv_from_rect


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
        mapping_path = atlas_dir / "atlas_mapping.json"

        cache_is_current = False
        if mapping_path.exists():
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

        # Load mapping JSON
        with open(mapping_path, "r", encoding="utf-8") as fp:
            mapping_data = json.load(fp)

        texture_map = {
            name.lower(): location
            for name, location in mapping_data.get("textures", {}).items()
            if location is not None
        }
        chunks_by_id = {int(chunk["chunk_id"]): chunk for chunk in mapping_data.get("chunks", [])}

        # Loading all animation chunks up front is needlessly expensive.  A
        # mesh only needs the chunk(s) referenced by its current materials.
        required_chunk_ids = set()
        for obj in target_objects:
            if obj.type != "MESH":
                continue
            for slot in obj.material_slots:
                if not slot.material:
                    continue
                _namespace, candidates = extract_material_texture_keys(slot.material)
                for candidate in candidates:
                    location = texture_map.get(candidate.lower().replace(".png", ""))
                    if location is not None:
                        required_chunk_ids.add(int(location["chunk_id"]))

        atlas_materials = build_atlas_chunk_materials(
            atlas_dir,
            pack_hash=pack.pack_hash,
            pack_textures=pack_textures,
            chunk_ids=required_chunk_ids,
        )

        replaced_objects = 0
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

            def face_attribute(name):
                attribute = mesh.attributes.get(name)
                if attribute is None:
                    attribute = mesh.attributes.new(name=name, type="FLOAT", domain="FACE")
                return attribute

            chunk_attr = face_attribute("atlas_chunk_id")
            texture_attr = face_attribute("atlas_texture_id")
            chunk_ids = [-1.0] * len(mesh.polygons)
            texture_ids = [-1.0] * len(mesh.polygons)
            resolved_locations = [None] * len(mesh.polygons)
            poly_updated = False

            for poly_idx, poly in enumerate(mesh.polygons):
                if poly.material_index >= len(obj.material_slots):
                    continue
                orig_slot = obj.material_slots[poly.material_index]
                if not orig_slot.material:
                    continue

                namespace, candidates = extract_material_texture_keys(orig_slot.material)
                location = None
                for cand in candidates:
                    clean_cand = cand.lower().replace(".png", "")
                    if clean_cand in texture_map:
                        location = texture_map[clean_cand]
                        break

                if location is not None:
                    chunk_ids[poly_idx] = float(location["chunk_id"])
                    texture_ids[poly_idx] = float(location["texture_id"])
                    resolved_locations[poly_idx] = location
                    poly_updated = True

            if poly_updated:
                chunk_attr.data.foreach_set("value", chunk_ids)
                texture_attr.data.foreach_set("value", texture_ids)
                if uv_layer is not None:
                    for poly_idx, location in enumerate(resolved_locations):
                        if location is None:
                            continue
                        polygon = mesh.polygons[poly_idx]
                        chunk = chunks_by_id[int(location["chunk_id"])]
                        for loop_index in polygon.loop_indices:
                            uv = uv_layer.data[loop_index].uv
                            if location["kind"] == "animation":
                                uv.x, uv.y = atlas_uv_from_rect(
                                    uv.x, uv.y,
                                    pixel_x=float(location["pixel_x"]), pixel_y=float(location["pixel_y"]),
                                    rect_width=float(location["frame_width"]), rect_height=float(location["frame_height"]),
                                    atlas_width=float(chunk["width"]), atlas_height=float(chunk["height"]),
                                )
                            else:
                                uv.x, uv.y = atlas_uv_from_local(
                                    uv.x, uv.y,
                                    tile_column=int(location["tile_column"]),
                                    tile_row=int(location["tile_row"]),
                                    tile_size=float(chunk["tile_size"]),
                                    atlas_width=float(chunk["width"]),
                                    atlas_height=float(chunk["height"]),
                                )
                used_chunk_ids = sorted({int(loc["chunk_id"]) for loc in resolved_locations if loc})
                mesh.materials.clear()
                for chunk_id in used_chunk_ids:
                    mesh.materials.append(atlas_materials[chunk_id])
                chunk_slots = {chunk_id: index for index, chunk_id in enumerate(used_chunk_ids)}
                for poly_idx, location in enumerate(resolved_locations):
                    if location is not None:
                        mesh.polygons[poly_idx].material_index = chunk_slots[int(location["chunk_id"])]
                    elif used_chunk_ids:
                        # Preserve a valid material assignment for unmatched
                        # faces; their UVs remain unchanged for diagnosis.
                        mesh.polygons[poly_idx].material_index = 0

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

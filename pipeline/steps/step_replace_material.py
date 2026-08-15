import json
from pathlib import Path
import bpy
from ..step import PipelineStep, StepResult
try:
    from ...utils.materials import (
        ZipResourcePack,
        get_cache_dir,
        rebuild_material,
        extract_material_texture_keys,
        detect_material_mode,
        get_atlas_mapping_from_material,
        extract_face_texture_info,
        ATLAS_FORMAT_VERSION,
        AtlasGenerator,
        build_atlas_chunk_materials,
        atlas_uv_from_local,
        atlas_uv_from_rect,
        local_uv_from_atlas,
        local_uv_from_rect,
    )
    from ...utils.system import has_pillow
except (ImportError, ValueError):
    from utils.materials import (
        ZipResourcePack,
        get_cache_dir,
        rebuild_material,
        extract_material_texture_keys,
        detect_material_mode,
        get_atlas_mapping_from_material,
        extract_face_texture_info,
        ATLAS_FORMAT_VERSION,
        AtlasGenerator,
        build_atlas_chunk_materials,
        atlas_uv_from_local,
        atlas_uv_from_rect,
        local_uv_from_atlas,
        local_uv_from_rect,
    )
    from utils.system import has_pillow


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
        """Execute material replacement in Atlas Mode supporting Standalone->Atlas and Atlas->Atlas UV conversion."""
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
            if not has_pillow():
                return StepResult.failed("Atlas Mode requires 'Pillow' dependency. Please open Preferences > Add-ons > MoziToolKit > Dependencies to install it.")
            pipeline_context.report("INFO", f"Generating Atlas texture for pack hash {pack.pack_hash[:12]}...")
            try:
                gen = AtlasGenerator(pack.extract_dir)
                gen.build(atlas_dir)
            except Exception as e:
                return StepResult.failed(f"Failed to generate Atlas texture: {e}")

        # Load target mapping JSON
        with open(mapping_path, "r", encoding="utf-8") as fp:
            mapping_data = json.load(fp)

        texture_map = {
            name.lower(): location
            for name, location in mapping_data.get("textures", {}).items()
            if location is not None
        }
        chunks_by_id = {int(chunk["chunk_id"]): chunk for chunk in mapping_data.get("chunks", [])}

        # Collect required chunks from target objects (handling both Standalone and existing Atlas meshes)
        required_chunk_ids = set()
        for obj in target_objects:
            if obj.type != "MESH" or not obj.data or not obj.material_slots:
                continue
            mesh = obj.data
            for poly_idx, poly in enumerate(mesh.polygons):
                if poly.material_index >= len(obj.material_slots):
                    continue
                slot_mat = obj.material_slots[poly.material_index].material
                if not slot_mat:
                    continue
                _ns, candidates, _old_loc = extract_face_texture_info(mesh, poly_idx, slot_mat)
                for cand in candidates:
                    clean_key = cand.lower().replace(".png", "")
                    loc = texture_map.get(clean_key)
                    if loc is not None:
                        required_chunk_ids.add(int(loc["chunk_id"]))
                        break

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
            anim_frames_attr = face_attribute("mtk_anim_total_frames")
            anim_frametime_attr = face_attribute("mtk_anim_frametime")
            anim_interp_attr = face_attribute("mtk_anim_interpolate")
            anim_width_attr = face_attribute("mtk_anim_frame_width")
            anim_height_attr = face_attribute("mtk_anim_frame_height")

            chunk_ids = [-1.0] * len(mesh.polygons)
            texture_ids = [-1.0] * len(mesh.polygons)
            anim_frames = [1.0] * len(mesh.polygons)
            anim_frametimes = [1.0] * len(mesh.polygons)
            anim_interps = [0.0] * len(mesh.polygons)
            anim_widths = [16.0] * len(mesh.polygons)
            anim_heights = [16.0] * len(mesh.polygons)
            resolved_locations = [None] * len(mesh.polygons)
            poly_updated = False

            # Animation metadata is deliberately mesh FACE-domain data.  The
            # shader reads these attributes directly, so object properties
            # would only duplicate (and, for mixed animations, misrepresent)
            # the data.  Remove properties written by earlier versions while
            # the object is being converted to Atlas mode.
            for prop in (
                "mtk_anim_total_frames", "mtk_anim_frametime",
                "mtk_anim_interpolate", "mtk_anim_frame_width",
                "mtk_anim_frame_height",
            ):
                if prop in obj:
                    del obj[prop]

            # Cache old atlas mappings per slot material to avoid redundant JSON parsing
            old_mappings = {}
            for slot in obj.material_slots:
                if slot.material and slot.material not in old_mappings:
                    old_mappings[slot.material] = get_atlas_mapping_from_material(slot.material)

            for poly_idx, poly in enumerate(mesh.polygons):
                if poly.material_index >= len(obj.material_slots):
                    continue
                orig_slot = obj.material_slots[poly.material_index]
                if not orig_slot.material:
                    continue

                old_mapping = old_mappings.get(orig_slot.material)
                orig_mode = detect_material_mode(orig_slot.material)
                _namespace, candidates, old_loc = extract_face_texture_info(
                    mesh, poly_idx, orig_slot.material, old_mapping
                )

                new_location = None
                for candidate in candidates:
                    clean_cand = candidate.lower().replace(".png", "")
                    if clean_cand in texture_map:
                        new_location = texture_map[clean_cand]
                        break

                if new_location is not None:
                    chunk_ids[poly_idx] = float(new_location["chunk_id"])
                    texture_ids[poly_idx] = float(new_location["texture_id"])
                    if new_location.get("kind") == "animation":
                        f_count = float(new_location.get("frame_count", 1))
                        f_time = float(new_location.get("frametime", 1))
                        f_interp = 1.0 if new_location.get("interpolate", False) else 0.0
                        f_width = float(new_location.get("frame_width", 16))
                        f_height = float(new_location.get("frame_height", 16))
                        anim_frames[poly_idx] = f_count
                        anim_frametimes[poly_idx] = f_time
                        anim_interps[poly_idx] = f_interp
                        anim_widths[poly_idx] = f_width
                        anim_heights[poly_idx] = f_height
                    else:
                        anim_frames[poly_idx] = 1.0
                        anim_frametimes[poly_idx] = 1.0
                        anim_interps[poly_idx] = 0.0
                        anim_widths[poly_idx] = float(new_location.get("frame_width", 16))
                        anim_heights[poly_idx] = float(new_location.get("frame_height", 16))

                    resolved_locations[poly_idx] = (new_location, old_loc, orig_mode, old_mapping)
                    poly_updated = True

            if poly_updated:
                chunk_attr.data.foreach_set("value", chunk_ids)
                texture_attr.data.foreach_set("value", texture_ids)
                anim_frames_attr.data.foreach_set("value", anim_frames)
                anim_frametime_attr.data.foreach_set("value", anim_frametimes)
                anim_interp_attr.data.foreach_set("value", anim_interps)
                anim_width_attr.data.foreach_set("value", anim_widths)
                anim_height_attr.data.foreach_set("value", anim_heights)

                if uv_layer is not None:
                    for poly_idx, resolved in enumerate(resolved_locations):
                        if resolved is None:
                            continue
                        new_location, old_loc, orig_mode, old_mapping = resolved
                        polygon = mesh.polygons[poly_idx]
                        target_chunk = chunks_by_id[int(new_location["chunk_id"])]

                        # If source was already Atlas, retrieve old chunk definition for UV normalization
                        old_chunk = None
                        if old_loc and old_mapping:
                            old_chunks_map = {int(c["chunk_id"]): c for c in old_mapping.get("chunks", [])}
                            old_chunk = old_chunks_map.get(int(old_loc["chunk_id"]))

                        for loop_index in polygon.loop_indices:
                            uv = uv_layer.data[loop_index].uv
                            u_val, v_val = uv.x, uv.y

                            # Step 1: Invert from old Atlas UV to Local [0, 1] if source was Atlas
                            if orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_chunk:
                                if old_loc.get("kind") == "animation":
                                    u_val, v_val = local_uv_from_rect(
                                        u_val, v_val,
                                        pixel_x=float(old_loc["pixel_x"]), pixel_y=float(old_loc["pixel_y"]),
                                        rect_width=float(old_loc["frame_width"]), rect_height=float(old_loc["frame_height"]),
                                        atlas_width=float(old_chunk["width"]), atlas_height=float(old_chunk["height"]),
                                    )
                                else:
                                    u_val, v_val = local_uv_from_atlas(
                                        u_val, v_val,
                                        tile_column=int(old_loc["tile_column"]),
                                        tile_row=int(old_loc["tile_row"]),
                                        tile_size=float(old_chunk["tile_size"]),
                                        atlas_width=float(old_chunk["width"]),
                                        atlas_height=float(old_chunk["height"]),
                                    )

                            # Step 2: Transform from Local [0, 1] to target Atlas UV
                            if new_location["kind"] == "animation":
                                uv.x, uv.y = atlas_uv_from_rect(
                                    u_val, v_val,
                                    pixel_x=float(new_location["pixel_x"]), pixel_y=float(new_location["pixel_y"]),
                                    rect_width=float(new_location["frame_width"]), rect_height=float(new_location["frame_height"]),
                                    atlas_width=float(target_chunk["width"]), atlas_height=float(target_chunk["height"]),
                                )
                            else:
                                uv.x, uv.y = atlas_uv_from_local(
                                    u_val, v_val,
                                    tile_column=int(new_location["tile_column"]),
                                    tile_row=int(new_location["tile_row"]),
                                    tile_size=float(target_chunk["tile_size"]),
                                    atlas_width=float(target_chunk["width"]),
                                    atlas_height=float(target_chunk["height"]),
                                )

                used_chunk_ids = sorted({int(res[0]["chunk_id"]) for res in resolved_locations if res})
                mesh.materials.clear()
                for chunk_id in used_chunk_ids:
                    mesh.materials.append(atlas_materials[chunk_id])
                chunk_slots = {chunk_id: index for index, chunk_id in enumerate(used_chunk_ids)}
                for poly_idx, resolved in enumerate(resolved_locations):
                    if resolved is not None:
                        mesh.polygons[poly_idx].material_index = chunk_slots[int(resolved[0]["chunk_id"])]
                    elif used_chunk_ids:
                        mesh.polygons[poly_idx].material_index = 0

            replaced_objects += 1

        return StepResult.success(f"Successfully processed {replaced_objects} object(s) in Atlas Mode.")

    def _execute_standalone_mode(self, pipeline_context, pack: ZipResourcePack, target_objects, pack_textures: bool) -> StepResult:
        """Execute material replacement in Standalone Mode supporting Atlas->Standalone UV inversion and slot mapping."""
        replaced_count = 0
        assigned_count = 0
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
            if obj.type != 'MESH' or not obj.data or not obj.material_slots:
                continue

            mesh = obj.data
            uv_layer = mesh.uv_layers.active_render or mesh.uv_layers.active

            # Cache old atlas mappings
            old_mappings = {}
            for slot in obj.material_slots:
                if slot.material and slot.material not in old_mappings:
                    old_mappings[slot.material] = get_atlas_mapping_from_material(slot.material)

            has_atlas_source = any(detect_material_mode(slot.material) in ("ATLAS_CHUNK", "ATLAS_UNIFIED")
                                   for slot in obj.material_slots if slot.material)

            face_materials = [None] * len(mesh.polygons)
            poly_modified = False

            for poly_idx, poly in enumerate(mesh.polygons):
                if poly.material_index >= len(obj.material_slots):
                    continue
                orig_slot = obj.material_slots[poly.material_index]
                if not orig_slot.material:
                    continue

                old_mapping = old_mappings.get(orig_slot.material)
                orig_mode = detect_material_mode(orig_slot.material)
                namespace, candidates, old_loc = extract_face_texture_info(
                    mesh, poly_idx, orig_slot.material, old_mapping
                )

                tex_info = None
                for cand in candidates:
                    info = pack.get_texture_info(cand, namespace)
                    if info and info.get("albedo"):
                        tex_info = info
                        break

                if tex_info:
                    mat, is_new = get_or_create_replacement_material(tex_info)
                    if mat:
                        face_materials[poly_idx] = mat
                        poly_modified = True
                        assigned_count += 1
                        if is_new:
                            replaced_count += 1
                            pipeline_context.report("INFO", f"Built standalone material '{mat.name}' for '{tex_info['texture_name']}'")

                    # Invert UV from Atlas to Local [0, 1] if polygon was in Atlas space
                    if orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_mapping and uv_layer:
                        old_chunks_map = {int(c["chunk_id"]): c for c in old_mapping.get("chunks", [])}
                        old_chunk = old_chunks_map.get(int(old_loc["chunk_id"]))
                        if old_chunk:
                            for loop_index in poly.loop_indices:
                                uv = uv_layer.data[loop_index].uv
                                if old_loc.get("kind") == "animation":
                                    uv.x, uv.y = local_uv_from_rect(
                                        uv.x, uv.y,
                                        pixel_x=float(old_loc["pixel_x"]), pixel_y=float(old_loc["pixel_y"]),
                                        rect_width=float(old_loc["frame_width"]), rect_height=float(old_loc["frame_height"]),
                                        atlas_width=float(old_chunk["width"]), atlas_height=float(old_chunk["height"]),
                                    )
                                else:
                                    uv.x, uv.y = local_uv_from_atlas(
                                        uv.x, uv.y,
                                        tile_column=int(old_loc["tile_column"]),
                                        tile_row=int(old_loc["tile_row"]),
                                        tile_size=float(old_chunk["tile_size"]),
                                        atlas_width=float(old_chunk["width"]),
                                        atlas_height=float(old_chunk["height"]),
                                    )

            if poly_modified:
                # Reassign material slots and polygon indices
                unique_mats = []
                for m in face_materials:
                    if m is not None and m not in unique_mats:
                        unique_mats.append(m)

                if unique_mats:
                    mesh.materials.clear()
                    for m in unique_mats:
                        mesh.materials.append(m)
                    mat_indices = {m: idx for idx, m in enumerate(unique_mats)}
                    for poly_idx, m in enumerate(face_materials):
                        if m is not None:
                            mesh.polygons[poly_idx].material_index = mat_indices[m]

                # If the mesh previously had atlas attributes, clean them up
                if has_atlas_source:
                    for attr_name in (
                        "atlas_chunk_id", "atlas_texture_id",
                        "mtk_anim_total_frames", "mtk_anim_frametime",
                        "mtk_anim_interpolate", "mtk_anim_frame_width",
                        "mtk_anim_frame_height",
                    ):
                        attr = mesh.attributes.get(attr_name)
                        if attr:
                            mesh.attributes.remove(attr)
                    for prop in (
                        "mtk_anim_total_frames", "mtk_anim_frametime",
                        "mtk_anim_interpolate", "mtk_anim_frame_width",
                        "mtk_anim_frame_height",
                    ):
                        if prop in obj:
                            del obj[prop]

        if assigned_count == 0:
            return StepResult.success("No exact material matches found; selected objects were left unchanged.")

        return StepResult.success(f"Successfully processed Standalone replacement ({assigned_count} slot(s) assigned, {replaced_count} new material(s) created).")

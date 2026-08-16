"""
Material replacement and reconstruction pipeline step.
Supports Standalone and Texture Atlas generation modes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Union, Optional
import bpy

from ..progress import ProgressUpdate
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
        canonical_texture_key,
        split_texture_key,
        material_source_origin,
        write_face_source_provenance,
        get_face_source_origin,
        get_face_source_texture_key,
        is_ice_cube_internal_face_material,
        ATLAS_FORMAT_VERSION,
        AtlasGenerator,
        build_atlas_chunk_materials,
        remap_uv_coordinate,
        remap_uv_to_local,
        remap_local_to_target_uv,
        get_material_animation_info,
        get_texture_info_animation_info,
        ATTR_ATLAS_CHUNK_ID,
        ATTR_ATLAS_TEXTURE_ID,
        ATTR_FACE_MATERIAL_ID,
        ATTR_UV_ROTATION,
        ATTR_UV_TILING_SCALE,
        ATTR_UV_TILING_LOCATION,
    )
    from ...utils.system import has_pillow
    from ...utils.mesh import straighten_face_uv, normalize_face_uv_for_atlas_tiling, restore_atlas_tiling_uv
except (ImportError, ValueError):
    from utils.materials import (
        ZipResourcePack,
        get_cache_dir,
        rebuild_material,
        extract_material_texture_keys,
        detect_material_mode,
        get_atlas_mapping_from_material,
        extract_face_texture_info,
        canonical_texture_key,
        split_texture_key,
        material_source_origin,
        write_face_source_provenance,
        get_face_source_origin,
        get_face_source_texture_key,
        is_ice_cube_internal_face_material,
        ATLAS_FORMAT_VERSION,
        AtlasGenerator,
        build_atlas_chunk_materials,
        remap_uv_coordinate,
        remap_uv_to_local,
        remap_local_to_target_uv,
        get_material_animation_info,
        get_texture_info_animation_info,
        ATTR_ATLAS_CHUNK_ID,
        ATTR_ATLAS_TEXTURE_ID,
        ATTR_FACE_MATERIAL_ID,
        ATTR_UV_ROTATION,
        ATTR_UV_TILING_SCALE,
        ATTR_UV_TILING_LOCATION,
    )
    from utils.system import has_pillow
    from utils.mesh import straighten_face_uv, normalize_face_uv_for_atlas_tiling, restore_atlas_tiling_uv


ANIM_AND_ATLAS_ATTR_NAMES = (
    ATTR_ATLAS_CHUNK_ID,
    ATTR_ATLAS_TEXTURE_ID,
    ATTR_FACE_MATERIAL_ID,
    ATTR_UV_ROTATION,
    ATTR_UV_TILING_SCALE,
    ATTR_UV_TILING_LOCATION,
    "atlas_chunk_id",
    "atlas_texture_id",
    "material_id",
    "mtk_uv_rotation",
    "mtk_anim_total_frames",
    "mtk_anim_frametime",
    "mtk_anim_interpolate",
    "mtk_anim_frame_width",
    "mtk_anim_frame_height",
)


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
        if (
            material.get("mtk:source_namespace") == namespace
            and material.get("mtk:source_texture") == texture_name
            and material.get("mtk:pack_hash") == pack.pack_hash
        ):
            return material
    return None


def apply_mesh_face_materials_and_provenance(
    mesh: bpy.types.Mesh,
    face_materials: list[bpy.types.Material | None],
    source_keys: list[str],
    source_origins: list[str],
) -> None:
    """Consolidate material slots and write back durable face-level provenance."""
    unique_materials: list[bpy.types.Material] = []
    for mat in face_materials:
        if mat is not None and mat not in unique_materials:
            unique_materials.append(mat)

    if unique_materials:
        mesh.materials.clear()
        for mat in unique_materials:
            mesh.materials.append(mat)
        mat_slots = {m: idx for idx, m in enumerate(unique_materials)}
        for poly_idx, mat in enumerate(face_materials):
            if mat is not None:
                mesh.polygons[poly_idx].material_index = mat_slots[mat]

    write_face_source_provenance(mesh, source_keys, source_origins)


def remap_polygon_loop_uvs(
    polygon: bpy.types.MeshPolygon,
    uv_layer: bpy.types.MeshUVLoopLayer,
    orig_mode: str,
    old_loc: Optional[dict] = None,
    old_chunk: Optional[dict] = None,
    old_anim_info: Optional[dict] = None,
    target_location: Optional[dict] = None,
    target_chunk: Optional[dict] = None,
    target_anim_info: Optional[dict] = None,
) -> None:
    """Transform all loop UVs for a single polygon from source space to target space."""
    for loop_index in polygon.loop_indices:
        uv = uv_layer.data[loop_index].uv
        uv.x, uv.y = remap_uv_coordinate(
            uv.x, uv.y,
            orig_mode=orig_mode,
            old_loc=old_loc,
            old_chunk=old_chunk,
            old_anim_info=old_anim_info,
            target_location=target_location,
            target_chunk=target_chunk,
            target_anim_info=target_anim_info,
        )


class StepReplaceMaterial(PipelineStep):
    """
    Modular PipelineStep for replacing and reconstructing materials from a Minecraft Java Resource Pack.
    Supports both Standalone and Atlas material generation modes.
    """

    name = "replace_material"
    description = "Replace and reconstruct materials from Minecraft Java Resource Pack"

    def execute_iter(self, pipeline_context) -> Iterator[Union[ProgressUpdate, StepResult]]:
        zip_path = pipeline_context.get_param("zip_path")
        pack_textures = pipeline_context.get_param("pack_textures", True)
        use_cache = pipeline_context.get_param("use_cache", True)
        material_mode = pipeline_context.get_param("material_mode", "STANDALONE")

        if not zip_path or not Path(zip_path).exists():
            yield StepResult.failed("Resource pack ZIP file not specified or found.")
            return

        target_objects = pipeline_context.target_objects
        if not target_objects:
            yield StepResult.failed("No objects selected for material replacement.")
            return

        yield ProgressUpdate(0.05, 1.0, "Loading Minecraft resource pack...")

        if pipeline_context.is_cancelled:
            yield StepResult.cancelled("Material replacement cancelled by user.")
            return

        try:
            pack = ZipResourcePack(zip_path, use_cache=use_cache)
        except Exception as e:
            yield StepResult.failed(f"Failed to load resource pack: {e}")
            return

        valid_objects = [o for o in target_objects if o and o.type == "MESH" and o.data and o.material_slots]
        if not valid_objects:
            yield StepResult.failed("No valid mesh objects with material slots found.")
            return

        if material_mode == "ATLAS":
            yield from self._execute_atlas_mode_iter(pipeline_context, pack, valid_objects, pack_textures)
        else:
            yield from self._execute_standalone_mode_iter(pipeline_context, pack, valid_objects, pack_textures)

    def _execute_atlas_mode_iter(
        self, pipeline_context, pack: ZipResourcePack, valid_objects: list, pack_textures: bool
    ) -> Iterator[Union[ProgressUpdate, StepResult]]:
        """Iteratively execute material replacement in Atlas Mode with fine-grained progress."""
        cache_root = get_cache_dir()
        atlas_dir = cache_root / pack.pack_hash
        mapping_path = atlas_dir / "atlas_mapping.json"

        yield ProgressUpdate(0.10, 1.0, "Checking Atlas texture cache...")

        if pipeline_context.is_cancelled:
            yield StepResult.cancelled("Material replacement cancelled by user.")
            return

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
                yield StepResult.failed(
                    "Atlas Mode requires 'Pillow' (PIL) module. Please ensure Pillow or extension wheels are installed."
                )
                return
            pipeline_context.report("INFO", f"Generating Atlas texture for pack hash {pack.pack_hash[:12]}...")
            try:
                gen = AtlasGenerator(pack.extract_dir)
                for frac, msg, _res in gen.build_iter(atlas_dir):
                    if pipeline_context.is_cancelled:
                        yield StepResult.cancelled("Material replacement cancelled by user.")
                        return
                    # Map Atlas build progress (0.0 - 1.0) into pipeline progress range (0.15 - 0.35)
                    atlas_pct = 0.15 + 0.20 * frac
                    yield ProgressUpdate(atlas_pct, 1.0, f"Atlas: {msg}")
            except Exception as e:
                yield StepResult.failed(f"Failed to generate Atlas texture: {e}")
                return

        yield ProgressUpdate(0.35, 1.0, "Reading Atlas mapping and required chunks...")

        with open(mapping_path, "r", encoding="utf-8") as fp:
            mapping_data = json.load(fp)

        texture_map = {}
        for name, location in mapping_data.get("textures", {}).items():
            if location is None:
                continue
            namespace, texture_name = split_texture_key(location.get("texture_key", name))
            texture_map[canonical_texture_key(namespace, texture_name)] = location
            legacy_namespace, legacy_texture = split_texture_key(name)
            texture_map.setdefault(canonical_texture_key(legacy_namespace, legacy_texture), location)

        chunks_by_id = {int(chunk["chunk_id"]): chunk for chunk in mapping_data.get("chunks", [])}

        # Collect required chunks
        required_chunk_ids = set()
        for obj in valid_objects:
            mesh = obj.data
            for poly_idx, poly in enumerate(mesh.polygons):
                if poly.material_index >= len(obj.material_slots):
                    continue
                slot_mat = obj.material_slots[poly.material_index].material
                if not slot_mat:
                    continue
                namespace, candidates, _old_loc = extract_face_texture_info(mesh, poly_idx, slot_mat)
                for cand in candidates:
                    loc = texture_map.get(canonical_texture_key(namespace, cand))
                    if loc is not None:
                        required_chunk_ids.add(int(loc["chunk_id"]))
                        break

        yield ProgressUpdate(0.45, 1.0, f"Building {len(required_chunk_ids)} Atlas chunk material(s)...")

        if pipeline_context.is_cancelled:
            yield StepResult.cancelled("Material replacement cancelled by user.")
            return

        atlas_materials = build_atlas_chunk_materials(
            atlas_dir,
            pack_hash=pack.pack_hash,
            pack_textures=pack_textures,
            chunk_ids=required_chunk_ids,
        )

        session_materials = {}

        def get_or_create_replacement_material(texture_info):
            texture_key = (texture_info["namespace"], texture_info["texture_name"])
            canonical_mat = find_existing_replacement(texture_info, pack) or session_materials.get(texture_key)
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

        replaced_objects = 0
        total_objs = len(valid_objects)

        for obj_idx, obj in enumerate(valid_objects):
            if pipeline_context.is_cancelled:
                yield StepResult.cancelled("Material replacement cancelled by user.")
                return

            obj_progress = 0.50 + 0.45 * (obj_idx / max(1, total_objs))
            yield ProgressUpdate(obj_progress, 1.0, f"Remapping Atlas UVs: {obj.name} ({obj_idx + 1}/{total_objs})")

            mesh = obj.data
            uv_layer = mesh.uv_layers.active_render or mesh.uv_layers.active

            def face_attribute(name):
                attribute = mesh.attributes.get(name)
                if attribute and (
                    attribute.domain != "FACE" or attribute.data_type != "FLOAT" or len(attribute.data) != len(mesh.polygons)
                ):
                    mesh.attributes.remove(attribute)
                    attribute = None
                return attribute or mesh.attributes.new(name=name, type="FLOAT", domain="FACE")

            def vector_face_attribute(name):
                attribute = mesh.attributes.get(name)
                if attribute and (
                    attribute.domain != "FACE" or attribute.data_type != "FLOAT_VECTOR" or len(attribute.data) != len(mesh.polygons)
                ):
                    mesh.attributes.remove(attribute)
                    attribute = None
                return attribute or mesh.attributes.new(name=name, type="FLOAT_VECTOR", domain="FACE")

            chunk_ids = [-1.0] * len(mesh.polygons)
            texture_ids = [-1.0] * len(mesh.polygons)
            uv_rotations = [0.0] * len(mesh.polygons)
            uv_tiling_scales = [(1.0, 1.0, 1.0)] * len(mesh.polygons)
            uv_tiling_locations = [(0.0, 0.0, 0.0)] * len(mesh.polygons)
            existing_rot_attr = mesh.attributes.get(ATTR_UV_ROTATION)
            if existing_rot_attr and len(existing_rot_attr.data) == len(mesh.polygons):
                uv_rotations = [float(item.value) for item in existing_rot_attr.data]

            anim_frames = [1.0] * len(mesh.polygons)
            anim_frametimes = [1.0] * len(mesh.polygons)
            anim_interps = [0.0] * len(mesh.polygons)
            anim_widths = [16.0] * len(mesh.polygons)
            anim_heights = [16.0] * len(mesh.polygons)
            resolved_locations = [None] * len(mesh.polygons)
            resolved_standalone = [None] * len(mesh.polygons)
            source_keys = [get_face_source_texture_key(mesh, idx) for idx in range(len(mesh.polygons))]
            source_origins = [get_face_source_origin(mesh, idx) for idx in range(len(mesh.polygons))]
            unresolved_faces = []
            skipped_faces = []
            face_materials = [
                obj.material_slots[poly.material_index].material
                if poly.material_index < len(obj.material_slots) else None
                for poly in mesh.polygons
            ]
            poly_updated = False

            old_mappings = {}
            for slot in obj.material_slots:
                if slot.material and slot.material not in old_mappings:
                    old_mappings[slot.material] = get_atlas_mapping_from_material(slot.material)

            for poly_idx, poly in enumerate(mesh.polygons):
                if poly.material_index >= len(obj.material_slots):
                    unresolved_faces.append(poly_idx)
                    continue
                orig_slot = obj.material_slots[poly.material_index]
                if not orig_slot.material:
                    unresolved_faces.append(poly_idx)
                    continue
                if is_ice_cube_internal_face_material(orig_slot.material):
                    skipped_faces.append(poly_idx)
                    continue

                old_mapping = old_mappings.get(orig_slot.material)
                orig_mode = detect_material_mode(orig_slot.material)
                namespace, candidates, old_loc = extract_face_texture_info(
                    mesh, poly_idx, orig_slot.material, old_mapping
                )

                new_location = None
                for candidate in candidates:
                    new_location = texture_map.get(canonical_texture_key(namespace, candidate))
                    if new_location is not None:
                        break

                if new_location is not None:
                    chunk_ids[poly_idx] = float(new_location["chunk_id"])
                    texture_ids[poly_idx] = float(new_location["texture_id"])
                    if new_location.get("kind") == "animation":
                        anim_frames[poly_idx] = float(new_location.get("frame_count", 1))
                        anim_frametimes[poly_idx] = float(new_location.get("frametime", 1))
                        anim_interps[poly_idx] = 1.0 if new_location.get("interpolate", False) else 0.0
                        anim_widths[poly_idx] = float(new_location.get("frame_width", 16))
                        anim_heights[poly_idx] = float(new_location.get("frame_height", 16))
                    else:
                        anim_frames[poly_idx] = 1.0
                        anim_frametimes[poly_idx] = 1.0
                        anim_interps[poly_idx] = 0.0
                        anim_widths[poly_idx] = float(new_location.get("frame_width", 16))
                        anim_heights[poly_idx] = float(new_location.get("frame_height", 16))

                    resolved_locations[poly_idx] = (new_location, old_loc, orig_mode, old_mapping)
                    target_namespace, target_texture = split_texture_key(
                        new_location.get("texture_key", candidates[0])
                    )
                    source_keys[poly_idx] = canonical_texture_key(target_namespace, target_texture)
                    source_origins[poly_idx] = (
                        get_face_source_origin(mesh, poly_idx) or material_source_origin(orig_slot.material)
                    )
                    poly_updated = True
                else:
                    # Non-atlas texture fallback
                    fallback_tex_info = None
                    for cand in candidates:
                        info = pack.get_texture_info(cand, namespace)
                        if info and info.get("albedo"):
                            fallback_tex_info = info
                            break

                    if fallback_tex_info:
                        mat, _is_new = get_or_create_replacement_material(fallback_tex_info)
                        if mat:
                            resolved_standalone[poly_idx] = (mat, old_loc, orig_mode, old_mapping)
                            source_keys[poly_idx] = canonical_texture_key(
                                fallback_tex_info["namespace"],
                                fallback_tex_info.get("texture_key", fallback_tex_info["texture_name"]),
                            )
                            source_origins[poly_idx] = (
                                get_face_source_origin(mesh, poly_idx) or material_source_origin(orig_slot.material)
                            )
                            poly_updated = True
                            continue

                    unresolved_faces.append(poly_idx)

            if skipped_faces:
                pipeline_context.report(
                    "INFO",
                    f"'{obj.name}': retained {len(skipped_faces)} Ice Cube internal face(s)."
                )

            if poly_updated:
                if uv_layer is not None:
                    # 1. Straighten any rotated local UVs (e.g. jmc2obj flowing liquid) and remap atlas faces to atlas UVs
                    for poly_idx, resolved in enumerate(resolved_locations):
                        if resolved is None:
                            continue
                        new_location, old_loc, orig_mode, old_mapping = resolved
                        polygon = mesh.polygons[poly_idx]
                        target_chunk = chunks_by_id[int(new_location["chunk_id"])]

                        old_chunk = None
                        if old_loc and old_mapping:
                            old_chunks_map = {int(c["chunk_id"]): c for c in old_mapping.get("chunks", [])}
                            old_chunk = old_chunks_map.get(int(old_loc["chunk_id"]))

                        old_anim_info = None
                        if not (orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_chunk):
                            orig_mat = (
                                obj.material_slots[polygon.material_index].material
                                if polygon.material_index < len(obj.material_slots) else None
                            )
                            old_anim_info = get_material_animation_info(orig_mat)

                        # Work in source-local UV space first. This makes both
                        # re-atlased meshes and direct jmc2obj imports follow
                        # exactly the same atlas-safe path.
                        for loop_index in polygon.loop_indices:
                            uv = uv_layer.data[loop_index].uv
                            uv.x, uv.y = remap_uv_to_local(
                                uv.x, uv.y, orig_mode, old_loc, old_chunk, old_anim_info
                            )

                        # Preserve non-orthogonal liquid UVs through the
                        # existing rotation attribute, then store any merged
                        # face span as shader tiling data instead of splitting.
                        if not (orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc):
                            rot_angle, was_straightened = straighten_face_uv(polygon, uv_layer)
                            if was_straightened:
                                uv_rotations[poly_idx] = float(rot_angle)

                        scale, location = normalize_face_uv_for_atlas_tiling(polygon, uv_layer)
                        uv_tiling_scales[poly_idx] = scale
                        uv_tiling_locations[poly_idx] = location

                        remap_polygon_loop_uvs(
                            polygon=polygon,
                            uv_layer=uv_layer,
                            orig_mode="STANDALONE",
                            target_location=new_location,
                            target_chunk=target_chunk,
                        )

                for attr_name, data in (
                    (ATTR_ATLAS_CHUNK_ID, chunk_ids),
                    (ATTR_ATLAS_TEXTURE_ID, texture_ids),
                    (ATTR_UV_ROTATION, uv_rotations),
                    ("mtk_anim_total_frames", anim_frames),
                    ("mtk_anim_frametime", anim_frametimes),
                    ("mtk_anim_interpolate", anim_interps),
                    ("mtk_anim_frame_width", anim_widths),
                    ("mtk_anim_frame_height", anim_heights),
                ):
                    face_attribute(attr_name).data.foreach_set("value", data)

                for attr_name, data in (
                    (ATTR_UV_TILING_SCALE, uv_tiling_scales),
                    (ATTR_UV_TILING_LOCATION, uv_tiling_locations),
                ):
                    vector_face_attribute(attr_name).data.foreach_set("vector", [component for value in data for component in value])

                # 2. Revert standalone fallback faces to local UVs (or Standalone Frame 0)
                for poly_idx, st_res in enumerate(resolved_standalone):
                    if st_res is None:
                        continue
                    mat, old_loc, orig_mode, old_mapping = st_res
                    polygon = mesh.polygons[poly_idx]

                    old_chunk = None
                    if old_loc and old_mapping:
                        old_chunks_map = {int(c["chunk_id"]): c for c in old_mapping.get("chunks", [])}
                        old_chunk = old_chunks_map.get(int(old_loc["chunk_id"]))

                    old_anim_info = None
                    if not (orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_chunk):
                        orig_mat = (
                            obj.material_slots[polygon.material_index].material
                            if polygon.material_index < len(obj.material_slots) else None
                        )
                        old_anim_info = get_material_animation_info(orig_mat)

                    target_anim_info = get_material_animation_info(mat)

                    remap_polygon_loop_uvs(
                        polygon=polygon,
                        uv_layer=uv_layer,
                        orig_mode=orig_mode,
                        old_loc=old_loc,
                        old_chunk=old_chunk,
                        old_anim_info=old_anim_info,
                        target_anim_info=target_anim_info,
                    )

                for poly_idx, resolved in enumerate(resolved_locations):
                    if resolved is not None:
                        face_materials[poly_idx] = atlas_materials[int(resolved[0]["chunk_id"])]

                for poly_idx, st_res in enumerate(resolved_standalone):
                    if st_res is not None:
                        face_materials[poly_idx] = st_res[0]

                apply_mesh_face_materials_and_provenance(mesh, face_materials, source_keys, source_origins)

                for prop in (
                    "mtk_anim_total_frames", "mtk_anim_frametime",
                    "mtk_anim_interpolate", "mtk_anim_frame_width",
                    "mtk_anim_frame_height",
                ):
                    if prop in obj:
                        del obj[prop]

            replaced_objects += 1

        yield ProgressUpdate(1.0, 1.0, f"Atlas replacement finished ({replaced_objects} object(s)).")
        yield StepResult.success(f"Successfully processed {replaced_objects} object(s) in Atlas Mode.")

    def _execute_standalone_mode_iter(
        self, pipeline_context, pack: ZipResourcePack, valid_objects: list, pack_textures: bool
    ) -> Iterator[Union[ProgressUpdate, StepResult]]:
        """Iteratively execute material replacement in Standalone Mode with fine-grained progress."""
        replaced_count = 0
        assigned_count = 0
        session_materials = {}

        total_objs = len(valid_objects)

        def get_or_create_replacement_material(texture_info):
            texture_key = (texture_info["namespace"], texture_info["texture_name"])
            canonical_mat = find_existing_replacement(texture_info, pack) or session_materials.get(texture_key)
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

        for obj_idx, obj in enumerate(valid_objects):
            if pipeline_context.is_cancelled:
                yield StepResult.cancelled("Material replacement cancelled by user.")
                return

            obj_progress = 0.10 + 0.85 * (obj_idx / max(1, total_objs))
            yield ProgressUpdate(obj_progress, 1.0, f"Reconstructing materials: {obj.name} ({obj_idx + 1}/{total_objs})")

            mesh = obj.data
            uv_layer = mesh.uv_layers.active_render or mesh.uv_layers.active

            def face_vector_attribute_value(name, poly_idx, default):
                attr = mesh.attributes.get(name)
                if (
                    attr and attr.domain == "FACE" and attr.data_type == "FLOAT_VECTOR"
                    and poly_idx < len(attr.data)
                ):
                    return tuple(attr.data[poly_idx].vector)
                return default

            def face_float_attribute_value(name, poly_idx, default=0.0):
                attr = mesh.attributes.get(name)
                if (
                    attr and attr.domain == "FACE" and attr.data_type == "FLOAT"
                    and poly_idx < len(attr.data)
                ):
                    return float(attr.data[poly_idx].value)
                return default

            old_mappings = {}
            for slot in obj.material_slots:
                if slot.material and slot.material not in old_mappings:
                    old_mappings[slot.material] = get_atlas_mapping_from_material(slot.material)

            resolved_faces = []
            unresolved_faces = []
            skipped_faces = []
            face_materials = [
                obj.material_slots[poly.material_index].material
                if poly.material_index < len(obj.material_slots) else None
                for poly in mesh.polygons
            ]

            for poly_idx, poly in enumerate(mesh.polygons):
                if poly.material_index >= len(obj.material_slots):
                    unresolved_faces.append(poly_idx)
                    continue
                orig_slot = obj.material_slots[poly.material_index]
                if not orig_slot.material:
                    unresolved_faces.append(poly_idx)
                    continue
                if is_ice_cube_internal_face_material(orig_slot.material):
                    skipped_faces.append(poly_idx)
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

                if not tex_info:
                    unresolved_faces.append(poly_idx)
                    continue
                resolved_faces.append((poly_idx, tex_info, orig_slot.material, orig_mode, old_loc, old_mapping))

            if unresolved_faces:
                pipeline_context.report(
                    "WARNING",
                    f"'{obj.name}' was left unchanged: {len(unresolved_faces)} face(s) could not be matched exactly."
                )
                continue
            if skipped_faces:
                pipeline_context.report(
                    "INFO",
                    f"'{obj.name}': retained {len(skipped_faces)} Ice Cube internal face(s)."
                )

            source_keys = [get_face_source_texture_key(mesh, idx) for idx in range(len(mesh.polygons))]
            source_origins = [get_face_source_origin(mesh, idx) for idx in range(len(mesh.polygons))]
            poly_modified = False
            prepared_faces = []
            material_build_failed = False

            for poly_idx, tex_info, original_material, orig_mode, old_loc, old_mapping in resolved_faces:
                mat, is_new = get_or_create_replacement_material(tex_info)
                if not mat:
                    material_build_failed = True
                    break
                prepared_faces.append((
                    poly_idx, tex_info, original_material, orig_mode,
                    old_loc, old_mapping, mat, is_new,
                ))

            if material_build_failed:
                pipeline_context.report("ERROR", f"'{obj.name}' material construction failed; no conversion was applied.")
                continue

            for poly_idx, tex_info, original_material, orig_mode, old_loc, old_mapping, mat, is_new in prepared_faces:
                face_materials[poly_idx] = mat
                source_keys[poly_idx] = canonical_texture_key(
                    tex_info["namespace"], tex_info.get("texture_key", tex_info["texture_name"])
                )
                source_origins[poly_idx] = (
                    get_face_source_origin(mesh, poly_idx) or material_source_origin(original_material)
                )
                poly_modified = True
                assigned_count += 1
                if is_new:
                    replaced_count += 1
                    pipeline_context.report("INFO", f"Built standalone material '{mat.name}' for '{tex_info['texture_name']}'")

                if uv_layer:
                    old_chunk = None
                    if orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_mapping:
                        old_chunks_map = {int(c["chunk_id"]): c for c in old_mapping.get("chunks", [])}
                        old_chunk = old_chunks_map.get(int(old_loc["chunk_id"]))

                    old_anim_info = None
                    if not (orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_chunk):
                        old_anim_info = get_material_animation_info(original_material)

                    target_anim_info = get_texture_info_animation_info(tex_info) or get_material_animation_info(mat)

                    polygon = mesh.polygons[poly_idx]
                    if orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_chunk:
                        # Atlas mesh UVs are deliberately normalized to one
                        # cell. Bake the same scale/location/rotation used by
                        # MC_Atlas_UV_Tiling before switching to a material
                        # that no longer contains that shader node.
                        tiling_scale = face_vector_attribute_value(
                            ATTR_UV_TILING_SCALE, poly_idx, (1.0, 1.0, 1.0)
                        )
                        tiling_location = face_vector_attribute_value(
                            ATTR_UV_TILING_LOCATION, poly_idx, (0.0, 0.0, 0.0)
                        )
                        tiling_rotation = face_float_attribute_value(ATTR_UV_ROTATION, poly_idx)
                        for loop_index in polygon.loop_indices:
                            uv = uv_layer.data[loop_index].uv
                            local_u, local_v = remap_uv_to_local(
                                uv.x, uv.y, orig_mode, old_loc, old_chunk, old_anim_info
                            )
                            local_u, local_v = restore_atlas_tiling_uv(
                                local_u, local_v, tiling_scale, tiling_location, tiling_rotation
                            )
                            uv.x, uv.y = remap_local_to_target_uv(
                                local_u, local_v, target_anim_info=target_anim_info
                            )
                    else:
                        remap_polygon_loop_uvs(
                            polygon=polygon,
                            uv_layer=uv_layer,
                            orig_mode=orig_mode,
                            old_loc=old_loc,
                            old_chunk=old_chunk,
                            old_anim_info=old_anim_info,
                            target_anim_info=target_anim_info,
                        )

            if poly_modified:
                apply_mesh_face_materials_and_provenance(mesh, face_materials, source_keys, source_origins)

                has_retained_atlas_face = any(
                    face_materials[poly_idx]
                    and detect_material_mode(face_materials[poly_idx]) in ("ATLAS_CHUNK", "ATLAS_UNIFIED")
                    for poly_idx in unresolved_faces + skipped_faces
                )
                if not has_retained_atlas_face:
                    for attr_name in ANIM_AND_ATLAS_ATTR_NAMES:
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
            yield StepResult.success("No exact material matches found; selected objects were left unchanged.")
            return

        yield ProgressUpdate(1.0, 1.0, f"Standalone replacement finished ({assigned_count} slots assigned).")
        yield StepResult.success(f"Successfully processed Standalone replacement ({assigned_count} slot(s) assigned, {replaced_count} new material(s) created).")

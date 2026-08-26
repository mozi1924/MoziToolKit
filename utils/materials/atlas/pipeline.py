"""
Atlas Material Replacement Execution Engine.
Processes standard polygon meshes and procedural objects, assigning Atlas chunk materials
and remapping UV coordinates and face attributes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Union, Optional
import bpy

from ..constants import (
    ATLAS_FORMAT_VERSION,
    ATTR_ATLAS_CHUNK_ID,
    ATTR_ATLAS_TEXTURE_ID,
    ATTR_UV_ROTATION,
    ATTR_ANIM_TIMING,
    ATTR_ANIM_FRAME_SIZE,
    ATTR_UV_TILING_TRANSFORM,
    ATTR_SOURCE_TEXTURE_KEY,
    ATTR_SOURCE_ORIGIN,
    FALLBACK_TEXTURE_KEY,
)
from ..pipeline.provenance import (
    canonical_texture_key,
    split_texture_key,
    write_provenance_schema,
)
from ..matching import material_source_origin
from ..pack.pack_stack import ResourcePackStack
from ..pack.resource_pack import ZipResourcePack, get_cache_dir, clean_obsolete_stack_caches
from ..biome import BiomeResolver
from ..nodes.builder import rebuild_material
from ..pack.animation import get_material_animation_info
from .builder import build_atlas_chunk_materials
from .generator import AtlasGenerator
from .addressing import AtlasAddressResolver
from ..pipeline.mesh_attributes import (
    ensure_face_attribute,
    read_face_string_attribute,
    read_face_float_attribute,
    read_face_tiling,
    compute_biome_tint_attributes,
    apply_biome_tint_attributes,
    cleanup_legacy_mesh_attributes,
    cleanup_object_anim_properties,
)
from ..pipeline.uv_pipeline import (
    remap_polygon_loop_uvs,
    remap_face_uv_to_local,
    restore_face_atlas_tiling,
    straighten_and_normalize_face_uv,
)
from ..pipeline.session import (
    build_material_face_cache,
    cached_face_texture_info,
    get_polygon_material_indices,
    name_replaced_material,
    find_existing_replacement,
    apply_mesh_face_materials_and_provenance,
    apply_generic_procedural_atlas_material,
    cleanup_unused_mtk_datablocks,
)


def _atlas_cache_is_complete(mapping: dict, atlas_dir: Path) -> bool:
    """Verify that mapping structure and all referenced chunk images exist on disk."""
    if (
        mapping.get("format_version") != ATLAS_FORMAT_VERSION
        or not mapping.get("chunks")
        or not mapping.get("textures")
    ):
        return False
    for chunk in mapping["chunks"]:
        files = chunk.get("files") if isinstance(chunk, dict) else None
        albedo = files.get("albedo") if isinstance(files, dict) else None
        if not isinstance(albedo, str) or not (atlas_dir / albedo).is_file():
            return False
        for channel in ("normal", "specular", "overlay"):
            filename = files.get(channel)
            if filename and not (atlas_dir / filename).is_file():
                return False
    return True


class AtlasReplacementEngine:
    """Executes Atlas-mode material replacement and UV remapping across target objects."""

    @classmethod
    def execute(
        cls,
        pipeline_context,
        pack: ZipResourcePack,
        valid_objects: list[bpy.types.Object],
        pack_textures: bool,
        biome_preset: str = "PLAINS",
        pack_stack: Optional[ResourcePackStack] = None,
    ) -> Iterator[Union[ProgressUpdate, StepResult]]:
        try:
            from ....pipeline.progress import ProgressUpdate
            from ....pipeline.step import StepResult
        except (ImportError, ValueError):
            try:
                from MoziToolKit.pipeline.progress import ProgressUpdate
                from MoziToolKit.pipeline.step import StepResult
            except (ImportError, ValueError):
                from pipeline.progress import ProgressUpdate
                from pipeline.step import StepResult

        effective_pack_hash = pack_stack.stack_hash if (pack_stack and pack_stack.packs) else pack.pack_hash
        cache_root = get_cache_dir()
        atlas_dir = cache_root / effective_pack_hash / "full_scene"
        mapping_path = atlas_dir / "atlas_mapping.json"

        yield ProgressUpdate(0.10, 1.0, "Checking Atlas texture cache...")

        if pipeline_context.is_cancelled:
            yield StepResult.cancelled("Material replacement cancelled by user.")
            return

        use_cache = pipeline_context.get_param("use_cache", True)
        cache_is_current = False
        if use_cache and mapping_path.exists():
            try:
                with open(mapping_path, "r", encoding="utf-8") as fp:
                    cached_mapping = json.load(fp)
                    cache_is_current = _atlas_cache_is_complete(cached_mapping, atlas_dir)
            except (OSError, json.JSONDecodeError):
                cache_is_current = False

        if not cache_is_current:
            pipeline_context.report("INFO", f"Generating Atlas texture for pack hash {effective_pack_hash[:12]}...")
            try:
                gen = AtlasGenerator(fallback_stack=pack_stack or pack)
                for frac, msg, _res in gen.build_iter(atlas_dir):
                    if pipeline_context.is_cancelled:
                        yield StepResult.cancelled("Material replacement cancelled by user.")
                        return
                    atlas_pct = 0.15 + 0.20 * frac
                    yield ProgressUpdate(atlas_pct, 1.0, f"Atlas: {msg}")
                clean_obsolete_stack_caches(current_stack_hash=effective_pack_hash)
            except Exception as e:
                yield StepResult.failed(f"Failed to generate Atlas texture: {e}")
                return

        yield ProgressUpdate(0.35, 1.0, "Reading Atlas mapping and required chunks...")

        with open(mapping_path, "r", encoding="utf-8") as fp:
            mapping_data = json.load(fp)

        if not mapping_data.get("chunks") or not mapping_data.get("textures"):
            yield StepResult.failed("Atlas generation produced no usable texture chunks.")
            return

        resolver = AtlasAddressResolver(mapping_data)
        fallback_location = resolver.lookup_texture(FALLBACK_TEXTURE_KEY) or resolver._locations.get(FALLBACK_TEXTURE_KEY)
        if fallback_location is None:
            yield StepResult.failed("Atlas mapping is missing its required fallback tile (chunk 0, slot 0).")
            return

        chunks_by_id = resolver._chunks_by_id
        texture_map = resolver._locations

        standard_mesh_objects = [obj for obj in valid_objects if len(obj.data.polygons) > 0]
        generic_procedural_objects = [obj for obj in valid_objects if len(obj.data.polygons) == 0]

        # Collect required chunks from standard polygon mesh objects
        required_chunk_ids = set()
        total_faces = sum(len(obj.data.polygons) for obj in standard_mesh_objects)
        scanned_faces = 0
        for obj in standard_mesh_objects:
            mesh = obj.data
            slot_materials, material_cache = build_material_face_cache(obj, mesh)
            source_keys = read_face_string_attribute(mesh, ATTR_SOURCE_TEXTURE_KEY)
            material_indices = get_polygon_material_indices(mesh)
            for poly_idx, material_index in enumerate(material_indices):
                scanned_faces += 1
                if scanned_faces % 10_000 == 0:
                    if pipeline_context.is_cancelled:
                        yield StepResult.cancelled("Material replacement cancelled by user.")
                        return
                    progress = 0.35 + 0.08 * (scanned_faces / max(1, total_faces))
                    yield ProgressUpdate(progress, 1.0, f"Reading Atlas attributes: {scanned_faces:,}/{total_faces:,} faces")
                if material_index >= len(slot_materials):
                    continue
                slot_mat = slot_materials[material_index]
                if not slot_mat:
                    continue
                state = material_cache[slot_mat]
                if state["is_internal"]:
                    continue
                namespace, candidates, _old_loc = cached_face_texture_info(
                    mesh, poly_idx, slot_mat, state, source_keys[poly_idx]
                )
                loc = resolver.lookup_texture(candidates, namespace=namespace)
                if loc is not None:
                    required_chunk_ids.add(int(loc["chunk_id"]))

        if generic_procedural_objects or not required_chunk_ids:
            static_chunks = [int(c["chunk_id"]) for c in mapping_data.get("chunks", []) if c.get("kind") == "static"]
            required_chunk_ids.update(static_chunks if static_chunks else [0])

        yield ProgressUpdate(0.45, 1.0, "Building Atlas chunk material(s)...")

        if pipeline_context.is_cancelled:
            yield StepResult.cancelled("Material replacement cancelled by user.")
            return

        # Fallback is always materialized; unsupported faces may be discovered
        # after the initial source scan.
        effective_chunks = (required_chunk_ids if required_chunk_ids else {0}) | {0}
        atlas_materials = build_atlas_chunk_materials(
            atlas_dir,
            pack_hash=effective_pack_hash,
            pack_textures=pack_textures,
            chunk_ids=effective_chunks,
        )

        session_materials = {}
        biome_resolver = BiomeResolver(pack_root=pack.extract_dir)
        if pack_stack:
            for p in pack_stack.packs:
                if p.extract_dir and p.extract_dir != pack.extract_dir:
                    biome_resolver.load_from_pack_root(p.extract_dir)

        def get_or_create_replacement_material(texture_info):
            texture_key = (texture_info["namespace"], texture_info["texture_name"])
            canonical_mat = session_materials.get(texture_key) or find_existing_replacement(texture_info, pack)
            if canonical_mat:
                session_materials[texture_key] = canonical_mat
                return canonical_mat, False

            mat_name = f"mtk:{texture_info['namespace']}:{texture_info['texture_name']}"
            mat = bpy.data.materials.new(name=mat_name)
            if not rebuild_material(mat, texture_info, pack_textures=pack_textures, pack_hash=effective_pack_hash):
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

            if len(mesh.polygons) == 0:
                if apply_generic_procedural_atlas_material(obj, atlas_materials, mapping_data):
                    replaced_objects += 1
                continue

            uv_layer = mesh.uv_layers.active_render or mesh.uv_layers.active

            slot_materials, material_cache = build_material_face_cache(obj, mesh)
            material_indices = get_polygon_material_indices(mesh)

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

            poly_tint_map = {}
            resolved_locations = [None] * len(mesh.polygons)
            resolved_standalone = [None] * len(mesh.polygons)
            source_keys = read_face_string_attribute(mesh, ATTR_SOURCE_TEXTURE_KEY)
            source_origins = read_face_string_attribute(mesh, ATTR_SOURCE_ORIGIN)
            unresolved_faces = []
            skipped_faces = []
            face_materials = [
                slot_materials[material_index]
                if material_index < len(slot_materials) else None
                for material_index in material_indices
            ]
            poly_updated = False

            total_polys = max(1, len(mesh.polygons))
            for poly_idx, material_index in enumerate(material_indices):
                if poly_idx > 0 and poly_idx % 2000 == 0:
                    if pipeline_context.is_cancelled:
                        yield StepResult.cancelled("Material replacement cancelled by user.")
                        return
                    sub_prog = obj_progress + 0.20 * (poly_idx / total_polys)
                    yield ProgressUpdate(sub_prog, 1.0, f"Scanning Atlas faces: {obj.name} ({poly_idx:,}/{total_polys:,})")

                orig_mat = slot_materials[material_index] if material_index < len(slot_materials) else None
                source_key = source_keys[poly_idx] if poly_idx < len(source_keys) else ""

                if not orig_mat:
                    if source_key:
                        namespace, texture_key = split_texture_key(source_key)
                        candidates = [texture_key] if texture_key else []
                        if "/" in texture_key:
                            basename = texture_key.rsplit("/", 1)[-1]
                            if basename and basename != texture_key:
                                candidates.append(basename)
                        state = None
                        old_mapping = None
                        orig_mode = "GENERIC"
                        old_loc = None
                    else:
                        chunk_ids[poly_idx] = 0.0
                        texture_ids[poly_idx] = 0.0
                        poly_tint_map[poly_idx] = fallback_location
                        resolved_locations[poly_idx] = (fallback_location, None, "GENERIC", None)
                        poly_updated = True
                        unresolved_faces.append(poly_idx)
                        continue
                else:
                    state = material_cache[orig_mat]
                    if state["is_internal"]:
                        skipped_faces.append(poly_idx)
                        continue

                    old_mapping = state["mapping"]
                    orig_mode = state["mode"]
                    namespace, candidates, old_loc = cached_face_texture_info(
                        mesh, poly_idx, orig_mat, state, source_key
                    )

                new_location = resolver.lookup_texture(candidates, namespace=namespace)

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

                    poly_tint_map[poly_idx] = new_location
                    resolved_locations[poly_idx] = (new_location, old_loc, orig_mode, old_mapping)
                    target_namespace, target_texture = split_texture_key(
                        new_location.get("texture_key", candidates[0])
                    )
                    source_keys[poly_idx] = canonical_texture_key(target_namespace, target_texture)
                    source_origins[poly_idx] = source_origins[poly_idx] or state["origin"]
                    poly_updated = True
                else:
                    # Non-atlas texture fallback
                    fallback_tex_info = None
                    for cand in candidates:
                        info = pack_stack.get_texture_info(cand, namespace) if pack_stack else pack.get_texture_info(cand, namespace)
                        if info and info.get("albedo"):
                            fallback_tex_info = dict(info)
                            overlay_stem = biome_resolver.get_overlay_texture(fallback_tex_info["texture_name"])
                            if overlay_stem:
                                overlay_info = pack_stack.get_texture_info(overlay_stem, namespace) if pack_stack else pack.get_texture_info(overlay_stem, namespace)
                                if overlay_info and overlay_info.get("albedo"):
                                    fallback_tex_info["overlay"] = overlay_info["albedo"]
                                    if overlay_info.get("albedo_mcmeta"):
                                        fallback_tex_info["overlay_mcmeta"] = overlay_info["albedo_mcmeta"]
                            fallback_tex_info["tint_info"] = biome_resolver.get_tint_info(fallback_tex_info["texture_name"])
                            break

                    if fallback_tex_info:
                        mat, _is_new = get_or_create_replacement_material(fallback_tex_info)
                        if mat:
                            resolved_standalone[poly_idx] = (mat, old_loc, orig_mode, old_mapping)
                            source_keys[poly_idx] = canonical_texture_key(
                                fallback_tex_info["namespace"],
                                fallback_tex_info.get("texture_key", fallback_tex_info["texture_name"]),
                            )
                            source_origins[poly_idx] = source_origins[poly_idx] or state["origin"]
                            poly_tint_map[poly_idx] = fallback_tex_info.get("tint_info") or biome_resolver.get_tint_info(fallback_tex_info["texture_name"])
                            poly_updated = True
                            continue

                    # Retain the source identity, but render the stable atlas
                    # fallback at chunk 0 / texture 0.  This keeps the object
                    # convertible when only one block is unsupported.
                    new_location = fallback_location
                    chunk_ids[poly_idx] = 0.0
                    texture_ids[poly_idx] = 0.0
                    poly_tint_map[poly_idx] = fallback_location
                    resolved_locations[poly_idx] = (new_location, old_loc, orig_mode, old_mapping)
                    if not source_keys[poly_idx] and candidates:
                        source_keys[poly_idx] = canonical_texture_key(namespace, candidates[0])
                    source_origins[poly_idx] = source_origins[poly_idx] or state["origin"]
                    poly_updated = True
                    unresolved_faces.append(poly_idx)

            if skipped_faces:
                pipeline_context.report("INFO", f"'{obj.name}': retained {len(skipped_faces)} Ice Cube internal face(s).")

            if unresolved_faces:
                pipeline_context.report("WARNING", f"'{obj.name}': {len(unresolved_faces)} unsupported face(s) assigned atlas fallback chunk 0 / texture 0.")

            if poly_updated:
                if uv_layer is not None:
                    for poly_idx, resolved in enumerate(resolved_locations):
                        if poly_idx > 0 and poly_idx % 2000 == 0:
                            if pipeline_context.is_cancelled:
                                yield StepResult.cancelled("Material replacement cancelled by user.")
                                return
                            sub_prog = obj_progress + 0.20 + 0.20 * (poly_idx / total_polys)
                            yield ProgressUpdate(sub_prog, 1.0, f"Remapping Atlas UVs: {obj.name} ({poly_idx:,}/{total_polys:,})")

                        if resolved is None:
                            continue
                        new_location, old_loc, orig_mode, old_mapping = resolved
                        polygon = mesh.polygons[poly_idx]
                        target_chunk = chunks_by_id[int(new_location["chunk_id"])]

                        old_chunk = None
                        if old_loc and old_mapping:
                            original_mat = face_materials[poly_idx]
                            if original_mat:
                                old_chunk = material_cache.get(original_mat, {}).get("chunks", {}).get(int(old_loc["chunk_id"]))

                        old_anim_info = None
                        if not (orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_chunk):
                            orig_mat = face_materials[poly_idx]
                            if orig_mat:
                                state = material_cache.get(orig_mat)
                                if state and not state["animation_loaded"]:
                                    state["animation"] = get_material_animation_info(orig_mat)
                                    state["animation_loaded"] = True
                                old_anim_info = state["animation"] if state else get_material_animation_info(orig_mat)

                        remap_face_uv_to_local(polygon, uv_layer, orig_mode, old_loc, old_chunk, old_anim_info)

                        if orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_chunk:
                            old_tiling_scale, old_tiling_location = read_face_tiling(mesh, poly_idx)
                            old_tiling_rotation = read_face_float_attribute(mesh, ATTR_UV_ROTATION, poly_idx)
                            restore_face_atlas_tiling(polygon, uv_layer, old_tiling_scale, old_tiling_location, old_tiling_rotation)

                        rot_angle, scale, location = straighten_and_normalize_face_uv(polygon, uv_layer)
                        uv_rotations[poly_idx] = rot_angle
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
                ):
                    ensure_face_attribute(mesh, attr_name, "FLOAT").data.foreach_set("value", data)

                packed_tint_data, tint_colors = compute_biome_tint_attributes(
                    len(mesh.polygons), poly_tint_map, biome_preset
                )
                apply_biome_tint_attributes(mesh, packed_tint_data, tint_colors)

                for attr_name, data in (
                    (ATTR_ANIM_TIMING, zip(anim_frames, anim_frametimes, anim_interps, anim_widths)),
                    (ATTR_ANIM_FRAME_SIZE, ((width, height, 0.0, 1.0) for width, height in zip(anim_widths, anim_heights))),
                    (ATTR_UV_TILING_TRANSFORM, ((scale[0], scale[1], location[0], location[1]) for scale, location in zip(uv_tiling_scales, uv_tiling_locations))),
                ):
                    ensure_face_attribute(mesh, attr_name, "FLOAT_COLOR").data.foreach_set(
                        "color", [component for value in data for component in value]
                    )

                cleanup_legacy_mesh_attributes(mesh)

                # Revert standalone fallback faces to local UVs
                for poly_idx, st_res in enumerate(resolved_standalone):
                    if st_res is None:
                        continue
                    mat, old_loc, orig_mode, old_mapping = st_res
                    polygon = mesh.polygons[poly_idx]

                    old_chunk = None
                    if old_loc and old_mapping:
                        original_mat = face_materials[poly_idx]
                        if original_mat:
                            old_chunk = material_cache.get(original_mat, {}).get("chunks", {}).get(int(old_loc["chunk_id"]))

                    old_anim_info = None
                    if not (orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_chunk):
                        orig_mat = face_materials[poly_idx]
                        if orig_mat:
                            state = material_cache.get(orig_mat)
                            if state and not state["animation_loaded"]:
                                state["animation"] = get_material_animation_info(orig_mat)
                                state["animation_loaded"] = True
                            old_anim_info = state["animation"] if state else get_material_animation_info(orig_mat)

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
                mesh["mtk:atlas_mapping"] = json.dumps(mapping_data, separators=(",", ":"))
                write_provenance_schema(mesh)
                cleanup_object_anim_properties(obj)

            replaced_objects += 1

        cleanup_unused_mtk_datablocks()
        yield ProgressUpdate(1.0, 1.0, f"Atlas replacement finished ({replaced_objects} object(s)).")
        yield StepResult.success(f"Successfully processed {replaced_objects} object(s) in Atlas Mode.")

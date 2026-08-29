"""
Standalone Material Replacement Execution Engine.
Reconstructs individual standalone materials per texture with PBR channels and animation synchronization,
and updates mesh UV coordinates, biome tint attributes, and material slots.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Union, Optional
import bpy

from ..constants import (
    ATLAS_FORMAT_VERSION,
    ANIM_AND_ATLAS_ATTR_NAMES,
    ATTR_UV_ROTATION,
    ATTR_SOURCE_TEXTURE_KEY,
    ATTR_SOURCE_ORIGIN,
    FALLBACK_TEXTURE_KEY,
)
from ..pipeline.provenance import (
    canonical_texture_key,
    detect_material_mode,
    split_texture_key,
)
from ..matching import material_source_origin
from ..pack.pack_stack import ResourcePackStack
from ..pack.resource_pack import ZipResourcePack, get_cache_dir, clean_obsolete_stack_caches
from ..biome import BiomeResolver
from ..nodes.builder import rebuild_material
from ..pack.animation import get_material_animation_info, get_texture_info_animation_info
from ..atlas.generator import AtlasGenerator
from .generator import StandaloneGenerator, STANDALONE_FORMAT_VERSION
from ..atlas.layout import remap_uv_to_local, remap_local_to_target_uv
from ...mesh import restore_atlas_tiling_uv
from ...mesh.fluid_uv import is_fluid_texture_name, normalize_static_fluid_face_uv
from ..pipeline.mesh_attributes import (
    read_face_string_attribute,
    read_face_float_attribute,
    read_face_tiling,
    compute_biome_tint_attributes,
    apply_biome_tint_attributes,
    cleanup_legacy_mesh_attributes,
    cleanup_object_anim_properties,
)

from ..pipeline.uv_pipeline import remap_polygon_loop_uvs
from ..pipeline.session import (
    build_material_face_cache,
    cached_face_texture_info,
    get_polygon_material_indices,
    name_replaced_material,
    find_existing_replacement,
    apply_mesh_face_materials_and_provenance,
    cleanup_unused_mtk_datablocks,
)


class StandaloneReplacementEngine:
    """Executes Standalone-mode material replacement and UV remapping across target objects."""

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

        replaced_count = 0
        assigned_count = 0
        session_materials = {}
        texture_info_cache = {}

        effective_pack_hash = pack_stack.stack_hash if (pack_stack and pack_stack.packs) else pack.pack_hash
        cache_root = get_cache_dir()
        atlas_dir = cache_root / effective_pack_hash / "full_scene"
        atlas_mapping_path = atlas_dir / "atlas_mapping.json"
        standalone_dir = cache_root / effective_pack_hash / "standalone"
        mapping_path = standalone_dir / "standalone_mapping.json"

        use_cache = pipeline_context.get_param("use_cache", True)

        # 1. Validate Standalone Asset Library
        standalone_mapping = None
        if use_cache and mapping_path.exists():
            try:
                with open(mapping_path, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    if data.get("format_version") == STANDALONE_FORMAT_VERSION and data.get("stack_hash") == effective_pack_hash:
                        standalone_mapping = data
            except Exception:
                standalone_mapping = None

        if not standalone_mapping:
            yield StepResult.failed(
                "The configured Resource Pack Stack has not been precompiled for Standalone mode. "
                "Please go to Edit > Preferences > Add-ons > MoziToolKit and click 'Precompile / Rebuild Stack Atlas Cache'."
            )
            return

        biome_root = pack.zip_path if pack.zip_path.is_dir() else (pack._extract_dir if pack._loaded else None)
        biome_resolver = BiomeResolver(pack_root=biome_root)

        total_objs = len(valid_objects)
        textures_map = standalone_mapping.get("textures", {}) if standalone_mapping else {}
        aliases_map = standalone_mapping.get("aliases", {}) if standalone_mapping else {}

        def get_or_create_replacement_material(texture_info):
            texture_key = (effective_pack_hash, texture_info["namespace"], texture_info["texture_name"])
            canonical_mat = session_materials.get(texture_key) or find_existing_replacement(texture_info, effective_pack_hash)
            if canonical_mat:
                session_materials[texture_key] = canonical_mat
                return canonical_mat, False

            mat_name = f"mtk:{texture_info['namespace']}:{texture_info['texture_name']}"
            mat = bpy.data.materials.new(name=mat_name)
            if not rebuild_material(mat, texture_info, pack_textures=pack_textures, pack_hash=effective_pack_hash):
                bpy.data.materials.remove(mat)
                return None, False

            name_replaced_material(mat, texture_info, effective_pack_hash)
            session_materials[texture_key] = mat
            return mat, True

        def resolve_texture_info(namespace, candidates):
            cache_key = (namespace, tuple(candidates))
            if cache_key in texture_info_cache:
                return texture_info_cache[cache_key]

            tex_info = None
            for cand in candidates:
                cand_key = f"{namespace}:{cand}"
                rec = (
                    textures_map.get(cand_key)
                    or textures_map.get(canonical_texture_key(namespace, cand))
                    or textures_map.get(f"{namespace}:block/{cand}")
                    or textures_map.get(f"{namespace}:item/{cand}")
                    or (textures_map.get(aliases_map.get(cand)) if aliases_map.get(cand) else None)
                )
                if rec and isinstance(rec, dict) and rec.get("files"):
                    files = rec["files"]
                    albedo_rel = files.get("albedo")
                    if albedo_rel and (standalone_dir / albedo_rel).exists():
                        tex_info = {
                            "namespace": rec.get("namespace", namespace),
                            "texture_name": rec.get("texture_name", cand),
                            "texture_key": rec.get("texture_key", cand),
                            "albedo": standalone_dir / albedo_rel,
                            "normal": (standalone_dir / files["normal"]) if files.get("normal") and (standalone_dir / files["normal"]).exists() else None,
                            "specular": (standalone_dir / files["specular"]) if files.get("specular") and (standalone_dir / files["specular"]).exists() else None,
                            "overlay": (standalone_dir / files["overlay"]) if files.get("overlay") and (standalone_dir / files["overlay"]).exists() else None,
                            "albedo_mcmeta": rec.get("animation"),
                            "normal_mcmeta": rec.get("animation"),
                            "specular_mcmeta": rec.get("animation"),
                            "overlay_mcmeta": rec.get("animation"),
                            "tint_info": rec.get("tint_info") or biome_resolver.get_tint_info(rec.get("texture_name", cand)),
                            "is_precompiled": True,
                            "animation_metadata": rec.get("animation"),
                            "pack_hash": effective_pack_hash,
                        }
                        break

                info = pack_stack.get_texture_info(cand, namespace) if pack_stack else pack.get_texture_info(cand, namespace)
                if not info or not info.get("albedo"):
                    continue
                tex_info = dict(info)
                overlay_stem = biome_resolver.get_overlay_texture(tex_info["texture_name"])
                if overlay_stem:
                    overlay_info = pack_stack.get_texture_info(overlay_stem, namespace) if pack_stack else pack.get_texture_info(overlay_stem, namespace)
                    if overlay_info and overlay_info.get("albedo"):
                        tex_info["overlay"] = overlay_info["albedo"]
                        if overlay_info.get("albedo_mcmeta"):
                            tex_info["overlay_mcmeta"] = overlay_info["albedo_mcmeta"]
                tex_info["tint_info"] = biome_resolver.get_tint_info(tex_info["texture_name"])
                tex_info["pack_hash"] = effective_pack_hash
                break

            texture_info_cache[cache_key] = tex_info
            return tex_info

        for obj_idx, obj in enumerate(valid_objects):
            if pipeline_context.is_cancelled:
                yield StepResult.cancelled("Material replacement cancelled by user.")
                return

            obj_progress = 0.10 + 0.85 * (obj_idx / max(1, total_objs))
            yield ProgressUpdate(obj_progress, 1.0, f"Reconstructing materials: {obj.name} ({obj_idx + 1}/{total_objs})")

            mesh = obj.data
            uv_layer = mesh.uv_layers.active_render or mesh.uv_layers.active

            slot_materials, material_cache = build_material_face_cache(obj, mesh)
            material_indices = get_polygon_material_indices(mesh)
            existing_source_keys = read_face_string_attribute(mesh, ATTR_SOURCE_TEXTURE_KEY)
            existing_source_origins = read_face_string_attribute(mesh, ATTR_SOURCE_ORIGIN)

            resolved_faces = []
            unresolved_faces = []
            skipped_faces = []
            face_materials = [
                slot_materials[material_index]
                if material_index < len(slot_materials) else None
                for material_index in material_indices
            ]

            total_polys = max(1, len(mesh.polygons))
            for poly_idx, material_index in enumerate(material_indices):
                if poly_idx > 0 and poly_idx % 2000 == 0:
                    if pipeline_context.is_cancelled:
                        yield StepResult.cancelled("Material replacement cancelled by user.")
                        return
                    sub_prog = obj_progress + 0.35 * (poly_idx / total_polys)
                    yield ProgressUpdate(sub_prog, 1.0, f"Scanning faces: {obj.name} ({poly_idx:,}/{total_polys:,})")

                orig_mat = slot_materials[material_index] if material_index < len(slot_materials) else None
                source_key = existing_source_keys[poly_idx] if poly_idx < len(existing_source_keys) else ""

                if not orig_mat:
                    if source_key:
                        namespace, texture_key = split_texture_key(source_key)
                        candidates = [texture_key] if texture_key else []
                        if "/" in texture_key:
                            basename = texture_key.rsplit("/", 1)[-1]
                            if basename and basename != texture_key:
                                candidates.append(basename)
                        tex_info = resolve_texture_info(namespace, candidates) if candidates else None
                        if tex_info:
                            resolved_faces.append((poly_idx, tex_info, None, "GENERIC", None, None))
                            continue
                        else:
                            unresolved_faces.append((poly_idx, None, None, namespace, candidates, None, None))
                            continue
                    else:
                        unresolved_faces.append((poly_idx, None, None, "minecraft", [], None, None))
                        continue

                state = material_cache[orig_mat]
                if state["is_internal"]:
                    skipped_faces.append(poly_idx)
                    continue

                old_mapping = state["mapping"]
                orig_mode = state["mode"]
                namespace, candidates, old_loc = cached_face_texture_info(
                    mesh, poly_idx, orig_mat, state, source_key
                )

                tex_info = resolve_texture_info(namespace, candidates)

                if not tex_info:
                    unresolved_faces.append((poly_idx, orig_mat, state, namespace, candidates, old_loc, old_mapping))
                    continue
                resolved_faces.append((poly_idx, tex_info, orig_mat, orig_mode, old_loc, old_mapping))

            if skipped_faces:
                pipeline_context.report(
                    "INFO",
                    f"'{obj.name}': retained {len(skipped_faces)} Ice Cube internal face(s)."
                )

            source_keys = existing_source_keys
            source_origins = existing_source_origins
            poly_modified = False
            replacement_by_texture = {}
            texture_infos_by_key = {}
            target_animation_by_texture = {}
            material_build_failed = False

            # The generated procedural tile is a real standalone material, so
            # a single bad source never aborts a mixed-material object.
            fallback_tex_info = resolve_texture_info("mozi", ["fallback"])
            fallback_material = None
            if unresolved_faces and fallback_tex_info:
                fallback_material, fallback_is_new = get_or_create_replacement_material(fallback_tex_info)
                if fallback_is_new:
                    replaced_count += 1
            if unresolved_faces and not fallback_material:
                pipeline_context.report("ERROR", f"'{obj.name}' fallback material construction failed; no conversion was applied.")
                continue

            for poly_idx, tex_info, original_material, orig_mode, old_loc, old_mapping in resolved_faces:
                texture_key = (tex_info["namespace"], tex_info["texture_name"])
                if texture_key in replacement_by_texture:
                    continue
                mat, is_new = get_or_create_replacement_material(tex_info)
                if not mat:
                    material_build_failed = True
                    break
                replacement_by_texture[texture_key] = (mat, is_new)
                texture_infos_by_key[texture_key] = tex_info
                target_animation_by_texture[texture_key] = (
                    get_texture_info_animation_info(tex_info) or get_material_animation_info(mat)
                )

            if material_build_failed:
                pipeline_context.report("ERROR", f"'{obj.name}' material construction failed; no conversion was applied.")
                continue

            for texture_key, (mat, is_new) in replacement_by_texture.items():
                if is_new:
                    replaced_count += 1
                    tex_info = texture_infos_by_key[texture_key]
                    pipeline_context.report("INFO", f"Built standalone material '{mat.name}' for '{tex_info['texture_name']}'")

            for poly_idx, original_material, state, namespace, candidates, _old_loc, _old_mapping in unresolved_faces:
                face_materials[poly_idx] = fallback_material
                # Never replace provenance with ``mozi:fallback``: retaining the
                # original key lets a later pack replace this face normally.
                if not source_keys[poly_idx] and candidates:
                    source_keys[poly_idx] = canonical_texture_key(namespace, candidates[0])
                if original_material and not source_origins[poly_idx]:
                    source_origins[poly_idx] = state["origin"] if state else material_source_origin(original_material)
                poly_modified = True
                assigned_count += 1
            if unresolved_faces:
                pipeline_context.report("WARNING", f"'{obj.name}': {len(unresolved_faces)} unsupported face(s) assigned the procedural fallback.")

            total_prep = max(1, len(resolved_faces))
            for prep_idx, (poly_idx, tex_info, original_material, orig_mode, old_loc, old_mapping) in enumerate(resolved_faces):
                if prep_idx > 0 and prep_idx % 2000 == 0:
                    if pipeline_context.is_cancelled:
                        yield StepResult.cancelled("Material replacement cancelled by user.")
                        return
                    sub_prog = obj_progress + 0.35 + 0.45 * (prep_idx / total_prep)
                    yield ProgressUpdate(sub_prog, 1.0, f"Reconstructing materials: {obj.name} ({prep_idx:,}/{total_prep:,})")

                mat, _is_new = replacement_by_texture[(tex_info["namespace"], tex_info["texture_name"])]

                face_materials[poly_idx] = mat
                source_keys[poly_idx] = canonical_texture_key(
                    tex_info["namespace"], tex_info.get("texture_key", tex_info["texture_name"])
                )
                source_origins[poly_idx] = (
                    source_origins[poly_idx]
                    or (material_cache.get(original_material, {}).get("origin") if original_material else None)
                    or (material_source_origin(original_material) if original_material else "")
                )
                poly_modified = True
                assigned_count += 1

                if uv_layer:
                    old_chunk = None
                    if orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_mapping and original_material:
                        old_chunk = material_cache.get(original_material, {}).get("chunks", {}).get(int(old_loc["chunk_id"]))

                    old_anim_info = None
                    if not (orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_chunk):
                        if original_material:
                            state = material_cache.get(original_material)
                            if state and not state["animation_loaded"]:
                                state["animation"] = get_material_animation_info(original_material)
                                state["animation_loaded"] = True
                            old_anim_info = state["animation"] if state else get_material_animation_info(original_material)

                    texture_key = (tex_info["namespace"], tex_info["texture_name"])
                    target_anim_info = target_animation_by_texture[texture_key]

                    if (
                        orig_mode in ("GENERIC", "STANDALONE")
                        and old_anim_info is None
                        and target_anim_info is None
                    ):
                        continue

                    polygon = mesh.polygons[poly_idx]
                    is_yefira = bool(obj.get("mtk:is_yefira_world") or obj.get("mtk:section_pos") is not None or obj.name.startswith("Yefira_"))
                    if is_fluid_texture_name(tex_info["texture_name"]) and orig_mode == "GENERIC" and not is_yefira:
                        normalize_static_fluid_face_uv(polygon, mesh, uv_layer, texture_name=tex_info["texture_name"])

                    if orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_chunk:
                        tiling_scale, tiling_location = read_face_tiling(mesh, poly_idx)
                        tiling_rotation = read_face_float_attribute(mesh, "mtk_uv_rotation", poly_idx)
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
                poly_tint_map = {
                    poly_idx: tex_info.get("tint_info") or biome_resolver.get_tint_info(tex_info["texture_name"])
                    for poly_idx, tex_info, _, _, _, _ in resolved_faces
                }
                packed_tint_data, tint_colors = compute_biome_tint_attributes(
                    len(mesh.polygons), poly_tint_map, biome_preset
                )
                apply_biome_tint_attributes(mesh, packed_tint_data, tint_colors)
                cleanup_legacy_mesh_attributes(mesh)
                apply_mesh_face_materials_and_provenance(mesh, face_materials, source_keys, source_origins)

                has_retained_atlas_face = any(
                    face_materials[poly_idx]
                    and detect_material_mode(face_materials[poly_idx]) in ("ATLAS_CHUNK", "ATLAS_UNIFIED")
                    for poly_idx in ([entry[0] for entry in unresolved_faces] + skipped_faces)
                )
                if not has_retained_atlas_face:
                    for attr_name in ANIM_AND_ATLAS_ATTR_NAMES:
                        attr = mesh.attributes.get(attr_name)
                        if attr:
                            mesh.attributes.remove(attr)
                    cleanup_object_anim_properties(obj)

        if assigned_count == 0:
            cleanup_unused_mtk_datablocks()
            yield StepResult.success("No exact material matches found; selected objects were left unchanged.")
            return

        cleanup_unused_mtk_datablocks()
        yield ProgressUpdate(1.0, 1.0, f"Standalone replacement finished ({assigned_count} slots assigned).")
        yield StepResult.success(f"Successfully processed Standalone replacement ({assigned_count} slot(s) assigned, {replaced_count} new material(s) created).")

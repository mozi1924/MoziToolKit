"""
Importer Matching and Material Format Adaptation System.
"""

from __future__ import annotations

from typing import Optional, Tuple, List
import bpy

from .base import (
    ImporterAdapter,
    MaterialMatchPreset,
    base_texture_candidates,
    extract_texture_provenance_from_image,
    normalized_image_key,
)
from .generic import GenericAdapter, generic_texture_candidates
from .ice_cube import (
    IceCubeAdapter,
    is_ice_cube_material,
    is_ice_cube_internal_face_material,
    ice_cube_texture_candidates,
    ice_cube_name_aliases,
    ice_cube_legacy_aliases,
    ICE_CUBE_ENTITY_ALIASES,
    ICE_CUBE_MATERIAL_NAME_ALIASES,
)
from .jmc2obj import (
    Jmc2objAdapter,
    is_jmc2obj_material,
    jmc2obj_texture_candidates,
    JMC2OBJ_BANNER_SHORT_ALIASES,
    JMC2OBJ_BIOME_SUFFIXES,
)
from .mineways import (
    MinewaysAdapter,
    is_mineways_material,
    mineways_texture_candidates,
    MINEWAYS_BLOCK_NAME_ALIASES,
)
from ..constants import (
    ATTR_ATLAS_CHUNK_ID,
    ATTR_ATLAS_TEXTURE_ID,
    ATTR_SOURCE_ORIGIN,
    ATTR_SOURCE_TEXTURE_KEY,
    DEFAULT_NAMESPACE,
)
from ..provenance import (
    without_blender_suffix,
    canonical_texture_key,
    split_texture_key,
    detect_material_mode,
    is_mozi_material,
    get_face_source_origin,
    get_face_source_texture_key,
    get_atlas_mapping_from_material,
    write_face_source_provenance,
)
from ..atlas_layout import find_texture_id_from_atlas_uv


# Instantiated format adapters (order defines priority)
ICE_CUBE_ADAPTER = IceCubeAdapter()
JMC2OBJ_ADAPTER = Jmc2objAdapter()
MINEWAYS_ADAPTER = MinewaysAdapter()
GENERIC_ADAPTER = GenericAdapter()

ADAPTERS: tuple[ImporterAdapter, ...] = (
    ICE_CUBE_ADAPTER,
    JMC2OBJ_ADAPTER,
    MINEWAYS_ADAPTER,
    GENERIC_ADAPTER,
)

# Compatibility Presets
ICE_CUBE_PRESET = MaterialMatchPreset(
    identifier=ICE_CUBE_ADAPTER.identifier,
    description=ICE_CUBE_ADAPTER.description,
    detects=ICE_CUBE_ADAPTER.detect,
    extract_keys=ICE_CUBE_ADAPTER.extract_keys,
)
JMC2OBJ_PRESET = MaterialMatchPreset(
    identifier=JMC2OBJ_ADAPTER.identifier,
    description=JMC2OBJ_ADAPTER.description,
    detects=JMC2OBJ_ADAPTER.detect,
    extract_keys=JMC2OBJ_ADAPTER.extract_keys,
)
MINEWAYS_PRESET = MaterialMatchPreset(
    identifier=MINEWAYS_ADAPTER.identifier,
    description=MINEWAYS_ADAPTER.description,
    detects=MINEWAYS_ADAPTER.detect,
    extract_keys=MINEWAYS_ADAPTER.extract_keys,
)
GENERIC_PRESET = MaterialMatchPreset(
    identifier=GENERIC_ADAPTER.identifier,
    description=GENERIC_ADAPTER.description,
    detects=GENERIC_ADAPTER.detect,
    extract_keys=GENERIC_ADAPTER.extract_keys,
)
MATCH_PRESETS: tuple[MaterialMatchPreset, ...] = (
    ICE_CUBE_PRESET,
    JMC2OBJ_PRESET,
    MINEWAYS_PRESET,
    GENERIC_PRESET,
)


def get_importer_adapter(mat: bpy.types.Material | None) -> ImporterAdapter:
    """Find the first matching importer adapter for a given material."""
    if not mat:
        return GENERIC_ADAPTER
    for adapter in ADAPTERS:
        if adapter.detect(mat):
            return adapter
    return GENERIC_ADAPTER


def get_material_match_preset(mat: bpy.types.Material) -> MaterialMatchPreset:
    """Legacy compatibility bridge function."""
    adapter = get_importer_adapter(mat)
    for preset in MATCH_PRESETS:
        if preset.identifier == adapter.identifier:
            return preset
    return GENERIC_PRESET


def material_source_origin(mat: bpy.types.Material | None) -> str:
    """Classify an external material without conflating it with Mozi mode."""
    if is_mozi_material(mat):
        return "mozi"
    return get_importer_adapter(mat).identifier if mat else "generic"


def extract_material_texture_keys(mat: bpy.types.Material) -> tuple[str, list[str]]:
    """Extract candidates using the detected importer adapter from material metadata."""
    adapter = get_importer_adapter(mat)
    if adapter.is_internal_or_skipped(mat):
        return DEFAULT_NAMESPACE, []
    return adapter.extract_keys(mat)


def _atlas_mapping_index(mapping: dict) -> dict:
    """Build and retain O(1) lookups for a parsed atlas mapping.

    This function is used in per-face conversion paths.  Scanning every
    mapping texture for every polygon makes re-atlasing older, uncompressed
    models effectively quadratic and can freeze Blender for minutes.
    """
    cache_key = "_mtk_runtime_atlas_lookup"
    cached = mapping.get(cache_key)
    if cached:
        return cached

    locations = {}
    for tex_name, location in mapping.get("textures", {}).items():
        if location is None:
            continue
        try:
            key = (int(location.get("chunk_id", -1)), int(location.get("texture_id", -1)))
        except (TypeError, ValueError):
            continue
        locations[key] = (tex_name, location)

    animations_by_chunk = {}
    animations_by_location = {}
    for animation in mapping.get("animations", []):
        try:
            chunk_id = int(animation.get("chunk_id", -1))
        except (TypeError, ValueError):
            continue
        animations_by_chunk.setdefault(chunk_id, []).append(animation)
        try:
            texture_id = int(animation.get("texture_id", -1))
        except (TypeError, ValueError):
            continue
        animations_by_location[(chunk_id, texture_id)] = animation

    cached = {
        "chunks": {int(chunk["chunk_id"]): chunk for chunk in mapping.get("chunks", [])},
        "locations": locations,
        "animations_by_chunk": animations_by_chunk,
        "animations_by_location": animations_by_location,
    }
    # The mapping is an in-memory JSON dict obtained from a material or mesh.
    # Keeping this runtime-only cache on it avoids a global lifetime cache and
    # is never written back to the .blend metadata.
    mapping[cache_key] = cached
    return cached


def extract_face_texture_info(
    mesh: bpy.types.Mesh,
    poly_idx: int,
    slot_mat: bpy.types.Material | None,
    atlas_mapping: dict | None = None,
) -> tuple[str, list[str], dict | None]:
    """
    Extract the source (namespace, candidate_keys_list, atlas_location_or_None) for a specific polygon.
    Handles Standalone materials, Atlas Chunk materials, Unified Atlas materials, and Generic materials.
    """
    if not slot_mat:
        return DEFAULT_NAMESPACE, [], None

    # FACE provenance is the authoritative identity across Standalone and
    # Atlas. It survives material-slot consolidation and must win over
    # mutable UV coordinates or material names.
    provenance = None
    source_attr = mesh.attributes.get(ATTR_SOURCE_TEXTURE_KEY)
    if (
        source_attr
        and source_attr.domain == "FACE"
        and source_attr.data_type == "STRING"
        and poly_idx < len(source_attr.data)
    ):
        raw_key = source_attr.data[poly_idx].value
        if isinstance(raw_key, bytes):
            raw_key = raw_key.decode("utf-8", errors="replace")
        namespace, texture_name = split_texture_key(raw_key)
        if texture_name:
            provenance = (namespace, [texture_name])

    mat_mode = detect_material_mode(slot_mat)
    if mat_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED"):
        mapping = atlas_mapping or get_atlas_mapping_from_material(slot_mat)
        if mapping:
            chunk_attr = mesh.attributes.get(ATTR_ATLAS_CHUNK_ID) or mesh.attributes.get("atlas_chunk_id")
            tex_attr = mesh.attributes.get(ATTR_ATLAS_TEXTURE_ID) or mesh.attributes.get("atlas_texture_id")

            chunk_id = None
            texture_id = None
            if chunk_attr and poly_idx < len(chunk_attr.data):
                val = chunk_attr.data[poly_idx].value
                if val >= 0:
                    chunk_id = int(val)
            if tex_attr and poly_idx < len(tex_attr.data):
                val = tex_attr.data[poly_idx].value
                if val >= 0:
                    texture_id = int(val)

            if chunk_id is None and "mtk:atlas_chunk_id" in slot_mat:
                chunk_id = int(slot_mat["mtk:atlas_chunk_id"])

            index = _atlas_mapping_index(mapping)
            current_chunk = index["chunks"].get(chunk_id) if chunk_id is not None else None

            # Fallback: calculate from UV if texture_id is missing or attribute was lost
            if texture_id is None and current_chunk is not None:
                uv_layer = mesh.uv_layers.active_render or mesh.uv_layers.active
                if uv_layer and poly_idx < len(mesh.polygons):
                    poly = mesh.polygons[poly_idx]
                    if poly.loop_indices:
                        u_coords = [uv_layer.data[li].uv.x for li in poly.loop_indices]
                        v_coords = [uv_layer.data[li].uv.y for li in poly.loop_indices]
                        u_center = sum(u_coords) / len(u_coords)
                        v_center = sum(v_coords) / len(v_coords)
                        anims_in_chunk = index["animations_by_chunk"].get(chunk_id, [])
                        texture_id = find_texture_id_from_atlas_uv(u_center, v_center, current_chunk, anims_in_chunk)

            # Find matching texture in mapping
            if chunk_id is not None and texture_id is not None:
                mapped = index["locations"].get((chunk_id, texture_id))
                if mapped:
                    tex_name, loc = mapped
                    namespace, texture_name = split_texture_key(loc.get("texture_key", tex_name))
                    return (*provenance, loc) if provenance else (namespace, [texture_name], loc)

                anim = index["animations_by_location"].get((chunk_id, texture_id))
                if anim:
                    loc = mapping.get("textures", {}).get(anim["name"])
                    namespace, texture_name = split_texture_key((loc or anim).get("texture_key", anim["name"]))
                    return (*provenance, loc or anim) if provenance else (namespace, [texture_name], loc or anim)

    if provenance:
        return *provenance, None

    # Standalone or Generic fallback
    namespace, candidates = extract_material_texture_keys(slot_mat)
    return namespace, candidates, None

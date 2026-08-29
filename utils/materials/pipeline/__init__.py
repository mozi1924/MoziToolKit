"""
Mesh face material session, attribute management, provenance tracking, and UV pipelines.
"""

from .provenance import (
    without_blender_suffix,
    canonical_texture_key,
    split_texture_key,
    detect_material_mode,
    is_mozi_material,
    get_face_source_origin,
    get_face_source_texture_key,
    get_atlas_mapping_from_material,
    get_material_atlas_dimensions,
    get_atlas_mapping_from_mesh,
    write_provenance_schema,
    write_face_source_provenance,
    get_effective_pack_hash,
    is_material_hash_valid,
)

from .mesh_attributes import (
    ensure_face_attribute,
    read_face_vector_attribute,
    read_face_float_attribute,
    read_face_string_attribute,
    read_face_tiling,
    compute_biome_tint_attributes,
    apply_biome_tint_attributes,
    cleanup_legacy_mesh_attributes,
    cleanup_object_anim_properties,
)

from .uv_pipeline import (
    remap_polygon_loop_uvs,
    remap_face_uv_to_local,
    restore_face_atlas_tiling,
    straighten_and_normalize_face_uv,
)

from .session import (
    name_replaced_material,
    find_existing_replacement,
    apply_mesh_face_materials_and_provenance,
    cleanup_unused_mtk_datablocks,
    build_material_face_cache,
    cached_face_texture_info,
    get_polygon_material_indices,
    apply_generic_procedural_atlas_material,
)

__all__ = [
    "without_blender_suffix",
    "canonical_texture_key",
    "split_texture_key",
    "detect_material_mode",
    "is_mozi_material",
    "get_face_source_origin",
    "get_face_source_texture_key",
    "get_atlas_mapping_from_material",
    "get_material_atlas_dimensions",
    "get_atlas_mapping_from_mesh",
    "write_provenance_schema",
    "write_face_source_provenance",
    "get_effective_pack_hash",
    "is_material_hash_valid",
    "ensure_face_attribute",
    "read_face_vector_attribute",
    "read_face_float_attribute",
    "read_face_string_attribute",
    "read_face_tiling",
    "compute_biome_tint_attributes",
    "apply_biome_tint_attributes",
    "cleanup_legacy_mesh_attributes",
    "cleanup_object_anim_properties",
    "remap_polygon_loop_uvs",
    "remap_face_uv_to_local",
    "restore_face_atlas_tiling",
    "straighten_and_normalize_face_uv",
    "name_replaced_material",
    "find_existing_replacement",
    "apply_mesh_face_materials_and_provenance",
    "cleanup_unused_mtk_datablocks",
    "build_material_face_cache",
    "cached_face_texture_info",
    "get_polygon_material_indices",
    "apply_generic_procedural_atlas_material",
]

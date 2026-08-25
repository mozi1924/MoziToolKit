"""
Yefira Direct Mesh world material integration.
"""

from .atlas_integration import (
    extract_atlas_parameters,
    find_active_atlas_material,
    find_all_atlas_chunk_materials,
    find_bound_atlas_material,
    get_or_create_atlas_material,
    parse_atlas_mapping,
    setup_material_slots_for_object,
    build_block_face_lut,
    build_block_face_atlas_ids,
    build_block_face_tint_lut,
    build_block_face_anim_lut,
    build_block_face_uv_rot_lut,
    build_block_face_uv_bounds_lut,
    resolve_block_state_face_locations,
)

from .yefira import (
    is_yefira_object,
    has_yefira_objects,
    refresh_baker_sources,
    parse_block_state_str,
    is_block_emissive,
)

__all__ = [
    "extract_atlas_parameters",
    "find_active_atlas_material",
    "find_all_atlas_chunk_materials",
    "find_bound_atlas_material",
    "get_or_create_atlas_material",
    "parse_atlas_mapping",
    "setup_material_slots_for_object",
    "build_block_face_lut",
    "build_block_face_atlas_ids",
    "build_block_face_tint_lut",
    "build_block_face_anim_lut",
    "build_block_face_uv_rot_lut",
    "build_block_face_uv_bounds_lut",
    "resolve_block_state_face_locations",
    "is_yefira_object",
    "has_yefira_objects",
    "refresh_baker_sources",
    "parse_block_state_str",
    "is_block_emissive",
]

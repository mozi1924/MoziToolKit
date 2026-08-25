"""
Yefira procedural point-cloud world material & Geometry Nodes integration.
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
    write_yefira_point_atlas_attributes,
    setup_yefira_point_cloud_attributes,
    notify_yefira_update,
    apply_yefira_atlas_materials,
    rebuild_or_update_yefira_material_dispatcher,
    refresh_baker_sources,
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
    "write_yefira_point_atlas_attributes",
    "setup_yefira_point_cloud_attributes",
    "notify_yefira_update",
    "apply_yefira_atlas_materials",
    "rebuild_or_update_yefira_material_dispatcher",
    "refresh_baker_sources",
]

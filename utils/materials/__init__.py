"""
Materials, resource pack indexing, and texture atlas management subpackage.
"""

from .constants import (
    DEFAULT_NAMESPACE,
    PROP_PACK_HASH,
    PROP_PACK_HASH_SHORT,
    PROP_SOURCE_NAMESPACE,
    PROP_SOURCE_TEXTURE,
    PROP_SOURCE_FILE,
    PROP_MATERIAL_ID,
    PROP_ATLAS_CHUNK_ID,
    PROP_ATLAS_CHUNK_KIND,
    PROP_ATLAS_MAPPING,
    ATTR_ATLAS_CHUNK_ID,
    ATTR_ATLAS_TEXTURE_ID,
    ATTR_FACE_MATERIAL_ID,
    ATTR_SOURCE_TEXTURE_KEY,
    ATTR_SOURCE_ORIGIN,
    PROVENANCE_SCHEMA_VERSION,
    FACE_ORDER,
    ATLAS_FORMAT_VERSION,
)

from .resource_pack import (
    ZipResourcePack,
    get_cache_dir,
    clear_resource_pack_cache,
    get_pack_hash,
    get_directory_hash,
    parse_mcmeta,
)

try:
    from .interpolation import (
        set_materials_texture_interpolation_closest,
        process_node_tree_interpolation,
    )
    from .matching import (
        detect_material_mode,
        is_mozi_material,
        get_atlas_mapping_from_material,
        extract_material_texture_keys,
        extract_face_texture_info,
        canonical_texture_key,
        split_texture_key,
        write_face_source_provenance,
        get_face_source_origin,
        get_face_source_texture_key,
        material_source_origin,
        is_ice_cube_internal_face_material,
        is_jmc2obj_material,
        jmc2obj_texture_candidates,
        JMC2OBJ_PRESET,
        get_material_match_preset,
        normalized_image_key,
        extract_texture_provenance_from_image,
        base_texture_candidates,
        without_blender_suffix,
        get_material_animation_info,
        get_texture_info_animation_info,
    )
    from .builder import (
        load_image_texture,
        set_material_displacement_method,
        build_channel_nodes,
        rebuild_material,
    )
    from .atlas_builder import (
        build_atlas_material,
        build_atlas_chunk_materials,
    )
except ImportError:
    # Running outside Blender CLI
    pass

from .atlas_layout import (
    face_index_from_normal,
    static_cell,
    chunk_cell,
    atlas_uv_from_local,
    atlas_uv_from_rect,
    local_uv_from_atlas,
    local_uv_from_rect,
    find_texture_id_from_atlas_uv,
)

from .atlas_generator import AtlasGenerator

__all__ = [
    # Constants
    "DEFAULT_NAMESPACE",
    "PROP_PACK_HASH",
    "PROP_PACK_HASH_SHORT",
    "PROP_SOURCE_NAMESPACE",
    "PROP_SOURCE_TEXTURE",
    "PROP_SOURCE_FILE",
    "PROP_MATERIAL_ID",
    "PROP_ATLAS_CHUNK_ID",
    "PROP_ATLAS_CHUNK_KIND",
    "PROP_ATLAS_MAPPING",
    "ATTR_ATLAS_CHUNK_ID",
    "ATTR_ATLAS_TEXTURE_ID",
    "ATTR_FACE_MATERIAL_ID",
    "ATTR_SOURCE_TEXTURE_KEY",
    "ATTR_SOURCE_ORIGIN",
    "PROVENANCE_SCHEMA_VERSION",
    "FACE_ORDER",
    "ATLAS_FORMAT_VERSION",

    # Resource Pack
    "ZipResourcePack",
    "get_cache_dir",
    "clear_resource_pack_cache",
    "get_pack_hash",
    "get_directory_hash",
    "parse_mcmeta",

    # Interpolation
    "set_materials_texture_interpolation_closest",
    "process_node_tree_interpolation",

    # Matching
    "detect_material_mode",
    "is_mozi_material",
    "get_atlas_mapping_from_material",
    "extract_material_texture_keys",
    "extract_face_texture_info",
    "canonical_texture_key",
    "split_texture_key",
    "write_face_source_provenance",
    "get_face_source_origin",
    "get_face_source_texture_key",
    "material_source_origin",
    "is_ice_cube_internal_face_material",
    "is_jmc2obj_material",
    "jmc2obj_texture_candidates",
    "JMC2OBJ_PRESET",
    "get_material_match_preset",
    "normalized_image_key",
    "without_blender_suffix",
    "get_material_animation_info",
    "get_texture_info_animation_info",

    # Builder
    "load_image_texture",
    "set_material_displacement_method",
    "build_channel_nodes",
    "rebuild_material",

    # Atlas Layout
    "face_index_from_normal",
    "static_cell",
    "chunk_cell",
    "atlas_uv_from_local",
    "atlas_uv_from_rect",
    "local_uv_from_atlas",
    "local_uv_from_rect",
    "find_texture_id_from_atlas_uv",

    # Atlas Generator & Builder
    "AtlasGenerator",
    "build_atlas_material",
    "build_atlas_chunk_materials",
]

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
    ATTR_UV_ROTATION,
    ATTR_UV_TILING_SCALE,
    ATTR_UV_TILING_LOCATION,
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

from .provenance import (
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

from .animation import (
    get_material_animation_info,
    get_texture_info_animation_info,
)

from .texture_finder import (
    find_albedo_image_from_material,
    find_face_image,
    get_material_pixel_step,
)

try:
    from .interpolation import (
        set_materials_texture_interpolation_closest,
        process_node_tree_interpolation,
    )
    from .matching import (
        ImporterAdapter,
        MaterialMatchPreset,
        ICE_CUBE_ADAPTER,
        JMC2OBJ_ADAPTER,
        GENERIC_ADAPTER,
        ADAPTERS,
        ICE_CUBE_PRESET,
        JMC2OBJ_PRESET,
        GENERIC_PRESET,
        MATCH_PRESETS,
        get_importer_adapter,
        get_material_match_preset,
        material_source_origin,
        extract_material_texture_keys,
        extract_face_texture_info,
        is_ice_cube_material,
        is_ice_cube_internal_face_material,
        ice_cube_texture_candidates,
        ice_cube_name_aliases,
        ice_cube_legacy_aliases,
        is_jmc2obj_material,
        jmc2obj_texture_candidates,
        generic_texture_candidates,
        base_texture_candidates,
        normalized_image_key,
        extract_texture_provenance_from_image,
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
    remap_uv_to_local,
    remap_local_to_target_uv,
    remap_uv_coordinate,
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
    "ATTR_UV_ROTATION",
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

    # Provenance
    "without_blender_suffix",
    "canonical_texture_key",
    "split_texture_key",
    "detect_material_mode",
    "is_mozi_material",
    "get_face_source_origin",
    "get_face_source_texture_key",
    "get_atlas_mapping_from_material",
    "write_face_source_provenance",

    # Animation
    "get_material_animation_info",
    "get_texture_info_animation_info",

    # Texture Finder
    "find_albedo_image_from_material",
    "find_face_image",
    "get_material_pixel_step",

    # Interpolation
    "set_materials_texture_interpolation_closest",
    "process_node_tree_interpolation",

    # Matching & Importers
    "ImporterAdapter",
    "MaterialMatchPreset",
    "ICE_CUBE_ADAPTER",
    "JMC2OBJ_ADAPTER",
    "GENERIC_ADAPTER",
    "ADAPTERS",
    "ICE_CUBE_PRESET",
    "JMC2OBJ_PRESET",
    "GENERIC_PRESET",
    "MATCH_PRESETS",
    "get_importer_adapter",
    "get_material_match_preset",
    "material_source_origin",
    "extract_material_texture_keys",
    "extract_face_texture_info",
    "is_ice_cube_material",
    "is_ice_cube_internal_face_material",
    "ice_cube_texture_candidates",
    "ice_cube_name_aliases",
    "ice_cube_legacy_aliases",
    "is_jmc2obj_material",
    "jmc2obj_texture_candidates",
    "generic_texture_candidates",
    "base_texture_candidates",
    "normalized_image_key",
    "extract_texture_provenance_from_image",

    # Builder
    "load_image_texture",
    "set_material_displacement_method",
    "build_channel_nodes",
    "rebuild_material",

    # Atlas Layout & Remapping
    "face_index_from_normal",
    "static_cell",
    "chunk_cell",
    "atlas_uv_from_local",
    "atlas_uv_from_rect",
    "local_uv_from_atlas",
    "local_uv_from_rect",
    "find_texture_id_from_atlas_uv",
    "remap_uv_to_local",
    "remap_local_to_target_uv",
    "remap_uv_coordinate",

    # Atlas UV tiling attributes
    "ATTR_UV_TILING_SCALE",
    "ATTR_UV_TILING_LOCATION",

    # Atlas Generator & Builder
    "AtlasGenerator",
    "build_atlas_material",
    "build_atlas_chunk_materials",
]

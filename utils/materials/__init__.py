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
    PROP_ATLAS_CHUNK_CATEGORY,
    PROP_ATLAS_MAPPING,
    PROP_ATLAS_WIDTH,
    PROP_ATLAS_HEIGHT,
    PROP_TILE_SIZE,
    PROP_TILES_PER_ROW,
    PROP_CREATED_BY,
    PROP_PROVENANCE_SCHEMA_VERSION,
    ATLAS_CATEGORY_BLOCKS,
    ATLAS_CATEGORY_ITEMS,
    ATLAS_CATEGORY_PARTICLES,
    ATLAS_CATEGORY_PAINTINGS,
    ATLAS_CATEGORY_ARMOR_TRIMS,
    ATLAS_CATEGORY_CHEST,
    ATLAS_CATEGORY_SHULKER_BOXES,
    ATLAS_CATEGORY_SHIELD_PATTERNS,
    ATLAS_CATEGORY_BANNER_PATTERNS,
    ATLAS_CATEGORY_DECORATED_POT,
    ATLAS_CATEGORY_CELESTIALS,
    ATLAS_CATEGORY_GUI,
    ATLAS_CATEGORY_MAP_DECORATIONS,
    ATLAS_CATEGORY_ENTITIES,
    ATLAS_CATEGORY_MISC,
    ATLAS_CATEGORY_PRIORITY,
    RECT_PACKED_CATEGORIES,
    classify_texture_category,
    ATTR_ATLAS_CHUNK_ID,
    ATTR_ATLAS_TEXTURE_ID,
    ATTR_FACE_MATERIAL_ID,
    ATTR_IS_OPAQUE,
    ATTR_ALPHA_MODE,
    ATTR_SOURCE_TEXTURE_KEY,
    ATTR_SOURCE_ORIGIN,
    ATTR_UV_ROTATION,
    ATTR_UV_TILING_SCALE,
    ATTR_UV_TILING_LOCATION,
    ATTR_UV_TILING_TRANSFORM,
    ATTR_BIOME_TINT_DATA,
    ATTR_BIOME_TINT_COLOR,
    ATTR_ANIM_TIMING,
    ATTR_ANIM_FRAME_SIZE,
    ATTR_TINT_WEIGHT,
    ATTR_BASE_TINT_WEIGHT,
    ATTR_OVERLAY_TINT_WEIGHT,
    ATTR_TINT_COLOR,
    ATTR_TINT_TYPE,
    ATTR_HARDCODED_COLOR,
    ATTR_USE_HARDCODED,
    ATTR_BIOME_TEMPERATURE,
    ATTR_BIOME_HUMIDITY,
    PROP_HAS_OVERLAY,
    PROP_OVERLAY_TEXTURE,
    PROP_TINT_CATEGORY,
    PROVENANCE_SCHEMA_VERSION,
    FACE_ORDER,
    ATLAS_FORMAT_VERSION,
    ANIM_AND_ATLAS_ATTR_NAMES,
    LEGACY_SPLIT_ATTR_NAMES,
)

from .biome import (
    hex_to_rgb,
    srgb_to_linear,
    hex_to_linear_rgb,
    hex_to_rgba,
    hex_to_linear_rgba,
    linear_to_srgb,
    linear_rgba_to_hex,
    BIOME_PALETTES,
    HARDCODED_BLOCK_TINTS,
    KNOWN_OVERLAY_PAIRS,
    TINT_TYPE_NONE,
    TINT_TYPE_GRASS,
    TINT_TYPE_FOLIAGE,
    TINT_TYPE_WATER,
    TINT_TYPE_HARDCODED,
    BiomeResolver,
    get_biome_colors,
    classify_tint_category,
)

from .resource_pack import (
    ZipResourcePack,
    get_cache_dir,
    clear_resource_pack_cache,
    get_pack_hash,
    get_directory_hash,
    parse_mcmeta,
    derive_texture_name,
)

from .pack_stack import (
    ResourcePackStack,
    get_configured_pack_stack,
    get_pack_stack_fingerprint,
)

from .rect_packer import (
    PackedRect,
    MaxRectsBinPack,
    pack_category_textures,
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
    get_material_atlas_dimensions,
    get_atlas_mapping_from_mesh,
    write_provenance_schema,
    write_face_source_provenance,
)

from .mineways_atlas import (
    MINEWAYS_TILES_TABLE,
    is_mineways_atlas_image,
    find_mineways_atlas_image,
    is_mineways_atlas_material,
    decode_mineways_face_uv,
    remap_mineways_atlas_uv_to_local,
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
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

if HAS_BPY:
    from .interpolation import (
        set_materials_texture_interpolation_closest,
        process_node_tree_interpolation,
    )
    from .matching import (
        ImporterAdapter,
        MaterialMatchPreset,
        ICE_CUBE_ADAPTER,
        JMC2OBJ_ADAPTER,
        MINEWAYS_ADAPTER,
        GENERIC_ADAPTER,
        ADAPTERS,
        ICE_CUBE_PRESET,
        JMC2OBJ_PRESET,
        MINEWAYS_PRESET,
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
        is_mineways_material,
        mineways_texture_candidates,
        generic_texture_candidates,
        base_texture_candidates,
        normalized_image_key,
        extract_texture_provenance_from_image,
        ICE_CUBE_STATIC_ASSET_UUID_ALIASES,
    )
    from .builder import (
        load_image_texture,
        set_material_displacement_method,
        build_channel_nodes,
        rebuild_material,
        inspect_material_nodes,
    )
    from .atlas_builder import (
        build_atlas_material,
        build_atlas_chunk_materials,
    )
    from .yefira import (
        is_yefira_object,
        has_yefira_objects,
        write_yefira_point_atlas_attributes,
        setup_yefira_point_cloud_attributes,
        notify_yefira_update,
        apply_yefira_atlas_materials,
        extract_atlas_parameters,
        find_bound_atlas_material,
        find_all_atlas_chunk_materials,
        get_or_create_atlas_material,
        setup_material_slots_for_object,
    )


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

from .standalone_aligner import (
    align_standalone_textures,
    is_channel_animated,
)

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
    "PROP_ATLAS_CHUNK_CATEGORY",
    "PROP_ATLAS_MAPPING",
    "PROP_CREATED_BY",
    "PROP_PROVENANCE_SCHEMA_VERSION",
    "ATLAS_CATEGORY_BLOCKS",
    "ATLAS_CATEGORY_ITEMS",
    "ATLAS_CATEGORY_PARTICLES",
    "ATLAS_CATEGORY_PAINTINGS",
    "ATLAS_CATEGORY_ARMOR_TRIMS",
    "ATLAS_CATEGORY_CHEST",
    "ATLAS_CATEGORY_SHULKER_BOXES",
    "ATLAS_CATEGORY_SHIELD_PATTERNS",
    "ATLAS_CATEGORY_BANNER_PATTERNS",
    "ATLAS_CATEGORY_DECORATED_POT",
    "ATLAS_CATEGORY_CELESTIALS",
    "ATLAS_CATEGORY_GUI",
    "ATLAS_CATEGORY_MAP_DECORATIONS",
    "ATLAS_CATEGORY_ENTITIES",
    "ATLAS_CATEGORY_MISC",
    "ATLAS_CATEGORY_PRIORITY",
    "RECT_PACKED_CATEGORIES",
    "classify_texture_category",
    "ATTR_ATLAS_CHUNK_ID",
    "ATTR_ATLAS_TEXTURE_ID",
    "ATTR_FACE_MATERIAL_ID",
    "ATTR_IS_OPAQUE",
    "ATTR_ALPHA_MODE",
    "ATTR_SOURCE_TEXTURE_KEY",
    "ATTR_SOURCE_ORIGIN",
    "ATTR_UV_ROTATION",
    "PROVENANCE_SCHEMA_VERSION",
    "FACE_ORDER",
    "ATLAS_FORMAT_VERSION",

    # 2D Bin Packing
    "PackedRect",
    "MaxRectsBinPack",
    "pack_category_textures",

    # Resource Pack
    "ZipResourcePack",
    "ResourcePackStack",
    "get_configured_pack_stack",
    "get_pack_stack_fingerprint",
    "get_cache_dir",
    "clear_resource_pack_cache",
    "get_pack_hash",
    "get_directory_hash",
    "parse_mcmeta",
    "derive_texture_name",

    # Provenance
    "without_blender_suffix",
    "canonical_texture_key",
    "split_texture_key",
    "detect_material_mode",
    "is_mozi_material",
    "get_face_source_origin",
    "get_face_source_texture_key",
    "get_atlas_mapping_from_material",
    "get_atlas_mapping_from_mesh",
    "write_provenance_schema",
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
    "MINEWAYS_ADAPTER",
    "GENERIC_ADAPTER",
    "ADAPTERS",
    "ICE_CUBE_PRESET",
    "JMC2OBJ_PRESET",
    "MINEWAYS_PRESET",
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
    "is_mineways_material",
    "mineways_texture_candidates",
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
    "ATTR_UV_TILING_TRANSFORM",

    # Atlas Generator & Builder
    "AtlasGenerator",
    "build_atlas_material",
    "build_atlas_chunk_materials",

    # Biome & Tint
    "ATTR_TINT_WEIGHT",
    "ATTR_BIOME_TINT_DATA",
    "ATTR_BIOME_TINT_COLOR",
    "ATTR_BASE_TINT_WEIGHT",
    "ATTR_OVERLAY_TINT_WEIGHT",
    "ATTR_TINT_COLOR",
    "ATTR_TINT_TYPE",
    "ATTR_HARDCODED_COLOR",
    "ATTR_USE_HARDCODED",
    "ATTR_ANIM_TIMING",
    "ATTR_ANIM_FRAME_SIZE",
    "ATTR_BIOME_TEMPERATURE",
    "ATTR_BIOME_HUMIDITY",
    "PROP_HAS_OVERLAY",
    "PROP_OVERLAY_TEXTURE",
    "PROP_TINT_CATEGORY",
    "hex_to_rgb",
    "srgb_to_linear",
    "hex_to_linear_rgb",
    "hex_to_rgba",
    "hex_to_linear_rgba",
    "BIOME_PALETTES",
    "HARDCODED_BLOCK_TINTS",
    "KNOWN_OVERLAY_PAIRS",
    "TINT_TYPE_NONE",
    "TINT_TYPE_GRASS",
    "TINT_TYPE_FOLIAGE",
    "TINT_TYPE_WATER",
    "TINT_TYPE_HARDCODED",
    "BiomeResolver",
    "get_biome_colors",
    # Standalone Alignment
    "align_standalone_textures",
    "is_channel_animated",

    # Yefira Integration
    "is_yefira_object",
    "has_yefira_objects",
    "write_yefira_point_atlas_attributes",
    "setup_yefira_point_cloud_attributes",
    "notify_yefira_update",
    "apply_yefira_atlas_materials",
    "extract_atlas_parameters",
    "find_bound_atlas_material",
    "find_all_atlas_chunk_materials",
    "get_or_create_atlas_material",
    "setup_material_slots_for_object",
]

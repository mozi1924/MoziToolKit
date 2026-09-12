"""
Materials, resource pack indexing, and texture atlas management subpackage.
Organized into focused subpackages:
- pack: Resource Pack extraction, stacking, caching, and animation timing
- atlas: Texture Atlas bin packing, layout math, generation, and chunk builder
- standalone: Standalone per-texture material generator and channel aligner
- biome: Biome palettes, hardcoded tints, and color space conversion
- nodes: Shader node tree building, PBR channel wiring, and interpolation
- matching: Importer format adapters and texture identification
- pipeline: Mesh face provenance, attributes, and UV pipelines
- yefira: Procedural point-cloud world integration and Geometry Nodes binding
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
    PROP_ENABLE_UV_TILING,
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
    FALLBACK_TEXTURE_KEY,
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
    ATTR_COLORMAP_UV,
    ATTR_BIOME_COORDS,
    PROP_HAS_OVERLAY,
    PROP_OVERLAY_TEXTURE,
    PROP_TINT_CATEGORY,
    PROVENANCE_SCHEMA_VERSION,
    FACE_ORDER,
    ATLAS_FORMAT_VERSION,
    ANIM_AND_ATLAS_ATTR_NAMES,
    LEGACY_SPLIT_ATTR_NAMES,
    BLOCK_TO_TEXTURE_ALIASES,
    is_scene_blacklisted,
    SCENE_BLACKLIST_CATEGORIES,
    SCENE_BLACKLIST_PREFIXES,
    LIVING_MOB_ENTITY_PREFIXES,
    ALLOWED_SCENE_ENTITY_PREFIXES,
)

from .catalog import (
    VANILLA_STATIC_EMISSION_LEVELS,
    VANILLA_THIN_WALL_EXACT_BLOCKS,
    VANILLA_THIN_WALL_KEYWORDS,
    get_block_emission_strength,
    is_thin_wall_block,
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
    BIOME_ENUM_ITEMS,
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
    is_mtk_object,
    detect_object_material_mode,
    update_object_biome,
)

from .pack import (
    ZipResourcePack,
    get_cache_dir,
    get_temp_extraction_dir,
    clean_obsolete_stack_caches,
    get_cache_stats,
    is_material_cache_ready,
    invalidate_material_cache_ready,
    clear_temp_extraction_cache,
    clear_baked_stack_cache,
    clear_resource_pack_cache,
    get_pack_hash,
    get_directory_hash,
    parse_mcmeta,
    derive_texture_name,
    texture_category_priority,
    ResourcePackStack,
    get_configured_pack_stack,
    get_pack_stack_fingerprint,
    get_material_animation_info,
    get_texture_info_animation_info,
)

from .atlas import (
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
    AtlasGenerator,
    build_atlas_material,
    build_atlas_chunk_materials,
    AtlasReplacementEngine,
    AtlasAddressResolver,
    ResolvedAtlasAddress,
)

from .standalone import (
    STANDALONE_FORMAT_VERSION,
    StandaloneReplacementEngine,
)

from .models import (
    ChannelDescriptor,
    StandaloneMaterialDescriptor,
    AtlasChunkDescriptor,
)

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

if HAS_BPY:
    from .nodes import (
        load_image_texture,
        set_material_displacement_method,
        build_channel_nodes,
        build_material_from_descriptor,
        rebuild_material,
        inspect_material_nodes,
        repair_material_nodes,
        set_materials_texture_interpolation_closest,
        process_node_tree_interpolation,
    )
    from .pipeline import (
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
        ensure_face_attribute,
        read_face_vector_attribute,
        read_face_float_attribute,
        read_face_string_attribute,
        read_face_tiling,
        compute_biome_tint_attributes,
        apply_biome_tint_attributes,
        cleanup_legacy_mesh_attributes,
        cleanup_object_anim_properties,
        remap_polygon_loop_uvs,
        remap_face_uv_to_local,
        restore_face_atlas_tiling,
        straighten_and_normalize_face_uv,
        name_replaced_material,
        find_existing_replacement,
        apply_mesh_face_materials_and_provenance,
        cleanup_unused_mtk_datablocks,
        build_material_face_cache,
        cached_face_texture_info,
        get_polygon_material_indices,
        apply_generic_procedural_atlas_material,
    )

    from .yefira import (
        is_yefira_object,
        has_yefira_objects,
        extract_atlas_parameters,
        find_bound_atlas_material,
        find_all_atlas_chunk_materials,
        get_or_create_atlas_material,
        setup_material_slots_for_object,
        find_active_atlas_material,
        parse_atlas_mapping,
        build_block_face_lut,
        build_block_face_atlas_ids,
        build_block_face_tint_lut,
        build_block_face_anim_lut,
        build_block_face_uv_rot_lut,
        build_block_face_uv_bounds_lut,
        resolve_block_state_face_locations,
        refresh_baker_sources,
    )
else:
    # Safe fallbacks when imported without Blender/bpy
    load_image_texture = None
    set_material_displacement_method = None
    build_channel_nodes = None
    build_material_from_descriptor = None
    rebuild_material = None
    inspect_material_nodes = None
    repair_material_nodes = None
    set_materials_texture_interpolation_closest = None
    process_node_tree_interpolation = None

    # Pipeline pure python functions can be directly imported from .pipeline.provenance
    from .pipeline.provenance import (
        without_blender_suffix,
        canonical_texture_key,
        split_texture_key,
        detect_material_mode,
        is_mozi_material,
        get_effective_pack_hash,
        is_material_hash_valid,
    )
    get_face_source_origin = None
    get_face_source_texture_key = None
    get_atlas_mapping_from_material = None
    get_material_atlas_dimensions = None
    get_atlas_mapping_from_mesh = None
    write_provenance_schema = None
    write_face_source_provenance = None
    ensure_face_attribute = None
    read_face_vector_attribute = None
    read_face_float_attribute = None
    read_face_string_attribute = None
    read_face_tiling = None
    compute_biome_tint_attributes = None
    apply_biome_tint_attributes = None
    cleanup_legacy_mesh_attributes = None
    cleanup_object_anim_properties = None
    remap_polygon_loop_uvs = None
    remap_face_uv_to_local = None
    restore_face_atlas_tiling = None
    straighten_and_normalize_face_uv = None
    name_replaced_material = None
    find_existing_replacement = None
    apply_mesh_face_materials_and_provenance = None
    cleanup_unused_mtk_datablocks = None
    build_material_face_cache = None
    cached_face_texture_info = None
    get_polygon_material_indices = None
    apply_generic_procedural_atlas_material = None

    is_yefira_object = None
    has_yefira_objects = None
    extract_atlas_parameters = None
    find_bound_atlas_material = None
    find_all_atlas_chunk_materials = None
    get_or_create_atlas_material = None
    setup_material_slots_for_object = None
    find_active_atlas_material = None
    parse_atlas_mapping = None
    build_block_face_lut = None
    build_block_face_atlas_ids = None
    build_block_face_tint_lut = None
    build_block_face_anim_lut = None
    build_block_face_uv_rot_lut = None
    build_block_face_uv_bounds_lut = None
    resolve_block_state_face_locations = None
    refresh_baker_sources = None

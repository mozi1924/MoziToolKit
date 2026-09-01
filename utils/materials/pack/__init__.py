"""
Resource Pack, Stack, and Animation metadata management.
"""

from .resource_pack import (
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
)

from .pack_stack import (
    ResourcePackStack,
    get_configured_pack_stack,
    get_pack_stack_fingerprint,
)

from .animation import (
    get_material_animation_info,
    get_texture_info_animation_info,
)

__all__ = [
    "ZipResourcePack",
    "get_cache_dir",
    "get_temp_extraction_dir",
    "clean_obsolete_stack_caches",
    "get_cache_stats",
    "is_material_cache_ready",
    "invalidate_material_cache_ready",
    "clear_temp_extraction_cache",
    "clear_baked_stack_cache",
    "clear_resource_pack_cache",
    "get_pack_hash",
    "get_directory_hash",
    "parse_mcmeta",
    "derive_texture_name",
    "texture_category_priority",
    "ResourcePackStack",
    "get_configured_pack_stack",
    "get_pack_stack_fingerprint",
    "get_material_animation_info",
    "get_texture_info_animation_info",
]

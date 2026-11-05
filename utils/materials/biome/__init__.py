"""
Biome palette lookup, hardcoded tint resolution, and color-space conversion.
"""

from .biome import (
    TINT_TYPE_NONE,
    TINT_TYPE_GRASS,
    TINT_TYPE_FOLIAGE,
    TINT_TYPE_WATER,
    TINT_TYPE_HARDCODED,
    TINT_TYPE_DRY_FOLIAGE,
    BiomeResolver,
    get_or_load_biome_resolver,
    get_biome_colors,
    compute_biome_tint_attributes,
    compute_biome_tint_attributes_paletted,
    apply_biome_tint_attributes,
    read_face_string_attribute,
    BIOME_ENUM_ITEMS,
)
import bpy
from .updater import (
    is_mtk_object,
    detect_object_material_mode,
    update_object_biome,
    resolve_and_apply_world_biome_tint,
    mark_world_biome,
    clear_biome_updater_cache,
)

__all__ = [
    "TINT_TYPE_NONE",
    "TINT_TYPE_GRASS",
    "TINT_TYPE_FOLIAGE",
    "TINT_TYPE_WATER",
    "TINT_TYPE_HARDCODED",
    "TINT_TYPE_DRY_FOLIAGE",
    "BiomeResolver",
    "get_biome_colors",
    "compute_biome_tint_attributes",
    "compute_biome_tint_attributes_paletted",
    "apply_biome_tint_attributes",
    "read_face_string_attribute",
    "BIOME_ENUM_ITEMS",
    "is_mtk_object",
    "detect_object_material_mode",
    "update_object_biome",
    "resolve_and_apply_world_biome_tint",
    "mark_world_biome",
    "clear_biome_updater_cache",
]

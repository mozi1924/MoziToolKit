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
    get_biome_colors,
    compute_biome_tint_attributes,
    apply_biome_tint_attributes,
    read_face_string_attribute,
    BIOME_ENUM_ITEMS,
)
try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

if HAS_BPY:
    from .updater import (
        is_mtk_object,
        detect_object_material_mode,
        update_object_biome,
    )
else:
    is_mtk_object = None
    detect_object_material_mode = None
    update_object_biome = None

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
    "apply_biome_tint_attributes",
    "read_face_string_attribute",
    "BIOME_ENUM_ITEMS",
    "is_mtk_object",
    "detect_object_material_mode",
    "update_object_biome",
]

"""
Biome palette lookup, hardcoded tint resolution, and color-space conversion.
"""

from .biome import (
    hex_to_rgb,
    srgb_to_linear,
    hex_to_linear_rgb,
    hex_to_rgba,
    hex_to_linear_rgba,
    linear_to_srgb,
    linear_rgba_to_hex,
    get_colormap_uv,
    sample_colormap_pixel,
    blend_biome_colors,
    BIOME_PALETTES,
    HARDCODED_BLOCK_TINTS,
    KNOWN_OVERLAY_PAIRS,
    TINT_TYPE_NONE,
    TINT_TYPE_GRASS,
    TINT_TYPE_FOLIAGE,
    TINT_TYPE_WATER,
    TINT_TYPE_HARDCODED,
    TINT_TYPE_DRY_FOLIAGE,
    BiomeResolver,
    get_biome_colors,
    classify_tint_category,
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
    "hex_to_rgb",
    "srgb_to_linear",
    "hex_to_linear_rgb",
    "hex_to_rgba",
    "hex_to_linear_rgba",
    "linear_to_srgb",
    "linear_rgba_to_hex",
    "get_colormap_uv",
    "sample_colormap_pixel",
    "blend_biome_colors",
    "BIOME_PALETTES",
    "BIOME_ENUM_ITEMS",
    "HARDCODED_BLOCK_TINTS",
    "KNOWN_OVERLAY_PAIRS",
    "TINT_TYPE_NONE",
    "TINT_TYPE_GRASS",
    "TINT_TYPE_FOLIAGE",
    "TINT_TYPE_WATER",
    "TINT_TYPE_HARDCODED",
    "TINT_TYPE_DRY_FOLIAGE",
    "BiomeResolver",
    "get_biome_colors",
    "classify_tint_category",
    "is_mtk_object",
    "detect_object_material_mode",
    "update_object_biome",
]

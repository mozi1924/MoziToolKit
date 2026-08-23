"""
Constants for MoziToolKit Material and Atlas System.
"""

# Default Minecraft Namespace
DEFAULT_NAMESPACE = "minecraft"

# Custom Property Keys on Materials and Images (namespaced with mtk:)
PROP_PACK_HASH = "mtk:pack_hash"
PROP_PACK_HASH_SHORT = "mtk:pack_hash_short"
PROP_SOURCE_NAMESPACE = "mtk:source_namespace"
PROP_SOURCE_TEXTURE = "mtk:source_texture"
PROP_SOURCE_FILE = "mtk:source_file"
PROP_MATERIAL_ID = "mtk:material_id"
PROP_ATLAS_CHUNK_ID = "mtk:atlas_chunk_id"
PROP_ATLAS_CHUNK_KIND = "mtk:atlas_chunk_kind"
PROP_ATLAS_CHUNK_CATEGORY = "mtk:atlas_chunk_category"
PROP_ATLAS_MAPPING = "mtk:atlas_mapping"
PROP_ATLAS_WIDTH = "mtk_atlas_width"
PROP_ATLAS_HEIGHT = "mtk_atlas_height"
PROP_TILE_SIZE = "mtk_tile_size"
PROP_TILES_PER_ROW = "mtk_tiles_per_row"
PROP_CREATED_BY = "mtk:created_by"
PROP_PROVENANCE_SCHEMA_VERSION = "mtk:provenance_schema_version"

# Atlas Categories & Priority Order (Minecraft-aligned)
ATLAS_CATEGORY_BLOCKS = "blocks"
ATLAS_CATEGORY_ITEMS = "items"
ATLAS_CATEGORY_PARTICLES = "particles"
ATLAS_CATEGORY_PAINTINGS = "paintings"
ATLAS_CATEGORY_ARMOR_TRIMS = "armor_trims"
ATLAS_CATEGORY_CHEST = "chest"
ATLAS_CATEGORY_SHULKER_BOXES = "shulker_boxes"
ATLAS_CATEGORY_SHIELD_PATTERNS = "shield_patterns"
ATLAS_CATEGORY_BANNER_PATTERNS = "banner_patterns"
ATLAS_CATEGORY_DECORATED_POT = "decorated_pot"
ATLAS_CATEGORY_CELESTIALS = "celestials"
ATLAS_CATEGORY_GUI = "gui"
ATLAS_CATEGORY_MAP_DECORATIONS = "map_decorations"
ATLAS_CATEGORY_ENTITIES = "entities"
ATLAS_CATEGORY_MISC = "misc"

ATLAS_CATEGORY_PRIORITY = (
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
)


def classify_texture_category(path_or_key: str) -> str:
    """Classify a relative texture path or resource key into its canonical Atlas category.

    Follows Minecraft's native atlas categorization hierarchy.
    """
    k = (path_or_key or "").replace("\\", "/").strip("/").lower()
    if ":" in k:
        k = k.split(":", 1)[1].strip("/")
    if "textures/" in k:
        k = k.split("textures/", 1)[1].strip("/")

    # Remove channel suffixes like _n, _s, and extension
    if k.endswith((".png", ".png.mcmeta")):
        k = k.removesuffix(".png.mcmeta").removesuffix(".png")
    if k.endswith(("_n", "_s")):
        k = k[:-2]

    # Specific multi-part entity / feature subcategories first
    if k.startswith(("entity/chest/", "chest/")):
        return ATLAS_CATEGORY_CHEST
    if k.startswith(("entity/shulker/", "shulker/", "shulker_boxes/")):
        return ATLAS_CATEGORY_SHULKER_BOXES
    if k.startswith(("entity/decorated_pot/", "decorated_pot/")):
        return ATLAS_CATEGORY_DECORATED_POT
    if k.startswith(("entity/shield/", "entity/shield_patterns/", "shield_patterns/")):
        return ATLAS_CATEGORY_SHIELD_PATTERNS
    if k.startswith(("entity/banner/", "entity/banner_patterns/", "banner_patterns/")):
        return ATLAS_CATEGORY_BANNER_PATTERNS
    if k.startswith(("trims/", "armor_trims/", "entity/trims/")):
        return ATLAS_CATEGORY_ARMOR_TRIMS
    if k.startswith(("environment/", "celestials/")):
        return ATLAS_CATEGORY_CELESTIALS
    if k.startswith(("map/", "map_decorations/")):
        return ATLAS_CATEGORY_MAP_DECORATIONS
    if k.startswith("gui/"):
        return ATLAS_CATEGORY_GUI
    if k.startswith(("particle/", "particles/")):
        return ATLAS_CATEGORY_PARTICLES
    if k.startswith(("painting/", "paintings/")):
        return ATLAS_CATEGORY_PAINTINGS

    # Primary block and item directories
    if k.startswith(("block/", "blocks/")):
        return ATLAS_CATEGORY_BLOCKS
    if k.startswith(("item/", "items/")):
        return ATLAS_CATEGORY_ITEMS

    # Other entities and armor
    if k.startswith(("entity/", "entities/", "models/armor/")):
        return ATLAS_CATEGORY_ENTITIES

    return ATLAS_CATEGORY_MISC


# Atlas Mesh Attribute Names (Namespaced with mtk_)
ATTR_ATLAS_CHUNK_ID = "mtk_atlas_chunk_id"
ATTR_ATLAS_TEXTURE_ID = "mtk_atlas_texture_id"
ATTR_FACE_MATERIAL_ID = "mtk_material_id"
ATTR_IS_OPAQUE = "mtk_is_opaque"
ATTR_ALPHA_MODE = "mtk_alpha_mode"
# Canonical source provenance.  These are FACE-domain string attributes so a
# mesh can retain one source texture identity per polygon even when several
# polygons share the same Blender material (as happens in atlas mode).
ATTR_SOURCE_TEXTURE_KEY = "mtk_source_texture_key"
ATTR_SOURCE_ORIGIN = "mtk_source_origin"
PROVENANCE_SCHEMA_VERSION = 1

# Biome & Tint Mesh Attribute Names (Namespaced with mtk_)
# GPU-facing data is intentionally packed.  EEVEE has a small per-material
# vertex-attribute budget, so one scalar attribute per tint setting quickly
# exceeds it on atlas materials.
ATTR_BIOME_TINT_DATA = "mtk_biome_tint_data"       # RGBA: base, overlay, tint, hardcoded
ATTR_BIOME_TINT_COLOR = "mtk_biome_tint_color"    # RGBA: resolved tint colour
ATTR_TINT_WEIGHT = "mtk_tint_weight"
ATTR_BASE_TINT_WEIGHT = "mtk_base_tint_weight"
ATTR_OVERLAY_TINT_WEIGHT = "mtk_overlay_tint_weight"
ATTR_TINT_COLOR = "mtk_tint_color"
ATTR_TINT_TYPE = "mtk_tint_type"
ATTR_HARDCODED_COLOR = "mtk_hardcoded_color"
ATTR_USE_HARDCODED = "mtk_use_hardcoded"
ATTR_BIOME_TEMPERATURE = "mtk_biome_temperature"
ATTR_BIOME_HUMIDITY = "mtk_biome_humidity"

# Biome & Overlay Custom Property Keys (Namespaced with mtk:)
PROP_HAS_OVERLAY = "mtk:has_overlay"
PROP_OVERLAY_TEXTURE = "mtk:overlay_texture"
PROP_TINT_CATEGORY = "mtk:tint_category"

# Animation Mesh Attribute Names (Atlas Dynamic Animation)
ATTR_ANIM_TIMING = "mtk_anim_timing"               # RGBA: frames, frametime, interpolate, frame width
ATTR_ANIM_FRAME_SIZE = "mtk_anim_frame_size"       # RG: frame width, frame height
ATTR_ANIM_TOTAL_FRAMES = "mtk_anim_total_frames"
ATTR_ANIM_FRAMETIME = "mtk_anim_frametime"
ATTR_ANIM_INTERPOLATE = "mtk_anim_interpolate"
ATTR_ANIM_FRAME_WIDTH = "mtk_anim_frame_width"
ATTR_ANIM_FRAME_HEIGHT = "mtk_anim_frame_height"

# Atlas UV Rotation Mesh Attribute (Euler Z rotation in radians)
ATTR_UV_ROTATION = "mtk_uv_rotation"
# Per-face affine UV data used by the Atlas tiling shader.  Before a source
# UV is baked into an atlas cell it is normalized to 0..1; these attributes
# reconstruct its original local coordinate (including jmc2obj merged faces).
ATTR_UV_TILING_TRANSFORM = "mtk_uv_tiling_transform"  # RGBA: scale XY, location XY
ATTR_UV_TILING_SCALE = "mtk_uv_tiling_scale"
ATTR_UV_TILING_LOCATION = "mtk_uv_tiling_location"

# Known Block Texture Suffixes
TEXTURE_SUFFIXES = (
    "_n", "_s",
    "_top", "_bottom", "_side", "_front", "_back",
    "_end", "_on", "_off", "_lit",
)

# Direction to Texture Suffix Mapping
DIRECTION_SUFFIX_MAP = {
    "+Y": ["_top", "_up", "_end"],
    "-Y": ["_bottom", "_down", "_end"],
    "+Z": ["_front", "_north", "_south", "_side"],
    "-Z": ["_back", "_south", "_north", "_side"],
    "+X": ["_side", "_east", "_west", "_right"],
    "-X": ["_side", "_west", "_east", "_left"],
}

# Standard 6-face cubic order
FACE_ORDER = ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]

# Atlas Format Version
ATLAS_FORMAT_VERSION = 11

# All Atlas & Animation Mesh Attribute Names (Current + Legacy/Transitional)
ANIM_AND_ATLAS_ATTR_NAMES = (
    ATTR_ATLAS_CHUNK_ID,
    ATTR_ATLAS_TEXTURE_ID,
    ATTR_FACE_MATERIAL_ID,
    ATTR_IS_OPAQUE,
    ATTR_UV_ROTATION,
    ATTR_UV_TILING_SCALE,
    ATTR_UV_TILING_LOCATION,
    ATTR_UV_TILING_TRANSFORM,
    ATTR_ANIM_TIMING,
    ATTR_ANIM_FRAME_SIZE,
    "atlas_chunk_id",
    "atlas_texture_id",
    "material_id",
    "mtk_uv_rotation",
    "mtk_anim_total_frames",
    "mtk_anim_frametime",
    "mtk_anim_interpolate",
    "mtk_anim_frame_width",
    "mtk_anim_frame_height",
)

# Obsolete / split stream attribute names cleaned up when compact attributes are written
LEGACY_SPLIT_ATTR_NAMES = (
    ATTR_TINT_WEIGHT,
    ATTR_BASE_TINT_WEIGHT,
    ATTR_OVERLAY_TINT_WEIGHT,
    ATTR_TINT_COLOR,
    ATTR_HARDCODED_COLOR,
    ATTR_USE_HARDCODED,
    ATTR_UV_TILING_SCALE,
    ATTR_UV_TILING_LOCATION,
    "mtk_anim_total_frames",
    "mtk_anim_frametime",
    "mtk_anim_interpolate",
    "mtk_anim_frame_width",
    "mtk_anim_frame_height",
)

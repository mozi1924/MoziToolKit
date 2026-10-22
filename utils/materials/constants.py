"""
Constants for MoziToolKit Material and Atlas System.
Authoritative block models, culling rules, and texture categorizations
are computed directly in Rust (libmtk).
"""

from ...bridge.mesh.attribute_schema import (
    ATTR_ANIM_FRAME_SIZE,
    ATTR_ANIM_TIMING,
    ATTR_ATLAS_CHUNK_ID,
    ATTR_BIOME_TINT_COLOR,
    ATTR_BIOME_TINT_DATA,
    ATTR_BLOCK_X,
    ATTR_BLOCK_Y,
    ATTR_BLOCK_Z,
    ATTR_SOURCE_TEXTURE_IDX,
    ATTR_SOURCE_TEXTURE_KEY,
    ATTR_UV_ROTATION,
    ATTR_UV_TRANSFORM,
)

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
PROP_ENABLE_UV_TILING = "mtk:enable_uv_tiling"

# Biome & Overlay Custom Property Keys (Namespaced with mtk:)
PROP_HAS_OVERLAY = "mtk:has_overlay"
PROP_OVERLAY_TEXTURE = "mtk:overlay_texture"
PROP_TINT_CATEGORY = "mtk:tint_category"

# Atlas Categories
ATLAS_CATEGORY_BLOCKS = "blocks"
ATLAS_CATEGORY_ITEMS = "items"
ATLAS_CATEGORY_ENTITIES = "entities"
ATLAS_CATEGORY_MISC = "misc"

# Mesh attribute names come from the native schema mirror (bridge/mesh/_attribute_schema_generated.py).
# Keep host-only custom-property keys here.
PROP_SOURCE_TEXTURES = "mtk_source_textures"
FALLBACK_TEXTURE_KEY = "mozi:fallback"
PROVENANCE_SCHEMA_VERSION = 2

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
ATLAS_FORMAT_VERSION = 16

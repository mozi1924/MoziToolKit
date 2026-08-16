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
PROP_ATLAS_MAPPING = "mtk:atlas_mapping"

# Atlas Mesh Attribute Names (Namespaced with mtk_)
ATTR_ATLAS_CHUNK_ID = "mtk_atlas_chunk_id"
ATTR_ATLAS_TEXTURE_ID = "mtk_atlas_texture_id"
ATTR_FACE_MATERIAL_ID = "mtk_material_id"
# Canonical source provenance.  These are FACE-domain string attributes so a
# mesh can retain one source texture identity per polygon even when several
# polygons share the same Blender material (as happens in atlas mode).
ATTR_SOURCE_TEXTURE_KEY = "mtk_source_texture_key"
ATTR_SOURCE_ORIGIN = "mtk_source_origin"
PROVENANCE_SCHEMA_VERSION = 1

# Animation Mesh Attribute Names (Atlas Dynamic Animation)
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
ATLAS_FORMAT_VERSION = 10

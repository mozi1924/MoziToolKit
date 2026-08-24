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

# Categories that naturally contain varying rectangular aspect ratios or non-square sizes
RECT_PACKED_CATEGORIES = frozenset({
    ATLAS_CATEGORY_ENTITIES,
    ATLAS_CATEGORY_PAINTINGS,
    ATLAS_CATEGORY_CHEST,
    ATLAS_CATEGORY_SHULKER_BOXES,
    ATLAS_CATEGORY_SHIELD_PATTERNS,
    ATLAS_CATEGORY_BANNER_PATTERNS,
    ATLAS_CATEGORY_DECORATED_POT,
    ATLAS_CATEGORY_ARMOR_TRIMS,
    ATLAS_CATEGORY_CELESTIALS,
    ATLAS_CATEGORY_GUI,
    ATLAS_CATEGORY_MAP_DECORATIONS,
    ATLAS_CATEGORY_MISC,
})


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

# Canonical Block name -> Texture candidate aliases mapping
BLOCK_TO_TEXTURE_ALIASES: dict[str, list[str]] = {
    "water": ["water_still", "water_flow"],
    "lava": ["lava_still", "lava_flow"],
    "magma_block": ["magma", "magma_block"],
    "fire": ["fire_0", "fire_1"],
    "soul_fire": ["soul_fire_0", "soul_fire_1"],
    "campfire": ["campfire_fire", "campfire_log", "campfire_log_lit"],
    "soul_campfire": ["soul_campfire_fire", "soul_campfire_log", "soul_campfire_log_lit"],
    "portal": ["nether_portal"],
    "nether_portal": ["nether_portal"],
    "kelp": ["kelp", "kelp_plant"],
    "kelp_plant": ["kelp_plant", "kelp"],
    "sea_pickle": ["sea_pickle"],
    "sea_lantern": ["sea_lantern"],
    "prismarine": ["prismarine"],
    "prismarine_bricks": ["prismarine_bricks"],
    "dark_prismarine": ["dark_prismarine"],
    "lantern": ["lantern"],
    "soul_lantern": ["soul_lantern"],
    "sculk_sensor": ["sculk_sensor_top", "sculk_sensor_side", "sculk_sensor_bottom"],
    "sculk_catalyst": ["sculk_catalyst_top", "sculk_catalyst_side", "sculk_catalyst_bottom"],
    "sculk_shrieker": ["sculk_shrieker_top", "sculk_shrieker_side", "sculk_shrieker_bottom"],
    "respawn_anchor": [
        "respawn_anchor_top_off", "respawn_anchor_top",
        "respawn_anchor_side0", "respawn_anchor_side1", "respawn_anchor_side2",
        "respawn_anchor_side3", "respawn_anchor_side4", "respawn_anchor_bottom"
    ],
    "smoker": ["smoker_front", "smoker_front_on", "smoker_side", "smoker_top", "smoker_bottom"],
    "furnace": ["furnace_front", "furnace_front_on", "furnace_side", "furnace_top", "furnace_bottom"],
    "blast_furnace": ["blast_furnace_front", "blast_furnace_front_on", "blast_furnace_side", "blast_furnace_top", "blast_furnace_bottom"],
    "redstone_lamp": ["redstone_lamp", "redstone_lamp_on"],
    "redstone_torch": ["redstone_torch", "redstone_torch_off"],
    "redstone_wall_torch": ["redstone_torch", "redstone_torch_off"],
    "command_block": ["command_block_front", "command_block_back", "command_block_side", "command_block_conditional"],
    "repeating_command_block": ["repeating_command_block_front", "repeating_command_block_back", "repeating_command_block_side", "repeating_command_block_conditional"],
    "chain_command_block": ["chain_command_block_front", "chain_command_block_back", "chain_command_block_side", "chain_command_block_conditional"],
    "dispenser": ["dispenser_front", "dispenser_front_vertical", "dispenser_side", "dispenser_top", "furnace_top"],
    "dropper": ["dropper_front", "dropper_front_vertical", "dropper_side", "dropper_top", "furnace_top"],
    "crafter": ["crafter_front", "crafter_front_powered", "crafter_top", "crafter_top_crafting", "crafter_top_triggered", "crafter_bottom", "crafter_side", "crafter_east", "crafter_west"],
    "observer": ["observer_front", "observer_back", "observer_top", "observer_side"],
    "piston": ["piston_top", "piston_bottom", "piston_side"],
    "sticky_piston": ["piston_top_sticky", "piston_bottom", "piston_side"],
    "barrel": ["barrel_top", "barrel_bottom", "barrel_side", "barrel_top_open"],
    "beehive": ["beehive_front", "beehive_front_honey", "beehive_side", "beehive_top", "beehive_bottom", "beehive_end"],
    "beehive_end": ["beehive_end", "beehive_top", "beehive_bottom"],
    "beehive_top": ["beehive_top", "beehive_end"],
    "bee_nest": ["bee_nest_front", "bee_nest_front_honey", "bee_nest_side", "bee_nest_top", "bee_nest_bottom", "bee_nest_end"],
    "bee_nest_end": ["bee_nest_end", "bee_nest_top", "bee_nest_bottom"],
    "bee_nest_top": ["bee_nest_top", "bee_nest_end"],
    "carved_pumpkin": ["carved_pumpkin", "pumpkin_side", "pumpkin_top"],
    "jack_o_lantern": ["jack_o_lantern", "pumpkin_side", "pumpkin_top"],
    "red_mushroom_block": ["red_mushroom_block", "mushroom_block_inside"],
    "brown_mushroom_block": ["brown_mushroom_block", "mushroom_block_inside"],
    "mushroom_stem": ["mushroom_stem", "mushroom_block_inside"],
    "grass_block": ["grass_block_top", "grass_block_side", "grass_block_snow", "grass_block_side_overlay", "dirt"],
    "podzol": ["podzol_top", "podzol_side", "grass_block_snow", "dirt"],
    "mycelium": ["mycelium_top", "mycelium_side", "grass_block_snow", "dirt"],
    "white_glazed_terracotta": ["white_glazed_terracotta"],
    "orange_glazed_terracotta": ["orange_glazed_terracotta"],
    "magenta_glazed_terracotta": ["magenta_glazed_terracotta"],
    "light_blue_glazed_terracotta": ["light_blue_glazed_terracotta"],
    "yellow_glazed_terracotta": ["yellow_glazed_terracotta"],
    "lime_glazed_terracotta": ["lime_glazed_terracotta"],
    "pink_glazed_terracotta": ["pink_glazed_terracotta"],
    "gray_glazed_terracotta": ["gray_glazed_terracotta"],
    "light_gray_glazed_terracotta": ["light_gray_glazed_terracotta"],
    "cyan_glazed_terracotta": ["cyan_glazed_terracotta"],
    "purple_glazed_terracotta": ["purple_glazed_terracotta"],
    "blue_glazed_terracotta": ["blue_glazed_terracotta"],
    "brown_glazed_terracotta": ["brown_glazed_terracotta"],
    "green_glazed_terracotta": ["green_glazed_terracotta"],
    "red_glazed_terracotta": ["red_glazed_terracotta"],
    "black_glazed_terracotta": ["black_glazed_terracotta"],
}

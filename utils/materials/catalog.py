"""
Minecraft Vanilla Block Emission & Thin Wall Catalog.
Defines canonical emission values (based on Minecraft 0..15 light levels)
and thin-wall whitelist (leaves, crops, flowers, saplings, vegetation)
derived directly from Minecraft Java Edition specifications.
"""

from __future__ import annotations
from typing import Any, Mapping, Optional


# Base block emission levels (0..15).
VANILLA_STATIC_EMISSION_LEVELS: dict[str, float] = {
    # Full bright emitters (Level 15)
    "beacon": 15.0,
    "conduit": 15.0,
    "end_gateway": 15.0,
    "end_portal": 15.0,
    "froglight": 15.0,
    "ochre_froglight": 15.0,
    "verdant_froglight": 15.0,
    "pearlescent_froglight": 15.0,
    "glowstone": 15.0,
    "jack_o_lantern": 15.0,
    "lava": 15.0,
    "sea_lantern": 15.0,
    "shroomlight": 15.0,
    "lantern": 15.0,
    "fire": 15.0,
    
    # High emitters (Level 14)
    "torch": 14.0,
    "wall_torch": 14.0,
    "end_rod": 14.0,

    # Medium-high emitters (Level 10-11)
    "soul_torch": 10.0,
    "soul_wall_torch": 10.0,
    "soul_lantern": 10.0,
    "soul_fire": 10.0,
    "crying_obsidian": 10.0,
    "nether_portal": 11.0,
    "firefly_bush": 10.0,

    # Medium emitters (Level 6-9)
    "glow_lichen": 7.0,
    "sculk_catalyst": 6.0,
    "amethyst_cluster": 5.0,
    "large_amethyst_bud": 4.0,
    "magma_block": 3.0,
    "medium_amethyst_bud": 2.0,

    # Low emitters (Level 1)
    "brewing_stand": 1.0,
    "dragon_egg": 1.0,
    "sculk_sensor": 1.0,
    "small_amethyst_bud": 1.0,
}

def _campfire_emission(props: Mapping[str, Any]) -> float:
    return 15.0 if str(props.get("lit", "true")).lower() == "true" else 0.0

def _soul_campfire_emission(props: Mapping[str, Any]) -> float:
    return 10.0 if str(props.get("lit", "true")).lower() == "true" else 0.0

def _furnace_emission(props: Mapping[str, Any]) -> float:
    return 13.0 if str(props.get("lit", "false")).lower() == "true" else 0.0

def _redstone_lamp_emission(props: Mapping[str, Any]) -> float:
    return 15.0 if str(props.get("lit", "false")).lower() == "true" else 0.0

def _redstone_torch_emission(props: Mapping[str, Any]) -> float:
    return 7.0 if str(props.get("lit", "true")).lower() == "true" else 0.0

def _redstone_ore_emission(props: Mapping[str, Any]) -> float:
    return 9.0 if str(props.get("lit", "false")).lower() == "true" else 0.0

def _copper_bulb_emission(props: Mapping[str, Any], max_val: float = 15.0) -> float:
    return max_val if str(props.get("lit", "false")).lower() == "true" else 0.0

def _candle_emission(props: Mapping[str, Any]) -> float:
    if str(props.get("lit", "false")).lower() != "true":
        return 0.0
    try:
        candles = int(props.get("candles", 1))
    except (ValueError, TypeError):
        candles = 1
    return float(candles * 3)

def _candle_cake_emission(props: Mapping[str, Any]) -> float:
    return 3.0 if str(props.get("lit", "false")).lower() == "true" else 0.0

def _sea_pickle_emission(props: Mapping[str, Any]) -> float:
    if str(props.get("waterlogged", "true")).lower() != "true":
        return 0.0
    try:
        pickles = int(props.get("pickles", 1))
    except (ValueError, TypeError):
        pickles = 1
    return float(pickles * 3 + 3)

def _respawn_anchor_emission(props: Mapping[str, Any]) -> float:
    try:
        charges = int(props.get("charges", 0))
    except (ValueError, TypeError):
        charges = 0
    mapping = {0: 0.0, 1: 3.0, 2: 7.0, 3: 11.0, 4: 15.0}
    return mapping.get(charges, 0.0)

def _cave_vines_emission(props: Mapping[str, Any]) -> float:
    return 14.0 if str(props.get("berries", "false")).lower() == "true" else 0.0

def _eyeblossom_emission(block_name: str) -> float:
    return 11.0 if "open" in block_name else 0.0

def _light_block_emission(props: Mapping[str, Any]) -> float:
    try:
        return float(props.get("level", 15))
    except (ValueError, TypeError):
        return 15.0


VANILLA_STATE_RESOLVERS = {
    "campfire": _campfire_emission,
    "soul_campfire": _soul_campfire_emission,
    "furnace": _furnace_emission,
    "blast_furnace": _furnace_emission,
    "smoker": _furnace_emission,
    "redstone_lamp": _redstone_lamp_emission,
    "redstone_torch": _redstone_torch_emission,
    "redstone_wall_torch": _redstone_torch_emission,
    "redstone_ore": _redstone_ore_emission,
    "deepslate_redstone_ore": _redstone_ore_emission,
    "copper_bulb": lambda p: _copper_bulb_emission(p, 15.0),
    "exposed_copper_bulb": lambda p: _copper_bulb_emission(p, 12.0),
    "weathered_copper_bulb": lambda p: _copper_bulb_emission(p, 8.0),
    "oxidized_copper_bulb": lambda p: _copper_bulb_emission(p, 4.0),
    "waxed_copper_bulb": lambda p: _copper_bulb_emission(p, 15.0),
    "waxed_exposed_copper_bulb": lambda p: _copper_bulb_emission(p, 12.0),
    "waxed_weathered_copper_bulb": lambda p: _copper_bulb_emission(p, 8.0),
    "waxed_oxidized_copper_bulb": lambda p: _copper_bulb_emission(p, 4.0),
    "candle": _candle_emission,
    "candle_cake": _candle_cake_emission,
    "sea_pickle": _sea_pickle_emission,
    "respawn_anchor": _respawn_anchor_emission,
    "cave_vines": _cave_vines_emission,
    "cave_vines_plant": _cave_vines_emission,
    "light": _light_block_emission,
}

NON_EMISSIVE_KEYWORDS: tuple[str, ...] = (
    "torchflower",
    "fire_coral",
    "coral",
    "banner",
    "bed",
    "wool",
    "carpet",
    "concrete",
    "terracotta",
    "stained_glass",
    "glass_pane",
    "shulker",
    "pressure_plate",
    "lightning_rod",
    "redstone_torch_off",
    "unlit",
)

EMISSIVE_TEXTURE_MAP: dict[str, float] = {
    "torch": 14.0,
    "wall_torch": 14.0,
    "soul_torch": 10.0,
    "soul_wall_torch": 10.0,
    "lantern": 15.0,
    "copper_lantern": 15.0,
    "exposed_copper_lantern": 15.0,
    "weathered_copper_lantern": 15.0,
    "oxidized_copper_lantern": 15.0,
    "waxed_copper_lantern": 15.0,
    "waxed_exposed_copper_lantern": 15.0,
    "waxed_weathered_copper_lantern": 15.0,
    "waxed_oxidized_copper_lantern": 15.0,
    "soul_lantern": 10.0,
    "glowstone": 15.0,
    "sea_lantern": 15.0,
    "shroomlight": 15.0,
    "froglight": 15.0,
    "ochre_froglight_side": 15.0,
    "ochre_froglight_top": 15.0,
    "verdant_froglight_side": 15.0,
    "verdant_froglight_top": 15.0,
    "pearlescent_froglight_side": 15.0,
    "pearlescent_froglight_top": 15.0,
    "lava": 15.0,
    "lava_still": 15.0,
    "lava_flow": 15.0,
    "fire": 15.0,
    "fire_0": 15.0,
    "fire_1": 15.0,
    "soul_fire": 10.0,
    "soul_fire_0": 10.0,
    "soul_fire_1": 10.0,
    "campfire_fire": 15.0,
    "campfire_log_lit": 15.0,
    "soul_campfire_fire": 10.0,
    "soul_campfire_log_lit": 10.0,
    "redstone_lamp_on": 15.0,
    "furnace_front_on": 13.0,
    "blast_furnace_front_on": 13.0,
    "smoker_front_on": 13.0,
    "redstone_torch": 7.0,
    "crying_obsidian": 10.0,
    "magma": 3.0,
    "cave_vines_lit": 14.0,
    "cave_vines_plant_lit": 14.0,
    "open_eyeblossom": 11.0,
    "open_eyeblossom_emissive": 11.0,
    "amethyst_cluster": 5.0,
    "beacon": 15.0,
    "conduit": 15.0,
    "copper_bulb_lit": 15.0,
    "copper_bulb_lit_powered": 15.0,
    "exposed_copper_bulb_lit": 12.0,
    "exposed_copper_bulb_lit_powered": 12.0,
    "weathered_copper_bulb_lit": 8.0,
    "weathered_copper_bulb_lit_powered": 8.0,
    "oxidized_copper_bulb_lit": 4.0,
    "oxidized_copper_bulb_lit_powered": 4.0,
    "end_rod": 14.0,
    "jack_o_lantern": 15.0,
    "nether_portal": 11.0,
}


def get_block_emission_strength(
    block_name: str,
    properties: Optional[Mapping[str, Any]] = None,
    texture_name: Optional[str] = None,
) -> float:
    clean_name = (block_name or "").lower().replace("minecraft:", "").strip()
    clean_tex = (texture_name or "").lower().replace("minecraft:", "").strip()
    if clean_tex.endswith(".png"):
        clean_tex = clean_tex[:-4]
    tex_base = clean_tex.split("/")[-1] if "/" in clean_tex else clean_tex

    # 0. Check non-emissive exclusions
    for kw in NON_EMISSIVE_KEYWORDS:
        if kw in clean_name or kw in clean_tex:
            return 0.0

    props = properties or {}

    # 1. Exact match in state resolvers first
    if clean_name in VANILLA_STATE_RESOLVERS:
        return float(VANILLA_STATE_RESOLVERS[clean_name](props))

    # 2. Candle color variants
    if "candle_cake" in clean_name:
        return _candle_cake_emission(props)
    if clean_name.endswith("_candle") or clean_name == "candle":
        return _candle_emission(props)

    # 3. Eyeblossom
    if "eyeblossom" in clean_name:
        return _eyeblossom_emission(clean_name)

    # 4. Exact static block emission
    if clean_name in VANILLA_STATIC_EMISSION_LEVELS:
        return VANILLA_STATIC_EMISSION_LEVELS[clean_name]

    # 5. Exact texture map lookup (e.g. block/torch, torch)
    if clean_tex in EMISSIVE_TEXTURE_MAP:
        return EMISSIVE_TEXTURE_MAP[clean_tex]
    if tex_base in EMISSIVE_TEXTURE_MAP:
        return EMISSIVE_TEXTURE_MAP[tex_base]

    return 0.0


VANILLA_THIN_WALL_KEYWORDS: tuple[str, ...] = (
    "leaves",
    "sapling",
    "crop",
    "flower",
    "tulip",
    "orchid",
    "daisy",
    "dandelion",
    "poppy",
    "allium",
    "bluet",
    "rose",
    "peony",
    "lilac",
    "sunflower",
    "petals",
    "wildflowers",
    "vine",
    "vines",
    "grass",
    "fern",
    "wheat",
    "carrot",
    "carrots",
    "potato",
    "potatoes",
    "beetroot",
    "beetroots",
    "sprout",
    "sprouts",
    "roots",
    "lichen",
    "moss",
    "fungus",
    "mushroom",
    "stem",
    "propagule",
    "azalea",
    "dripleaf",
    "lily_pad",
    "seagrass",
    "kelp",
    "coral",
    "coral_fan",
    "sugar_cane",
    "bamboo",
    "sweet_berry",
    "bush",
    "eyeblossom",
)

VANILLA_THIN_WALL_EXACT_BLOCKS: frozenset[str] = frozenset({
    "oak_leaves", "spruce_leaves", "birch_leaves", "jungle_leaves",
    "acacia_leaves", "dark_oak_leaves", "pale_oak_leaves",
    "mangrove_leaves", "cherry_leaves", "azalea_leaves", "flowering_azalea_leaves",

    "wheat", "carrots", "potatoes", "beetroots",
    "melon_stem", "attached_melon_stem",
    "pumpkin_stem", "attached_pumpkin_stem",
    "torchflower_crop", "pitcher_crop",
    "sweet_berry_bush", "cocoa",

    "dandelion", "poppy", "blue_orchid", "allium", "azure_bluet",
    "red_tulip", "orange_tulip", "white_tulip", "pink_tulip",
    "oxeye_daisy", "cornflower", "lily_of_the_valley", "wither_rose",
    "torchflower", "sunflower", "lilac", "rose_bush", "peony",
    "pitcher_plant", "pink_petals", "wildflowers", "cactus_flower",
    "spore_blossom", "open_eyeblossom", "closed_eyeblossom",
    "firefly_bush",

    "oak_sapling", "spruce_sapling", "birch_sapling", "jungle_sapling",
    "acacia_sapling", "dark_oak_sapling", "pale_oak_sapling",
    "cherry_sapling", "azalea", "flowering_azalea", "mangrove_propagule",

    "vine", "weeping_vines", "weeping_vines_plant",
    "twisting_vines", "twisting_vines_plant",
    "cave_vines", "cave_vines_plant",
    "glow_lichen", "hanging_roots",

    "short_grass", "tall_grass", "grass", "fern", "large_fern",
    "nether_sprouts", "crimson_roots", "warped_roots",
    "crimson_fungus", "warped_fungus",
    "brown_mushroom", "red_mushroom",
    "lily_pad", "seagrass", "tall_seagrass",
    "kelp", "kelp_plant", "sugar_cane", "bamboo",
    "big_dripleaf", "big_dripleaf_stem", "small_dripleaf",

    "tube_coral", "brain_coral", "bubble_coral", "fire_coral", "horn_coral",
    "tube_coral_fan", "brain_coral_fan", "bubble_coral_fan", "fire_coral_fan", "horn_coral_fan",
    "tube_coral_wall_fan", "brain_coral_wall_fan", "bubble_coral_wall_fan", "fire_coral_wall_fan", "horn_coral_wall_fan",
    "dead_tube_coral", "dead_brain_coral", "dead_bubble_coral", "dead_fire_coral", "dead_horn_coral",
    "dead_tube_coral_fan", "dead_brain_coral_fan", "dead_bubble_coral_fan", "dead_fire_coral_fan", "dead_horn_coral_fan",
    "dead_tube_coral_wall_fan", "dead_brain_coral_wall_fan", "dead_bubble_coral_wall_fan", "dead_fire_coral_wall_fan", "dead_horn_coral_wall_fan",
})


def is_thin_wall_block(block_name: str, texture_name: Optional[str] = None) -> bool:
    clean_name = (block_name or "").lower().replace("minecraft:", "").strip()
    clean_tex = (texture_name or "").lower().replace("minecraft:", "").replace("block/", "").strip()
    if clean_tex.endswith(".png"):
        clean_tex = clean_tex[:-4]

    if clean_name in VANILLA_THIN_WALL_EXACT_BLOCKS:
        return True
    if clean_tex in VANILLA_THIN_WALL_EXACT_BLOCKS:
        return True

    for kw in VANILLA_THIN_WALL_KEYWORDS:
        if kw in clean_name or (clean_tex and kw in clean_tex):
            if clean_name in ("moss_block", "mushroom_stem") or clean_tex in ("moss_block", "mushroom_stem"):
                return False
            return True

    return False


VANILLA_TRANSMISSION_EXACT_BLOCKS: frozenset[str] = frozenset({
    "glass", "glass_pane",
    "tinted_glass",
    "white_stained_glass", "orange_stained_glass", "magenta_stained_glass",
    "light_blue_stained_glass", "yellow_stained_glass", "lime_stained_glass",
    "pink_stained_glass", "gray_stained_glass", "light_gray_stained_glass",
    "cyan_stained_glass", "purple_stained_glass", "blue_stained_glass",
    "brown_stained_glass", "green_stained_glass", "red_stained_glass",
    "black_stained_glass",
    "white_stained_glass_pane", "orange_stained_glass_pane", "magenta_stained_glass_pane",
    "light_blue_stained_glass_pane", "yellow_stained_glass_pane", "lime_stained_glass_pane",
    "pink_stained_glass_pane", "gray_stained_glass_pane", "light_gray_stained_glass_pane",
    "cyan_stained_glass_pane", "purple_stained_glass_pane", "blue_stained_glass_pane",
    "brown_stained_glass_pane", "green_stained_glass_pane", "red_stained_glass_pane",
    "black_stained_glass_pane",
    "water", "flowing_water", "water_still", "water_flow",
    "ice", "packed_ice", "blue_ice", "frosted_ice",
    "slime_block", "slime", "honey_block", "honey",
    "beacon",
})

VANILLA_TRANSMISSION_KEYWORDS: tuple[str, ...] = (
    "glass",
    "glass_pane",
    "stained_glass",
    "tinted_glass",
    "water",
    "ice",
    "frosted_ice",
    "slime",
    "honey",
    "beacon",
)


def is_transmissive_block(block_name: str, texture_name: Optional[str] = None) -> bool:
    """Return True if the block represents a transmissive / refractive dielectric (glass, water, ice, etc.)."""
    clean_name = (block_name or "").lower().replace("minecraft:", "").strip()
    clean_tex = (texture_name or "").lower().replace("minecraft:", "").replace("block/", "").strip()
    if clean_tex.endswith(".png"):
        clean_tex = clean_tex[:-4]

    if clean_name in VANILLA_TRANSMISSION_EXACT_BLOCKS:
        return True
    if clean_tex in VANILLA_TRANSMISSION_EXACT_BLOCKS:
        return True

    for kw in VANILLA_TRANSMISSION_KEYWORDS:
        if kw in clean_name or (clean_tex and kw in clean_tex):
            # Exclude spyglass item texture or non-block keywords if applicable
            if "spyglass" in clean_name or (clean_tex and "spyglass" in clean_tex):
                return False
            return True

    return False



def get_block_transmission_weight(block_name: str, texture_name: Optional[str] = None) -> float:
    """Return transmission weight (1.0 for glass/water/ice dielectric transmission, 0.0 otherwise)."""
    return 1.0 if is_transmissive_block(block_name, texture_name=texture_name) else 0.0


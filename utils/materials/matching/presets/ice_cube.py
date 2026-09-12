"""
Ice Cube Asset Library Presets & Alias Mappings.
Pure data definitions and candidate generation routines.
"""

from __future__ import annotations

import re

# Ice Cube's entity names and 26.2 naming layout aliases
ICE_CUBE_ENTITY_ALIASES = {
    "aggressive_panda": "panda_aggressive",
    "brown_panda": "panda_brown",
    "lazy_panda": "panda_lazy",
    "playful_panda": "panda_playful",
    "weak_panda": "panda_weak",
    "worried_panda": "panda_worried",
    "white_splotched": "rabbit_white_splotched",
    "caerbannog": "rabbit_caerbannog",
    "salt": "rabbit_salt",
    "toast": "rabbit_toast",
    "elder_guardian": "guardian_elder",
    "drowned_outer": "drowned_outer_layer",
    "magma_cube": "magmacube",
    "polar_bear": "polarbear",
    "snow_fox": "fox_snow",
}

# Fixed Blender datablock UUID aliases from specific Ice Cube rig library assets
ICE_CUBE_STATIC_ASSET_UUID_ALIASES = {
    "m_48fb624d-1fe0-62f6-cbd5-9e84d4f37f7d": "entity/fish/pufferfish",
    "m_7417965d-36ac-0683-5e20-769f38e2593e": "entity/fish/pufferfish",
    "m_34375663-2091-1652-f671-bfe08576cfa2": "entity/skeleton/stray_overlay",
    "m_9ce7088c-085a-56ae-0fbf-05927c923b4b": "entity/shulker/spark",
}

ICE_CUBE_MATERIAL_NAME_ALIASES = {
    **ICE_CUBE_STATIC_ASSET_UUID_ALIASES,

    # Heads
    "creeper head": "entity/creeper/creeper",
    "dragon head": "entity/enderdragon/dragon",
    "piglin head": "entity/piglin/piglin",
    "player head": "entity/player/wide/steve",
    "skeleton head": "entity/skeleton/skeleton",
    "wither skeleton head": "entity/skeleton/wither_skeleton",
    "zombie head": "entity/zombie/zombie",
    "wither charge head": "entity/wither/wither_invulnerable",

    # Horse Body Skins
    "black horse armor": "entity/horse/horse_black",
    "brown horse armor": "entity/horse/horse_brown",
    "chestnut horse armor": "entity/horse/horse_chestnut",
    "creamy horse armor": "entity/horse/horse_creamy",
    "dark brown horse armor": "entity/horse/horse_darkbrown",
    "gray horse armor": "entity/horse/horse_gray",
    "white horse armor": "entity/horse/horse_white",

    # Cats
    "tuxedo cat": "entity/cat/cat_black",
    "british shorthair cat": "cat_british_shorthair",
    "calico cat": "cat_calico",
    "jellie cat": "cat_jellie",
    "persian cat": "cat_persian",
    "ragdoll cat": "cat_ragdoll",
    "red cat": "cat_red",
    "siamese cat": "cat_siamese",
    "tabby cat": "cat_tabby",
    "white cat": "cat_white",
    "black cat": "cat_black",

    # Axolotl & Mooshroom
    "lucy axolotl": "axolotl_lucy",
    "brown mooshroom": "mooshroom_brown",
    "mooshroom": "mooshroom_red",
    "brown mooshroom mushrooms": "block/brown_mushroom",
    "red mooshroom mushrooms": "block/red_mushroom",
    "mooshroom mushrooms": "block/red_mushroom",

    # Farm Animals & Variants
    "cold chicken": "chicken_cold",
    "warm chicken": "chicken_warm",
    "temperate cow": "cow_temperate",
    "cold cow": "cow_cold",
    "warm cow": "cow_warm",
    "temperate frog": "frog_temperate",
    "cold frog": "frog_cold",
    "warm frog": "frog_warm",
    "temperate pig": "pig_temperate",
    "cold pig": "pig_cold",
    "warm pig": "pig_warm",

    # Rabbits
    "black and white rabbit": "rabbit_white_splotched",
    "the killer bunny": "rabbit_caerbannog",
    "salt and pepper rabbit": "rabbit_salt",
    "toast rabbit": "rabbit_toast",

    # Llamas
    "creamy llama": "entity/llama/llama_creamy",
    "gray llama": "entity/llama/llama_gray",
    "white llama": "entity/llama/llama_white",
    "brown llama": "entity/llama/llama_brown",
    "llama decoration": "entity/equipment/llama_body/white",

    # Parrots
    "red parrot": "entity/parrot/parrot_red_blue",
    "jungle parrot": "entity/parrot/parrot_red_blue",
    "blue parrot": "entity/parrot/parrot_blue",
    "cyan parrot": "entity/parrot/parrot_cyan",
    "green parrot": "entity/parrot/parrot_green",
    "grey parrot": "entity/parrot/parrot_grey",

    # Fish & Mobs
    "small tropical fish": "entity/fish/tropical_a",
    "tropical fish a": "entity/fish/tropical_a",
    "large tropical fish": "entity/fish/tropical_b",
    "tropical fish b": "entity/fish/tropical_b",
    "bogged overlay": "entity/skeleton/bogged_overlay",
    "stray overlay": "entity/skeleton/stray_overlay",
    "slime outer": "entity/slime/slime",
    "chargedcreeper": "entity/creeper/creeper_armor",
    "drownedouter": "drowned_outer_layer",
    "iron golem cracked high": "entity/iron_golem/iron_golem_crackiness_high",
    "iron golem cracked low": "entity/iron_golem/iron_golem_crackiness_low",
    "iron golem cracked medium": "entity/iron_golem/iron_golem_crackiness_medium",
    "strider saddle": "entity/equipment/strider_saddle/saddle",
    "pig saddle": "entity/equipment/pig_saddle/saddle",
    "chest": "entity/chest/normal",
    "chest left": "entity/chest/normal_left",
    "chest right": "entity/chest/normal_right",
    "ender chest": "entity/chest/ender",
    "trapped chest": "entity/chest/trapped",
    "trapped chest left": "entity/chest/trapped_left",
    "trapped chest right": "entity/chest/trapped_right",
    "conduit base": "entity/conduit/base",
    "conduit cage": "entity/conduit/cage",
    "conduit wind": "entity/conduit/wind",
    "end crystal beam": "entity/end_crystal/end_crystal_beam",
    "lead knot": "entity/lead_knot",
    "shield": "entity/shield_base",
    "shield pattern": "entity/shield_base_nopattern",
    "shulker box": "entity/shulker/shulker",
    "trident": "entity/trident",
    "spyglass": "entity/spyglass",
    "bell": "entity/bell/bell_body",
    "oak boat": "entity/boat/oak",
    "raft": "entity/boat/bamboo",
    "oak hanging sign": "block/oak_hanging_sign",
    "oak sign": "block/oak_sign",
    "red bed": "block/red_bed_head_up",

    # Blocks & 26.2 Mojang Renames
    "chain_all": "block/iron_chain",
    "item_chain": "item/iron_chain",
    "chain": "block/iron_chain",
    "iron_bars_all": "block/iron_bars",
    "powered_rail_on": "block/powered_rail_on",
    "glow_lichen_glow_lichen": "block/glow_lichen",
    "water_cauldron_full_content": "block/water_still",
    "lava_cauldron_content": "block/lava_still",
    "nether_portal_ns_portal": "block/nether_portal",
    "campfire_lit_log": "block/campfire_log_lit",
    "soul_campfire_lit_log": "block/soul_campfire_log_lit",
    "campfire_fire_block/campfire_fire.png": "block/campfire_fire",
    "campfire_lit_log_block/campfire_log_lit.png": "block/campfire_log_lit",
    "soul_campfire_fire_block/soul_campfire_fire.png": "block/soul_campfire_fire",
    "soul_campfire_lit_log_block/soul_campfire_log_lit.png": "block/soul_campfire_log_lit",
    "sculk_mirrored_all": "block/sculk",
    "sculk_catalyst_bloom_side": "block/sculk_catalyst_side_bloom",
    "sculk_catalyst_bloom_top": "block/sculk_catalyst_top_bloom",
    "item_clock_00": "item/clock_00",
    "item_compass_00": "item/compass_00",
    "item_recovery_compass_00": "item/recovery_compass_00",
}


def is_ice_cube_internal_face(name: str) -> bool:
    """Return whether this material represents an internal or intentionally invisible face in Ice Cube."""
    clean = name.strip().lower()
    return (
        bool(re.fullmatch(r"internal_face_deletion(?:_[0-9]+)?", clean))
        or clean in ("dots stroke", "enchantmentglintnode")
        or clean.startswith("item_template_spawn_egg")
    )


def clean_icecube_identifier(raw: str) -> str:
    """Clean and strip Ice Cube specific prefixes and suffixes."""
    s = raw.strip().lower().replace(" ", "_")
    if s.endswith(".png") or s.endswith(".jpg"):
        s = s[:-4]
    if "." in s and s.rsplit(".", 1)[-1].isdigit():
        s = s.rsplit(".", 1)[0]

    prefixes = (
        "ice_cube_block_", "ice_cube_entity_", "ice_cube_item_",
        "icecube_block_", "icecube_entity_", "icecube_item_",
        "icecube_", "ice_cube_", "m_block_", "m_entity_", "m_item_", "m_",
    )
    for p in prefixes:
        if s.startswith(p):
            s = s[len(p):]
            break
    return s.replace("-", "_")


def expand_ice_cube_candidates(raw_name: str) -> list[str]:
    """Generate candidate texture paths for Ice Cube materials."""
    candidates = []
    clean = clean_icecube_identifier(raw_name)
    raw_lower = raw_name.strip().lower()

    # 1. Check fixed aliases
    for key in (raw_lower, clean, raw_name.strip()):
        if key in ICE_CUBE_MATERIAL_NAME_ALIASES:
            candidates.append(ICE_CUBE_MATERIAL_NAME_ALIASES[key])
        if key in ICE_CUBE_ENTITY_ALIASES:
            candidates.append(ICE_CUBE_ENTITY_ALIASES[key])

    # 2. Armor aliases
    if any(k in clean for k in ("boots", "chestplate", "helmet", "leggings")):
        for mat_type in ("diamond", "golden", "gold", "iron", "chainmail", "netherite", "leather"):
            if mat_type in clean:
                canon = "gold" if mat_type in ("gold", "golden") else mat_type
                if "leggings" in clean:
                    if "overlay" in clean:
                        candidates.extend([
                            f"entity/equipment/humanoid_leggings/{canon}_overlay",
                            f"models/armor/{canon}_layer_2_overlay",
                            f"{canon}_layer_2_overlay",
                        ])
                    else:
                        candidates.extend([
                            f"entity/equipment/humanoid_leggings/{canon}",
                            f"models/armor/{canon}_layer_2",
                            f"{canon}_layer_2",
                        ])
                else:
                    if "overlay" in clean:
                        candidates.extend([
                            f"entity/equipment/humanoid/{canon}_overlay",
                            f"models/armor/{canon}_layer_1_overlay",
                            f"{canon}_layer_1_overlay",
                        ])
                    else:
                        candidates.extend([
                            f"entity/equipment/humanoid/{canon}",
                            f"models/armor/{canon}_layer_1",
                            f"{canon}_layer_1",
                        ])
                break

    # 3. Fire aliases
    if "soul_fire" in clean:
        if any(d in clean for d in ("1", "alt1")):
            candidates.extend(["block/soul_fire_1", "soul_fire_1"])
        else:
            candidates.extend(["block/soul_fire_0", "soul_fire_0"])
    elif "fire" in clean and "campfire" not in clean:
        if any(d in clean for d in ("1", "alt1")):
            candidates.extend(["block/fire_1", "fire_1"])
        else:
            candidates.extend(["block/fire_0", "fire_0"])

    # 4. Suffix stripping
    stem = clean
    for suffix in ("_cross", "_wool", "_all", "_side", "_top", "_bottom", "_front", "_back",
                   "_end", "_inner", "_base", "_pattern", "_lit", "_candle", "_one_candle_all",
                   "_one_candle_lit_all", "_two_candles_all", "_three_candles_all", "_four_candles_all"):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
            candidates.append(stem)
            candidates.append(f"block/{stem}")
            candidates.append(f"entity/{stem}")
            candidates.append(f"item/{stem}")

    # Special handling for candle cakes
    if "candle_cake" in clean:
        if "top" in clean:
            candidates.extend(["block/cake_top", "cake_top"])
        elif "side" in clean:
            candidates.extend(["block/cake_side", "cake_side"])
        elif "bottom" in clean:
            candidates.extend(["block/cake_bottom", "cake_bottom"])
        elif "candle" in clean:
            for color in ("white", "orange", "magenta", "light_blue", "yellow", "lime",
                          "pink", "gray", "light_gray", "cyan", "purple", "blue",
                          "brown", "green", "red", "black"):
                if color in clean:
                    candidates.extend([f"block/{color}_candle", f"{color}_candle"])
                    break

    # 5. Default prefixes
    candidates.append(clean)
    candidates.append(f"block/{clean}")
    candidates.append(f"entity/{clean}")
    candidates.append(f"item/{clean}")
    if stem != clean:
        candidates.append(f"block/{stem}")
        candidates.append(f"entity/{stem}")
        candidates.append(f"item/{stem}")

    return list(dict.fromkeys(c for c in candidates if c))

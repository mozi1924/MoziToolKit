"""
jmc2obj Presets & Semantic Alias Generator.
Pure data definitions and candidate generation routines.
"""

from __future__ import annotations

import re

JMC2OBJ_BANNER_SHORT_ALIASES = {
    "pattern_base": "entity/banner/banner_base",
    "pattern_bs": "entity/banner/stripe_bottom",
    "pattern_ts": "entity/banner/stripe_top",
    "pattern_ls": "entity/banner/stripe_left",
    "pattern_rs": "entity/banner/stripe_right",
    "pattern_cs": "entity/banner/stripe_center",
    "pattern_ms": "entity/banner/stripe_middle",
    "pattern_drs": "entity/banner/stripe_downright",
    "pattern_dls": "entity/banner/stripe_downleft",
    "pattern_ss": "entity/banner/small_stripes",
    "pattern_cr": "entity/banner/cross",
    "pattern_sc": "entity/banner/straight_cross",
    "pattern_ld": "entity/banner/diagonal_left",
    "pattern_rud": "entity/banner/diagonal_right",
    "pattern_lud": "entity/banner/diagonal_up_left",
    "pattern_rd": "entity/banner/diagonal_up_right",
    "pattern_vh": "entity/banner/half_vertical",
    "pattern_vhr": "entity/banner/half_vertical_right",
    "pattern_hh": "entity/banner/half_horizontal",
    "pattern_hhb": "entity/banner/half_horizontal_bottom",
    "pattern_bl": "entity/banner/square_bottom_left",
    "pattern_br": "entity/banner/square_bottom_right",
    "pattern_tl": "entity/banner/square_top_left",
    "pattern_tr": "entity/banner/square_top_right",
    "pattern_bt": "entity/banner/triangle_bottom",
    "pattern_tt": "entity/banner/triangle_top",
    "pattern_bts": "entity/banner/triangles_bottom",
    "pattern_tts": "entity/banner/triangles_top",
    "pattern_mc": "entity/banner/circle",
    "pattern_mr": "entity/banner/rhombus",
    "pattern_bo": "entity/banner/border",
    "pattern_cbo": "entity/banner/curly_border",
    "pattern_bri": "entity/banner/bricks",
    "pattern_gra": "entity/banner/gradient",
    "pattern_gru": "entity/banner/gradient_up",
    "pattern_cre": "entity/banner/creeper",
    "pattern_sku": "entity/banner/skull",
    "pattern_flo": "entity/banner/flower",
    "pattern_moj": "entity/banner/mojang",
    "pattern_glb": "entity/banner/globe",
    "pattern_pig": "entity/banner/piglin",
    "pattern_flw": "entity/banner/flow",
    "pattern_gus": "entity/banner/guster",
}

JMC2OBJ_BIOME_SUFFIXES = (
    "-desert", "-forest", "-swamp", "-taiga", "-snow", "-ocean", "-jungle",
    "-badlands", "-savanna", "-dark_forest", "-birch_forest", "-plains",
    "-meadow", "-mangrove", "-cherry_grove", "-cold_ocean", "-warm_ocean",
    "_desert", "_forest", "_swamp", "_taiga", "_snow", "_ocean", "_jungle",
    "_badlands", "_savanna", "_dark_forest", "_birch_forest", "_plains",
    "_meadow", "_mangrove", "_cherry_grove", "_cold_ocean", "_warm_ocean",
)

MINECRAFT_COLORS = (
    "white", "orange", "magenta", "light_blue", "yellow", "lime",
    "pink", "gray", "light_gray", "cyan", "purple", "blue",
    "brown", "green", "red", "black",
)

WOOD_TYPES = (
    "oak", "spruce", "birch", "jungle", "acacia", "dark_oak",
    "mangrove", "cherry", "pale_oak", "bamboo", "crimson", "warped",
)

EXPLICIT_MATERIAL_ALIASES = {
    # Special block names
    "magma_block": ["block/magma", "block/magma_block", "magma"],
    "smooth_quartz": ["block/quartz_block_top", "block/quartz_block_side", "block/quartz_block_bottom"],
    "smooth_sandstone": ["block/sandstone_top", "block/sandstone_bottom"],
    "smooth_red_sandstone": ["block/red_sandstone_top", "block/red_sandstone_bottom"],
    "smooth_basalt": ["block/smooth_basalt", "block/basalt_side"],
    "moss_carpet": ["block/moss_block", "block/moss_carpet"],
    "hay_block": ["block/hay_block_side", "block/hay_block_top"],
    "dried_kelp_block": ["block/dried_kelp_top", "block/dried_kelp_side", "block/dried_kelp_bottom"],
    "glowstone": ["block/glowstone"],
    "sea_lantern": ["block/sea_lantern"],
    "shroomlight": ["block/shroomlight"],
    "infested_deepslate": ["block/deepslate"],
    "infested_cobblestone": ["block/cobblestone"],
    "infested_stone": ["block/stone"],
    "infested_stone_bricks": ["block/stone_bricks"],
    "infested_cracked_stone_bricks": ["block/cracked_stone_bricks"],
    "infested_mossy_stone_bricks": ["block/mossy_stone_bricks"],
    "infested_chiseled_stone_bricks": ["block/chiseled_stone_bricks"],
    "grass": ["block/short_grass", "block/grass"],
    "sculk_sensor": ["block/sculk_sensor_side", "block/sculk_sensor_top"],
    "calibrated_sculk_sensor": ["block/calibrated_sculk_sensor_side", "block/calibrated_sculk_sensor_top"],
    "chiseled_bookshelf": ["block/chiseled_bookshelf_empty", "block/chiseled_bookshelf_side"],
    "decorated_pot": ["entity/decorated_pot/decorated_pot_base", "entity/decorated_pot/base"],
    "bell": ["entity/bell/bell_body", "entity/bell/bell"],
    "conduit": ["entity/conduit/base", "entity/conduit/cage"],
    "end_portal": ["entity/end_portal"],
    "lightning_rod": ["block/lightning_rod"],
    "tripwire": ["block/tripwire"],
    "tripwire_hook": ["block/tripwire_hook"],
    "cake": ["block/cake_top", "block/cake_side", "block/cake_inner", "block/cake_bottom"],
    "suspicious_gravel": ["block/gravel", "block/suspicious_gravel_0"],
    "suspicious_sand": ["block/sand", "block/suspicious_sand_0"],
    "torchflower_crop": ["block/torchflower_crop_stage0", "block/torchflower_crop_stage1"],
    "pitcher_crop": ["block/pitcher_crop_side", "block/pitcher_crop_top"],
    "respawn_anchor": ["block/respawn_anchor_top", "block/respawn_anchor_side0"],
    "lodestone": ["block/lodestone_top", "block/lodestone_side"],
    "target": ["block/target_top", "block/target_side"],
    "crying_obsidian": ["block/crying_obsidian"],
    "ancient_debris": ["block/ancient_debris_side", "block/ancient_debris_top"],
    # Entities / Heads
    "skeleton_skull": ["entity/skeleton/skeleton"],
    "skeleton_wall_skull": ["entity/skeleton/skeleton"],
    "wither_skeleton_skull": ["entity/skeleton/wither_skeleton"],
    "wither_skeleton_wall_skull": ["entity/skeleton/wither_skeleton"],
    "zombie_head": ["entity/zombie/zombie"],
    "zombie_wall_head": ["entity/zombie/zombie"],
    "creeper_head": ["entity/creeper/creeper"],
    "creeper_wall_head": ["entity/creeper/creeper"],
    "piglin_head": ["entity/piglin/piglin"],
    "piglin_wall_head": ["entity/piglin/piglin"],
    "dragon_head": ["entity/enderdragon/dragon"],
    "dragon_wall_head": ["entity/enderdragon/dragon"],
    "player_head": ["entity/player/wide/steve"],
    "player_wall_head": ["entity/player/wide/steve"],
    # Chests
    "chest": ["entity/chest/normal", "entity/chest/chest"],
    "chest_left": ["entity/chest/normal_left", "entity/chest/normal"],
    "chest_right": ["entity/chest/normal_right", "entity/chest/normal"],
    "normal_chest": ["entity/chest/normal", "entity/chest/chest"],
    "normal_chest_left": ["entity/chest/normal_left", "entity/chest/normal"],
    "normal_chest_right": ["entity/chest/normal_right", "entity/chest/normal"],
    "normal_left": ["entity/chest/normal_left"],
    "normal_right": ["entity/chest/normal_right"],
    "double_chest_left": ["entity/chest/normal_left", "entity/chest/normal"],
    "double_chest_right": ["entity/chest/normal_right", "entity/chest/normal"],
    "trapped_chest": ["entity/chest/trapped"],
    "trapped_chest_left": ["entity/chest/trapped_left", "entity/chest/trapped"],
    "trapped_chest_right": ["entity/chest/trapped_right", "entity/chest/trapped"],
    "trapped_double_chest_left": ["entity/chest/trapped_left", "entity/chest/trapped"],
    "trapped_double_chest_right": ["entity/chest/trapped_right", "entity/chest/trapped"],
    "trapped_left": ["entity/chest/trapped_left"],
    "trapped_right": ["entity/chest/trapped_right"],
    "ender_chest": ["entity/chest/ender"],
    "copper_chest": ["entity/chest/copper"],
    "copper_chest_left": ["entity/chest/copper_left", "entity/chest/copper"],
    "copper_chest_right": ["entity/chest/copper_right", "entity/chest/copper"],
    "copper_double_chest_left": ["entity/chest/copper_left", "entity/chest/copper"],
    "copper_double_chest_right": ["entity/chest/copper_right", "entity/chest/copper"],
    "banner_standing": ["entity/banner/banner_base", "entity/banner/base"],
    "banner_wall": ["entity/banner/banner_base", "entity/banner/base"],
    "banner_base": ["entity/banner/banner_base", "entity/banner/base"],
    "banner": ["entity/banner/banner_base", "entity/banner/base"],
}


def clean_jmc2obj_identifier(raw: str) -> str:
    """Clean jmc2obj prefixes, suffixes, extensions, and biome tints."""
    s = raw.strip().lower()
    if s.endswith(".png") or s.endswith(".jpg"):
        s = s[:-4]
    if "." in s and s.rsplit(".", 1)[-1].isdigit():
        s = s.rsplit(".", 1)[0]

    prefixes = (
        "tex/minecraft/", "textures/block/", "textures/entity/", "textures/",
        "minecraft_block-", "minecraft_entity-", "minecraft_item-", "minecraft_banner-",
        "minecraft_block_", "minecraft_entity_", "minecraft_item_",
        "jmc2obj_block-", "jmc2obj_block_", "jmc2obj_entity-", "jmc2obj_item-", "jmc2obj_",
        "minecraft:", "minecraft-", "tile_", "tile-", "tile.", "block_", "block-", "block.",
    )
    for p in prefixes:
        if s.startswith(p):
            s = s[len(p):]
            break

    for suffix in JMC2OBJ_BIOME_SUFFIXES:
        if s.endswith(suffix):
            s = s[:-len(suffix)]
            break

    if "/" not in s:
        s = s.replace(" ", "_").replace("-", "_")

    return s


def expand_jmc2obj_candidates(raw_name: str) -> list[str]:
    """Generate structured candidate paths for jmc2obj material names."""
    clean = clean_jmc2obj_identifier(raw_name)
    cands: list[str] = []

    # 1. Check Banner short aliases
    for short_code, mapped_path in JMC2OBJ_BANNER_SHORT_ALIASES.items():
        if clean == short_code or clean.endswith(short_code):
            cands.append(mapped_path)
            cands.append(f"minecraft:{mapped_path}")
            return cands

    # 2. Check explicit aliases
    if clean in EXPLICIT_MATERIAL_ALIASES:
        cands.extend(EXPLICIT_MATERIAL_ALIASES[clean])

    # 3. Beds (all 16 colors)
    if "bed" in clean:
        for color in MINECRAFT_COLORS:
            if color in clean:
                cands.extend([
                    f"entity/bed/{color}",
                    f"block/{color}_bed",
                    f"block/{color}_bed_top",
                    f"block/{color}_bed_head_up",
                    f"block/{color}_bed_head",
                    f"block/{color}_bed_foot_up",
                    f"block/{color}_bed_foot",
                    f"block/{color}_bed_head_north",
                    f"block/{color}_bed_foot_south",
                    f"block/{color}_bed_head_east",
                    f"block/{color}_bed_foot_east",
                    f"bed/{color}",
                ])
                break
        else:
            cands.extend([
                "entity/bed/red",
                "block/red_bed",
                "block/red_bed_top",
                "block/red_bed_head_up",
                "block/red_bed_head",
                "block/red_bed_foot_up",
                "block/red_bed_foot",
                "block/red_bed_head_north",
                "block/red_bed_foot_south",
            ])

    # 4. Chests
    if "chest" in clean:
        if "ender" in clean:
            cands.extend(["entity/chest/ender", "entity/chest/ender_chest", "block/ender_chest"])
        elif "trapped" in clean:
            if "left" in clean:
                cands.extend(["entity/chest/trapped_left", "entity/chest/trapped"])
            elif "right" in clean:
                cands.extend(["entity/chest/trapped_right", "entity/chest/trapped"])
            else:
                cands.extend(["entity/chest/trapped", "block/trapped_chest"])
        else:
            if "left" in clean:
                cands.extend(["entity/chest/normal_left", "entity/chest/normal"])
            elif "right" in clean:
                cands.extend(["entity/chest/normal_right", "entity/chest/normal"])
            else:
                cands.extend(["entity/chest/normal", "entity/chest/chest", "block/chest_front", "block/chest_top", "block/chest_side"])

    # 5. Redstone dust/wire
    if "redstone_dust" in clean or "redstone_wire" in clean:
        cands.extend([
            "block/redstone_dust_line0",
            "block/redstone_dust_line1",
            "block/redstone_dust_dot",
            "block/redstone_dust_overlay",
        ])

    # 6. Signs & Hanging Signs (all wood types)
    if "sign" in clean:
        is_hanging = "hanging" in clean
        for wood in WOOD_TYPES:
            if wood in clean:
                if is_hanging:
                    cands.extend([
                        f"entity/signs/hanging/{wood}",
                        f"entity/signs/{wood}",
                        f"block/{wood}_hanging_sign",
                        f"block/{wood}_sign",
                        f"block/{wood}_planks",
                    ])
                else:
                    cands.extend([
                        f"entity/signs/{wood}",
                        f"block/{wood}_sign",
                        f"block/{wood}_planks",
                    ])
                break

    # 7. Shulker Boxes (all 16 colors)
    if "shulker" in clean:
        for color in MINECRAFT_COLORS:
            if color in clean:
                cands.extend([
                    f"entity/shulker/shulker_{color}",
                    f"block/{color}_shulker_box",
                    f"block/{color}_shulker_box_top",
                    f"entity/shulker/{color}",
                ])
                break
        else:
            cands.extend([
                "entity/shulker/shulker",
                "block/shulker_box",
                "block/shulker_box_top",
            ])

    # 8. Slabs, Stairs, Walls, Carpets
    for suffix in ("_slab", "_stairs", "_wall", "_carpet"):
        if clean.endswith(suffix):
            base_mat = clean[:-len(suffix)]
            cands.extend([
                f"block/{clean}",
                f"block/{base_mat}",
                f"block/{base_mat}_top",
                f"block/{base_mat}_side",
                f"block/{base_mat}_planks",
            ])
            break

    # 9. General category fallbacks
    cands.append(clean)
    cands.append(f"block/{clean}")
    cands.append(f"entity/{clean}")
    cands.append(f"item/{clean}")

    # Deduplicate while preserving order
    return list(dict.fromkeys(c for c in cands if c))

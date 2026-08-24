"""
jmc2obj format adapter, material naming conventions, and block/entity aliases.
"""

from __future__ import annotations

import re
import bpy
from .base import ImporterAdapter, base_texture_candidates, normalized_image_key
from .ice_cube import is_ice_cube_material
from ..constants import DEFAULT_NAMESPACE
from ..provenance import without_blender_suffix, is_mozi_material


JMC2OBJ_BANNER_SHORT_ALIASES = {
    "pattern_base": "entity/banner/base",
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
    "magma_block": ["block/magma", "magma"],
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
    "normal_chest": ["entity/chest/normal", "entity/chest/chest"],
    "trapped_chest": ["entity/chest/trapped"],
    "ender_chest": ["entity/chest/ender"],
    "banner_standing": ["entity/banner/banner_base", "entity/banner/base"],
    "banner_wall": ["entity/banner/banner_base", "entity/banner/base"],
}


def is_jmc2obj_material(mat: bpy.types.Material | None) -> bool:
    """Detect materials exported by jmc2obj via naming conventions, image paths, or metadata."""
    if not mat:
        return False
    if is_mozi_material(mat) or is_ice_cube_material(mat):
        return False
    if mat.get("mtk:source_importer") == "jmc2obj":
        return True

    name = without_blender_suffix(mat.name.strip().lower())
    if re.match(r"^(?:minecraft|jmc2obj)_(?:block|entity|item|banner|painting)-", name):
        return True
    if name.startswith("jmc2obj_"):
        return True
    if re.match(r"^[a-z0-9_]+_(?:block|entity|item)-[a-z0-9_\-]+", name):
        return True

    if mat.use_nodes and mat.node_tree:
        # Check node tree name
        tree_name = without_blender_suffix(mat.node_tree.name.strip().lower())
        if re.match(r"^(?:minecraft|jmc2obj)_(?:block|entity|item|banner|painting)-", tree_name):
            return True

        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE":
                if node.image:
                    fp = (node.image.filepath or node.image.name or "").replace("\\", "/").lower()
                    if "/tex/minecraft/" in fp or "tex/minecraft/" in fp or "tex/jmc2obj/" in fp:
                        return True
                    img_name = without_blender_suffix(node.image.name.lower())
                    if re.match(r"^(?:minecraft|jmc2obj)_(?:block|entity|item)-", img_name):
                        return True
                # Fallback: Check node label or custom node name for jmc2obj patterns (e.g. when image is missing/None)
                for attr_val in (node.label, node.name):
                    if attr_val:
                        clean_attr = without_blender_suffix(attr_val.strip().lower()).removesuffix(".png")
                        if re.match(r"^(?:minecraft|jmc2obj)_(?:block|entity|item)-", clean_attr):
                            return True
                        if "/tex/minecraft/" in clean_attr or clean_attr.startswith("tex/minecraft/"):
                            return True

    return False


def _expand_semantic_candidates(stem: str) -> list[str]:
    """Generate structured candidate texture keys for a normalized jmc2obj resource stem."""
    cands: list[str] = []

    # 1. Direct explicit aliases
    if stem in EXPLICIT_MATERIAL_ALIASES:
        cands.extend(EXPLICIT_MATERIAL_ALIASES[stem])
    clean_stem = stem.replace("block/", "").replace("entity/", "").replace("item/", "")
    if clean_stem in EXPLICIT_MATERIAL_ALIASES:
        cands.extend(EXPLICIT_MATERIAL_ALIASES[clean_stem])

    # 2. Beds (all 16 colors + red default)
    if "bed" in stem:
        for color in MINECRAFT_COLORS:
            if color in stem:
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
                "block/red_bed_head_east",
                "block/red_bed_foot_east",
            ])

    # 2b. Chests (all chest types and decomposed tile parts)
    if "chest" in clean_stem:
        # Determine specific chest variant
        if "ender" in clean_stem:
            cands.extend([
                "entity/chest/ender",
                "entity/chest/ender_chest",
                "block/ender_chest",
            ])
        elif "trapped" in clean_stem:
            if "left" in clean_stem:
                cands.extend(["entity/chest/trapped_left", "entity/chest/trapped"])
            elif "right" in clean_stem:
                cands.extend(["entity/chest/trapped_right", "entity/chest/trapped"])
            else:
                cands.extend(["entity/chest/trapped", "block/trapped_chest"])
        elif "exposed_copper" in clean_stem:
            if "left" in clean_stem:
                cands.extend(["entity/chest/copper_exposed_left", "entity/chest/copper_exposed"])
            elif "right" in clean_stem:
                cands.extend(["entity/chest/copper_exposed_right", "entity/chest/copper_exposed"])
            else:
                cands.extend(["entity/chest/copper_exposed", "entity/chest/copper_weathered", "block/exposed_copper_chest"])
        elif "weathered_copper" in clean_stem:
            if "left" in clean_stem:
                cands.extend(["entity/chest/copper_weathered_left", "entity/chest/copper_weathered"])
            elif "right" in clean_stem:
                cands.extend(["entity/chest/copper_weathered_right", "entity/chest/copper_weathered"])
            else:
                cands.extend(["entity/chest/copper_weathered", "block/weathered_copper_chest"])
        elif "oxidized_copper" in clean_stem:
            if "left" in clean_stem:
                cands.extend(["entity/chest/copper_oxidized_left", "entity/chest/copper_oxidized"])
            elif "right" in clean_stem:
                cands.extend(["entity/chest/copper_oxidized_right", "entity/chest/copper_oxidized"])
            else:
                cands.extend(["entity/chest/copper_oxidized", "block/oxidized_copper_chest"])
        elif "copper" in clean_stem:
            if "left" in clean_stem:
                cands.extend(["entity/chest/copper_left", "entity/chest/copper"])
            elif "right" in clean_stem:
                cands.extend(["entity/chest/copper_right", "entity/chest/copper"])
            else:
                cands.extend(["entity/chest/copper", "block/copper_chest"])
        elif "christmas" in clean_stem:
            if "left" in clean_stem:
                cands.extend(["entity/chest/christmas_left", "entity/chest/christmas"])
            elif "right" in clean_stem:
                cands.extend(["entity/chest/christmas_right", "entity/chest/christmas"])
            else:
                cands.extend(["entity/chest/christmas", "entity/chest/christmas_chest"])
        else:
            if "left" in clean_stem:
                cands.extend(["entity/chest/normal_left", "entity/chest/normal"])
            elif "right" in clean_stem:
                cands.extend(["entity/chest/normal_right", "entity/chest/normal"])
            else:
                cands.extend(["entity/chest/normal", "entity/chest/chest", "block/chest_front", "block/chest_top", "block/chest_side"])

    # 2c. Redstone Wires and Dust Variants
    if "redstone_dust" in clean_stem or "redstone_wire" in clean_stem:
        cands.extend([
            "block/redstone_dust_line0",
            "block/redstone_dust_line1",
            "block/redstone_dust_dot",
            "block/redstone_dust_overlay",
        ])

    # 2d. Shelves (All wood variants)
    if "shelf" in clean_stem:
        for wood in WOOD_TYPES:
            if wood in clean_stem:
                cands.extend([
                    f"block/{wood}_shelf",
                    f"block/{wood}_planks",
                ])
                break

    # 2e. Chains (Legacy and Modern JAR)
    if clean_stem == "chain":
        cands.extend([
            "block/chain",
            "block/iron_chain",
            "item/chain",
            "item/iron_chain",
        ])

    # 3. Signs and Hanging Signs (all wood types)
    if "sign" in stem:
        is_hanging = "hanging" in stem
        for wood in WOOD_TYPES:
            if wood in stem:
                if is_hanging:
                    cands.extend([
                        f"entity/signs/hanging/{wood}",
                        f"entity/signs/{wood}",
                        f"block/{wood}_hanging_sign",
                        f"block/{wood}_sign",
                        f"block/{wood}_planks",
                        f"block/{wood}_log",
                    ])
                else:
                    cands.extend([
                        f"entity/signs/{wood}",
                        f"block/{wood}_sign",
                        f"block/{wood}_planks",
                        f"block/{wood}_log",
                    ])
                break

    # 4. Shulker Boxes (all 16 colors + undyed)
    if "shulker" in stem:
        found_color = None
        for color in MINECRAFT_COLORS:
            if color in stem:
                found_color = color
                break
        if found_color:
            cands.extend([
                f"entity/shulker/shulker_{found_color}",
                f"block/{found_color}_shulker_box",
                f"entity/shulker/{found_color}",
            ])
        else:
            cands.extend([
                "entity/shulker/shulker",
                "block/shulker_box",
            ])

    # 5. Slabs, Stairs, Walls, Fences, Gates, Pressure Plates, Buttons
    for suffix in ("_slab", "_stairs", "_wall", "_fence_gate", "_fence", "_pressure_plate", "_button"):
        if clean_stem.endswith(suffix):
            base_b = clean_stem[:-len(suffix)]
            # e.g. dark_prismarine_slab -> dark_prismarine
            cands.extend([
                f"block/{base_b}",
                f"block/{base_b}_planks" if not base_b.endswith("_planks") else f"block/{base_b}",
                f"block/{base_b}s" if not base_b.endswith("s") else f"block/{base_b}",
                f"block/{base_b}_bricks" if not base_b.endswith("_bricks") else f"block/{base_b}",
                f"block/{base_b}_block" if not base_b.endswith("_block") else f"block/{base_b}",
                f"block/{base_b}_top",
                f"block/{base_b}_side",
            ])
            break

    # 6. Carpets
    if clean_stem.endswith("_carpet"):
        color = clean_stem[:-7]
        if color in MINECRAFT_COLORS:
            cands.extend([
                f"block/{color}_wool",
                f"block/{color}_carpet",
            ])
        elif color == "moss":
            cands.extend(["block/moss_block", "block/moss_carpet"])

    # 7. Wood / Stripped Wood / Hyphae (6-sided logs)
    if clean_stem.endswith("_wood"):
        wood_name = clean_stem[:-5]
        if wood_name.startswith("stripped_"):
            real_wood = wood_name[9:]
            cands.extend([
                f"block/stripped_{real_wood}_log",
                f"block/stripped_{real_wood}_log_top",
                f"block/stripped_{real_wood}_stem",
            ])
        else:
            cands.extend([
                f"block/{wood_name}_log",
                f"block/{wood_name}_log_top",
                f"block/{wood_name}_stem",
            ])
    elif clean_stem.endswith("_hyphae"):
        hyphae_name = clean_stem[:-7]
        if hyphae_name.startswith("stripped_"):
            real_h = hyphae_name[9:]
            cands.extend([
                f"block/stripped_{real_h}_stem",
                f"block/stripped_{real_h}_stem_top",
            ])
        else:
            cands.extend([
                f"block/{hyphae_name}_stem",
                f"block/{hyphae_name}_stem_top",
            ])

    # 8. Waxed variants
    if clean_stem.startswith("waxed_"):
        unwaxed = clean_stem[6:]
        cands.extend([
            f"block/{unwaxed}",
            unwaxed,
        ])
        # Recursively expand unwaxed base (e.g. waxed_oxidized_cut_copper_slab -> oxidized_cut_copper)
        cands.extend(_expand_semantic_candidates(unwaxed))

    # 9. Wall mounted variants
    if "_wall_" in clean_stem:
        non_wall = clean_stem.replace("_wall_", "_")
        cands.extend([f"block/{non_wall}", non_wall])
    elif clean_stem.startswith("wall_"):
        non_wall = clean_stem[5:]
        cands.extend([f"block/{non_wall}", non_wall])

    # 10. Potted variants
    if clean_stem.startswith("potted_"):
        plant = clean_stem[7:]
        cands.extend([
            f"block/{plant}",
            f"block/{plant}_plant",
            f"block/{plant}_side",
            plant,
        ])

    # 11. Cauldrons
    if "cauldron" in clean_stem:
        cands.extend([
            "block/cauldron_side",
            "block/cauldron_top",
            "block/cauldron_inner",
            "block/cauldron_bottom",
        ])

    # 12. Candle Cakes
    if "candle_cake" in clean_stem:
        cands.extend([
            "block/cake_top",
            "block/cake_side",
        ])

    # 13. General multi-face block additions
    cands.extend([
        f"block/{clean_stem}_side",
        f"block/{clean_stem}_top",
        f"block/{clean_stem}_front",
        f"block/{clean_stem}_bottom",
        f"block/{clean_stem}_base",
    ])

    return cands


def jmc2obj_texture_candidates(mat: bpy.types.Material) -> tuple[str, list[str]]:
    """Extract candidate texture keys for materials exported by jmc2obj."""
    namespace, base_cands = base_texture_candidates(mat)
    if mat.get("mtk:source_namespace"):
        return namespace, base_cands

    candidates: list[str] = []
    source_name = without_blender_suffix(mat.name.strip().lower())
    raw_names = [source_name]

    # Collect raw names from image nodes and labels as well
    if mat.use_nodes and mat.node_tree:
        tree_name = without_blender_suffix(mat.node_tree.name.strip().lower()).removesuffix(".png")
        if tree_name and not tree_name.startswith(("shader nodetree", "nodetree", "material")):
            raw_names.append(tree_name)

        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE":
                if node.image:
                    fp = (node.image.filepath or "").replace("\\", "/").strip()
                    if fp:
                        norm_fp = fp.lower()
                        if "/tex/" in norm_fp or norm_fp.startswith("tex/"):
                            idx = norm_fp.find("tex/")
                            rel_path = fp[idx + 4:]
                            if rel_path.lower().endswith(".png"):
                                rel_path = rel_path[:-4]
                            if "/" in rel_path:
                                ns, tex_path = rel_path.split("/", 1)
                                detected_ns = ns.lower()
                                if detected_ns and detected_ns not in ("tex", ""):
                                    if namespace == DEFAULT_NAMESPACE or namespace == "jmc2obj":
                                        namespace = detected_ns
                                candidates.append(tex_path)
                                if "/" in tex_path:
                                    candidates.append(tex_path.split("/", 1)[1])
                    img_key = normalized_image_key(node.image)
                    if img_key and img_key not in raw_names:
                        raw_names.append(img_key)
                # Fallback: check node label and custom node name
                for attr_val in (node.label, node.name):
                    if attr_val:
                        clean_attr = without_blender_suffix(attr_val.strip().lower()).removesuffix(".png")
                        if clean_attr and not clean_attr.startswith(("image texture", "tex_image", "atlas_chunk_")):
                            if clean_attr not in raw_names:
                                raw_names.append(clean_attr)

    for item in raw_names:
        stem = without_blender_suffix(item)
        if stem.endswith(".png"):
            stem = stem[:-4]

        # Strip leading tex/ or /tex/
        if stem.startswith("tex/"):
            stem = stem[4:]
        elif "/tex/" in stem:
            stem = stem.split("/tex/")[-1]

        cur_ns = namespace
        path_part = stem
        if "_" in stem:
            prefix, rest = stem.split("_", 1)
            if prefix in ("minecraft", "jmc2obj"):
                cur_ns = DEFAULT_NAMESPACE
                path_part = rest
            elif any(rest.startswith(f"{cat}-") for cat in ("block", "entity", "item", "banner", "painting", "particle", "gui", "environment", "colormap", "models")):
                cur_ns = prefix
                path_part = rest
                if namespace == DEFAULT_NAMESPACE and cur_ns != DEFAULT_NAMESPACE:
                    namespace = cur_ns

        # Banner aliases
        if path_part.startswith("banner-"):
            banner_sub = path_part[len("banner-"):]
            if banner_sub in JMC2OBJ_BANNER_SHORT_ALIASES:
                candidates.append(JMC2OBJ_BANNER_SHORT_ALIASES[banner_sub])

        # Redstone aliases
        if path_part.startswith("block-redstone_dust_"):
            if "dot" in path_part:
                candidates.extend(["block/redstone_dust_dot", "redstone_dust_dot"])
            elif "line" in path_part:
                candidates.extend(["block/redstone_dust_line0", "block/redstone_dust_line", "redstone_dust_line0"])

        BIOME_TINTED_KEYWORDS = ("grass", "leaves", "vine", "foliage", "water", "fern", "lily_pad", "sugar_cane")
        if any(k in path_part for k in BIOME_TINTED_KEYWORDS):
            for b_suffix in JMC2OBJ_BIOME_SUFFIXES:
                if path_part.endswith(b_suffix):
                    stripped_path = path_part[:-len(b_suffix)]
                    converted_stripped = stripped_path.replace("-", "/")
                    candidates.append(converted_stripped + b_suffix)
                    candidates.append(converted_stripped)
                    if "/" in converted_stripped:
                        candidates.append(converted_stripped.split("/", 1)[1] + b_suffix)
                        candidates.append(converted_stripped.split("/", 1)[1])
                    path_part = stripped_path
                    break

        # Convert jmc2obj '-' to '/' for folder hierarchy
        converted = path_part.replace("-", "/")
        candidates.append(converted)
        if cur_ns != DEFAULT_NAMESPACE:
            candidates.append(f"{cur_ns}:{converted}")
        if "/" in converted:
            cat, rest_sub = converted.split("/", 1)
            candidates.append(rest_sub)
            if cat != "block":
                candidates.append(f"block/{rest_sub}")
            if cat != "entity":
                candidates.append(f"entity/{rest_sub}")
        else:
            candidates.append(f"block/{converted}")
            candidates.append(f"entity/{converted}")

        # Expand semantic Minecraft aliases (beds, signs, slabs, stairs, carpets, etc.)
        candidates.extend(_expand_semantic_candidates(converted))

    # Add base candidates from nodes/name
    candidates.extend(base_cands)

    return namespace, list(dict.fromkeys(c for c in candidates if c))


class Jmc2objAdapter(ImporterAdapter):
    """jmc2obj exported material names, texture paths, and block/entity aliases."""

    identifier = "jmc2obj"
    description = "jmc2obj exported material names, texture paths, and block/entity aliases"

    def detect(self, mat: bpy.types.Material | None) -> bool:
        return is_jmc2obj_material(mat)

    def extract_keys(self, mat: bpy.types.Material) -> tuple[str, list[str]]:
        return jmc2obj_texture_candidates(mat)

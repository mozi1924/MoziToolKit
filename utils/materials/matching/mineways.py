"""
Mineways format adapter, material naming conventions, and block aliases.
"""

from __future__ import annotations

import re
import bpy
from .base import ImporterAdapter, base_texture_candidates, normalized_image_key
from .ice_cube import is_ice_cube_material
from .jmc2obj import is_jmc2obj_material, _expand_semantic_candidates
from ..constants import DEFAULT_NAMESPACE
from ..provenance import without_blender_suffix, is_mozi_material


# Complete Mineways block & tile name alias dictionary built against Mineways source and Minecraft JAR definitions
MINEWAYS_BLOCK_NAME_ALIASES: dict[str, list[str]] = {
    # Liquids
    "stationary_water": ["block/water_still", "block/water_flow", "water_still"],
    "water": ["block/water_still", "block/water_flow", "water_still"],
    "stationary_lava": ["block/lava_still", "block/lava_flow", "lava_still"],
    "lava": ["block/lava_still", "block/lava_flow", "lava_still"],

    # Redstone & Lighting
    "lit_redstone_lamp": ["block/redstone_lamp_on", "block/redstone_lamp"],
    "redstone_lamp": ["block/redstone_lamp", "block/redstone_lamp_on"],
    "lit_furnace": ["block/furnace_front_on", "block/furnace_front", "block/furnace_side"],
    "furnace": ["block/furnace_front", "block/furnace_side", "block/furnace_top"],
    "lit_redstone_torch": ["block/redstone_torch", "block/redstone_torch_off"],
    "redstone_torch": ["block/redstone_torch", "block/redstone_torch_off"],
    "redstone_wire": ["block/redstone_dust_line0", "block/redstone_dust_dot", "block/redstone_dust_line", "block/redstone_dust_overlay"],

    # Redstone Wire / Dust Layout & State Variants (Mineways tiles)
    "redstone_dust_line0": ["block/redstone_dust_line0", "block/redstone_dust_overlay", "block/redstone_dust_dot"],
    "redstone_dust_line0_off": ["block/redstone_dust_line0", "block/redstone_dust_overlay", "block/redstone_dust_dot"],
    "redstone_dust_line0_on": ["block/redstone_dust_line0", "block/redstone_dust_overlay", "block/redstone_dust_dot"],
    "redstone_dust_line1": ["block/redstone_dust_line1", "block/redstone_dust_overlay", "block/redstone_dust_dot"],
    "redstone_dust_line1_off": ["block/redstone_dust_line1", "block/redstone_dust_overlay", "block/redstone_dust_dot"],
    "redstone_dust_line1_on": ["block/redstone_dust_line1", "block/redstone_dust_overlay", "block/redstone_dust_dot"],
    "redstone_dust_dot": ["block/redstone_dust_dot", "block/redstone_dust_overlay"],
    "redstone_dust_dot_off": ["block/redstone_dust_dot", "block/redstone_dust_overlay"],
    "redstone_dust_dot_on": ["block/redstone_dust_dot", "block/redstone_dust_overlay"],
    "redstone_dust_angled": ["block/redstone_dust_line0", "block/redstone_dust_line1", "block/redstone_dust_overlay"],
    "redstone_dust_angled_off": ["block/redstone_dust_line0", "block/redstone_dust_line1", "block/redstone_dust_overlay"],
    "redstone_dust_angled_on": ["block/redstone_dust_line0", "block/redstone_dust_line1", "block/redstone_dust_overlay"],
    "redstone_dust_three_way": ["block/redstone_dust_line1", "block/redstone_dust_overlay", "block/redstone_dust_dot"],
    "redstone_dust_three_way_off": ["block/redstone_dust_line1", "block/redstone_dust_overlay", "block/redstone_dust_dot"],
    "redstone_dust_three_way_on": ["block/redstone_dust_line1", "block/redstone_dust_overlay", "block/redstone_dust_dot"],
    "redstone_dust_four_way": ["block/redstone_dust_dot", "block/redstone_dust_line1", "block/redstone_dust_overlay"],
    "redstone_dust_four_way_off": ["block/redstone_dust_dot", "block/redstone_dust_line1", "block/redstone_dust_overlay"],
    "redstone_dust_four_way_on": ["block/redstone_dust_dot", "block/redstone_dust_line1", "block/redstone_dust_overlay"],
    "redstone_dust_cross": ["block/redstone_dust_dot", "block/redstone_dust_line1", "block/redstone_dust_overlay"],
    "redstone_dust_cross_off": ["block/redstone_dust_dot", "block/redstone_dust_line1", "block/redstone_dust_overlay"],
    "redstone_wire_dot": ["block/redstone_dust_dot", "block/redstone_dust_overlay"],
    "redstone_wire_line0": ["block/redstone_dust_line0", "block/redstone_dust_overlay"],
    "redstone_wire_line1": ["block/redstone_dust_line1", "block/redstone_dust_overlay"],
    "redstone_wire_angled": ["block/redstone_dust_line0", "block/redstone_dust_line1", "block/redstone_dust_overlay"],
    "redstone_wire_three_way": ["block/redstone_dust_line1", "block/redstone_dust_overlay", "block/redstone_dust_dot"],
    "redstone_wire_four_way": ["block/redstone_dust_dot", "block/redstone_dust_line1", "block/redstone_dust_overlay"],

    # Torches & Flattened Torches (Mineways 3D Print / Composite tiles)
    "flattened_torch_top": ["block/torch"],
    "flattened_redstone_torch_top": ["block/redstone_torch"],
    "flattened_redstone_torch_top_off": ["block/redstone_torch_off"],
    "flattened_soul_torch_top": ["block/soul_torch"],
    "flattened_copper_torch_top": ["block/copper_torch"],

    # Beds (Mineways tile parts - Red default + multi-color support)
    "bed_feet_top": ["entity/bed/red", "block/red_bed_top", "block/red_bed_head_up", "block/red_bed_foot_up", "block/red_bed", "block/red_bed_head_north", "block/red_bed_foot_south", "block/red_bed_head_east", "block/red_bed_foot_east"],
    "bed_head_top": ["entity/bed/red", "block/red_bed_top", "block/red_bed_head", "block/red_bed_head_up", "block/red_bed", "block/red_bed_head_north", "block/red_bed_foot_south", "block/red_bed_head_east", "block/red_bed_foot_east"],
    "bed_feet_end": ["entity/bed/red", "block/red_bed_foot", "block/red_bed", "block/red_bed_foot_up", "block/red_bed_foot_south", "block/red_bed_foot_east"],
    "bed_feet_side": ["entity/bed/red", "block/red_bed_side", "block/red_bed", "block/red_bed_foot_up", "block/red_bed_foot_south", "block/red_bed_foot_east"],
    "bed_head_side": ["entity/bed/red", "block/red_bed_side", "block/red_bed", "block/red_bed_head_up", "block/red_bed_head_north", "block/red_bed_head_east"],
    "bed_head_end": ["entity/bed/red", "block/red_bed_head", "block/red_bed", "block/red_bed_head_up", "block/red_bed_head_north", "block/red_bed_head_east"],

    # Chests (Single & Double, Normal, Trapped, Ender, Copper, Christmas)
    # Normal Chest
    "chest_front": ["entity/chest/normal", "entity/chest/chest", "block/chest_front"],
    "chest_side": ["entity/chest/normal", "entity/chest/chest", "block/chest_side"],
    "chest_top": ["entity/chest/normal", "entity/chest/chest", "block/chest_top"],
    "chest_back": ["entity/chest/normal", "entity/chest/chest"],
    "chest_bottom": ["entity/chest/normal", "entity/chest/chest"],
    "chest_latch": ["entity/chest/normal", "entity/chest/chest"],
    "double_chest_front_left": ["entity/chest/normal_left", "entity/chest/normal"],
    "double_chest_front_right": ["entity/chest/normal_right", "entity/chest/normal"],
    "double_chest_back_left": ["entity/chest/normal_left", "entity/chest/normal"],
    "double_chest_back_right": ["entity/chest/normal_right", "entity/chest/normal"],
    "double_chest_top_left": ["entity/chest/normal_left", "entity/chest/normal"],
    "double_chest_top_right": ["entity/chest/normal_right", "entity/chest/normal"],
    "double_chest_bottom_left": ["entity/chest/normal_left", "entity/chest/normal"],
    "double_chest_bottom_right": ["entity/chest/normal_right", "entity/chest/normal"],

    # Ender Chest
    "ender_chest_front": ["entity/chest/ender", "entity/chest/ender_chest", "block/ender_chest"],
    "ender_chest_side": ["entity/chest/ender", "entity/chest/ender_chest", "block/ender_chest"],
    "ender_chest_top": ["entity/chest/ender", "entity/chest/ender_chest", "block/ender_chest"],
    "ender_chest_back": ["entity/chest/ender", "entity/chest/ender_chest", "block/ender_chest"],
    "ender_chest_bottom": ["entity/chest/ender", "entity/chest/ender_chest", "block/ender_chest"],
    "ender_chest_latch": ["entity/chest/ender", "entity/chest/ender_chest", "block/ender_chest"],

    # Trapped Chest
    "trapped_chest_front": ["entity/chest/trapped", "block/trapped_chest"],
    "trapped_chest_side": ["entity/chest/trapped", "block/trapped_chest"],
    "trapped_chest_top": ["entity/chest/trapped", "block/trapped_chest"],
    "trapped_chest_back": ["entity/chest/trapped", "block/trapped_chest"],
    "trapped_chest_bottom": ["entity/chest/trapped", "block/trapped_chest"],
    "trapped_chest_latch": ["entity/chest/trapped", "block/trapped_chest"],
    "trapped_double_chest_front_left": ["entity/chest/trapped_left", "entity/chest/trapped"],
    "trapped_double_chest_front_right": ["entity/chest/trapped_right", "entity/chest/trapped"],
    "trapped_double_chest_back_left": ["entity/chest/trapped_left", "entity/chest/trapped"],
    "trapped_double_chest_back_right": ["entity/chest/trapped_right", "entity/chest/trapped"],
    "trapped_double_chest_top_left": ["entity/chest/trapped_left", "entity/chest/trapped"],
    "trapped_double_chest_top_right": ["entity/chest/trapped_right", "entity/chest/trapped"],
    "trapped_double_chest_bottom_left": ["entity/chest/trapped_left", "entity/chest/trapped"],
    "trapped_double_chest_bottom_right": ["entity/chest/trapped_right", "entity/chest/trapped"],

    # Copper Chest
    "copper_chest_front": ["entity/chest/copper", "block/copper_chest"],
    "copper_chest_side": ["entity/chest/copper", "block/copper_chest"],
    "copper_chest_top": ["entity/chest/copper", "block/copper_chest"],
    "copper_chest_back": ["entity/chest/copper", "block/copper_chest"],
    "copper_chest_bottom": ["entity/chest/copper", "block/copper_chest"],
    "copper_chest_latch": ["entity/chest/copper", "block/copper_chest"],
    "copper_double_chest_front_left": ["entity/chest/copper_left", "entity/chest/copper"],
    "copper_double_chest_front_right": ["entity/chest/copper_right", "entity/chest/copper"],
    "copper_double_chest_back_left": ["entity/chest/copper_left", "entity/chest/copper"],
    "copper_double_chest_back_right": ["entity/chest/copper_right", "entity/chest/copper"],
    "copper_double_chest_top_left": ["entity/chest/copper_left", "entity/chest/copper"],
    "copper_double_chest_top_right": ["entity/chest/copper_right", "entity/chest/copper"],
    "copper_double_chest_bottom_left": ["entity/chest/copper_left", "entity/chest/copper"],
    "copper_double_chest_bottom_right": ["entity/chest/copper_right", "entity/chest/copper"],

    # Exposed Copper Chest
    "exposed_copper_chest_front": ["entity/chest/copper_exposed", "entity/chest/copper_weathered", "block/exposed_copper_chest"],
    "exposed_copper_chest_side": ["entity/chest/copper_exposed", "entity/chest/copper_weathered", "block/exposed_copper_chest"],
    "exposed_copper_chest_top": ["entity/chest/copper_exposed", "entity/chest/copper_weathered", "block/exposed_copper_chest"],
    "exposed_copper_chest_back": ["entity/chest/copper_exposed", "entity/chest/copper_weathered", "block/exposed_copper_chest"],
    "exposed_copper_chest_bottom": ["entity/chest/copper_exposed", "entity/chest/copper_weathered", "block/exposed_copper_chest"],
    "exposed_copper_chest_latch": ["entity/chest/copper_exposed", "entity/chest/copper_weathered", "block/exposed_copper_chest"],
    "exposed_copper_double_chest_front_left": ["entity/chest/copper_exposed_left", "entity/chest/copper_exposed"],
    "exposed_copper_double_chest_front_right": ["entity/chest/copper_exposed_right", "entity/chest/copper_exposed"],
    "exposed_copper_double_chest_back_left": ["entity/chest/copper_exposed_left", "entity/chest/copper_exposed"],
    "exposed_copper_double_chest_back_right": ["entity/chest/copper_exposed_right", "entity/chest/copper_exposed"],
    "exposed_copper_double_chest_top_left": ["entity/chest/copper_exposed_left", "entity/chest/copper_exposed"],
    "exposed_copper_double_chest_top_right": ["entity/chest/copper_exposed_right", "entity/chest/copper_exposed"],
    "exposed_copper_double_chest_bottom_left": ["entity/chest/copper_exposed_left", "entity/chest/copper_exposed"],
    "exposed_copper_double_chest_bottom_right": ["entity/chest/copper_exposed_right", "entity/chest/copper_exposed"],

    # Weathered Copper Chest
    "weathered_copper_chest_front": ["entity/chest/copper_weathered", "block/weathered_copper_chest"],
    "weathered_copper_chest_side": ["entity/chest/copper_weathered", "block/weathered_copper_chest"],
    "weathered_copper_chest_top": ["entity/chest/copper_weathered", "block/weathered_copper_chest"],
    "weathered_copper_chest_back": ["entity/chest/copper_weathered", "block/weathered_copper_chest"],
    "weathered_copper_chest_bottom": ["entity/chest/copper_weathered", "block/weathered_copper_chest"],
    "weathered_copper_chest_latch": ["entity/chest/copper_weathered", "block/weathered_copper_chest"],
    "weathered_copper_double_chest_front_left": ["entity/chest/copper_weathered_left", "entity/chest/copper_weathered"],
    "weathered_copper_double_chest_front_right": ["entity/chest/copper_weathered_right", "entity/chest/copper_weathered"],
    "weathered_copper_double_chest_back_left": ["entity/chest/copper_weathered_left", "entity/chest/copper_weathered"],
    "weathered_copper_double_chest_back_right": ["entity/chest/copper_weathered_right", "entity/chest/copper_weathered"],
    "weathered_copper_double_chest_top_left": ["entity/chest/copper_weathered_left", "entity/chest/copper_weathered"],
    "weathered_copper_double_chest_top_right": ["entity/chest/copper_weathered_right", "entity/chest/copper_weathered"],
    "weathered_copper_double_chest_bottom_left": ["entity/chest/copper_weathered_left", "entity/chest/copper_weathered"],
    "weathered_copper_double_chest_bottom_right": ["entity/chest/copper_weathered_right", "entity/chest/copper_weathered"],

    # Oxidized Copper Chest
    "oxidized_copper_chest_front": ["entity/chest/copper_oxidized", "block/oxidized_copper_chest"],
    "oxidized_copper_chest_side": ["entity/chest/copper_oxidized", "block/oxidized_copper_chest"],
    "oxidized_copper_chest_top": ["entity/chest/copper_oxidized", "block/oxidized_copper_chest"],
    "oxidized_copper_chest_back": ["entity/chest/copper_oxidized", "block/oxidized_copper_chest"],
    "oxidized_copper_chest_bottom": ["entity/chest/copper_oxidized", "block/oxidized_copper_chest"],
    "oxidized_copper_chest_latch": ["entity/chest/copper_oxidized", "block/oxidized_copper_chest"],
    "oxidized_copper_double_chest_front_left": ["entity/chest/copper_oxidized_left", "entity/chest/copper_oxidized"],
    "oxidized_copper_double_chest_front_right": ["entity/chest/copper_oxidized_right", "entity/chest/copper_oxidized"],
    "oxidized_copper_double_chest_back_left": ["entity/chest/copper_oxidized_left", "entity/chest/copper_oxidized"],
    "oxidized_copper_double_chest_back_right": ["entity/chest/copper_oxidized_right", "entity/chest/copper_oxidized"],
    "oxidized_copper_double_chest_top_left": ["entity/chest/copper_oxidized_left", "entity/chest/copper_oxidized"],
    "oxidized_copper_double_chest_top_right": ["entity/chest/copper_oxidized_right", "entity/chest/copper_oxidized"],
    "oxidized_copper_double_chest_bottom_left": ["entity/chest/copper_oxidized_left", "entity/chest/copper_oxidized"],
    "oxidized_copper_double_chest_bottom_right": ["entity/chest/copper_oxidized_right", "entity/chest/copper_oxidized"],

    # Christmas Chest
    "christmas_chest_front": ["entity/chest/christmas", "entity/chest/christmas_chest"],
    "christmas_chest_side": ["entity/chest/christmas", "entity/chest/christmas_chest"],
    "christmas_chest_top": ["entity/chest/christmas", "entity/chest/christmas_chest"],
    "christmas_chest_back": ["entity/chest/christmas", "entity/chest/christmas_chest"],
    "christmas_chest_bottom": ["entity/chest/christmas", "entity/chest/christmas_chest"],
    "christmas_chest_latch": ["entity/chest/christmas", "entity/chest/christmas_chest"],
    "christmas_double_chest_front_left": ["entity/chest/christmas_left", "entity/chest/christmas"],
    "christmas_double_chest_front_right": ["entity/chest/christmas_right", "entity/chest/christmas"],
    "christmas_double_chest_back_left": ["entity/chest/christmas_left", "entity/chest/christmas"],
    "christmas_double_chest_back_right": ["entity/chest/christmas_right", "entity/chest/christmas"],
    "christmas_double_chest_top_left": ["entity/chest/christmas_left", "entity/chest/christmas"],
    "christmas_double_chest_top_right": ["entity/chest/christmas_right", "entity/chest/christmas"],
    "christmas_double_chest_bottom_left": ["entity/chest/christmas_left", "entity/chest/christmas"],
    "christmas_double_chest_bottom_right": ["entity/chest/christmas_right", "entity/chest/christmas"],

    # Shelves (All wood variants)
    "acacia_shelf_front": ["block/acacia_shelf", "block/acacia_planks"],
    "acacia_shelf_back": ["block/acacia_shelf", "block/acacia_planks"],
    "acacia_shelf_powered": ["block/acacia_shelf", "block/acacia_planks"],
    "bamboo_shelf_front": ["block/bamboo_shelf", "block/bamboo_planks"],
    "bamboo_shelf_back": ["block/bamboo_shelf", "block/bamboo_planks"],
    "bamboo_shelf_powered": ["block/bamboo_shelf", "block/bamboo_planks"],
    "birch_shelf_front": ["block/birch_shelf", "block/birch_planks"],
    "birch_shelf_back": ["block/birch_shelf", "block/birch_planks"],
    "birch_shelf_powered": ["block/birch_shelf", "block/birch_planks"],
    "cherry_shelf_front": ["block/cherry_shelf", "block/cherry_planks"],
    "cherry_shelf_back": ["block/cherry_shelf", "block/cherry_planks"],
    "cherry_shelf_powered": ["block/cherry_shelf", "block/cherry_planks"],
    "crimson_shelf_front": ["block/crimson_shelf", "block/crimson_planks"],
    "crimson_shelf_back": ["block/crimson_shelf", "block/crimson_planks"],
    "crimson_shelf_powered": ["block/crimson_shelf", "block/crimson_planks"],
    "dark_oak_shelf_front": ["block/dark_oak_shelf", "block/dark_oak_planks"],
    "dark_oak_shelf_back": ["block/dark_oak_shelf", "block/dark_oak_planks"],
    "dark_oak_shelf_powered": ["block/dark_oak_shelf", "block/dark_oak_planks"],
    "jungle_shelf_front": ["block/jungle_shelf", "block/jungle_planks"],
    "jungle_shelf_back": ["block/jungle_shelf", "block/jungle_planks"],
    "jungle_shelf_powered": ["block/jungle_shelf", "block/jungle_planks"],
    "mangrove_shelf_front": ["block/mangrove_shelf", "block/mangrove_planks"],
    "mangrove_shelf_back": ["block/mangrove_shelf", "block/mangrove_planks"],
    "mangrove_shelf_powered": ["block/mangrove_shelf", "block/mangrove_planks"],
    "oak_shelf_front": ["block/oak_shelf", "block/oak_planks"],
    "oak_shelf_back": ["block/oak_shelf", "block/oak_planks"],
    "oak_shelf_powered": ["block/oak_shelf", "block/oak_planks"],
    "oak_shelf_shelf_front": ["block/oak_shelf", "block/oak_planks"],
    "oak_shelf_shelf_back": ["block/oak_shelf", "block/oak_planks"],
    "oak_shelf_shelf_powered": ["block/oak_shelf", "block/oak_planks"],
    "pale_oak_shelf_front": ["block/pale_oak_shelf", "block/pale_oak_planks"],
    "pale_oak_shelf_back": ["block/pale_oak_shelf", "block/pale_oak_planks"],
    "pale_oak_shelf_powered": ["block/pale_oak_shelf", "block/pale_oak_planks"],
    "spruce_shelf_front": ["block/spruce_shelf", "block/spruce_planks"],
    "spruce_shelf_back": ["block/spruce_shelf", "block/spruce_planks"],
    "spruce_shelf_powered": ["block/spruce_shelf", "block/spruce_planks"],
    "warped_shelf_front": ["block/warped_shelf", "block/warped_planks"],
    "warped_shelf_back": ["block/warped_shelf", "block/warped_planks"],
    "warped_shelf_powered": ["block/warped_shelf", "block/warped_planks"],

    # Decorated Pots
    "decorated_pot_base1": ["entity/decorated_pot/decorated_pot_base", "entity/decorated_pot/base"],
    "decorated_pot_base2": ["entity/decorated_pot/decorated_pot_base", "entity/decorated_pot/base"],
    "decorated_pot_base3": ["entity/decorated_pot/decorated_pot_base", "entity/decorated_pot/base"],
    "decorated_pot_base4": ["entity/decorated_pot/decorated_pot_base", "entity/decorated_pot/base"],

    # Slabs, Stone, and Chains
    "stone_slab_side": ["block/smooth_stone_slab_side", "block/stone", "block/smooth_stone"],
    "stone_slab_top": ["block/stone", "block/smooth_stone"],
    "smooth_stone_slab_side": ["block/smooth_stone_slab_side", "block/smooth_stone", "block/stone"],
    "chain": ["block/chain", "block/iron_chain", "item/chain", "item/iron_chain"],
    "end_portal": ["entity/end_portal"],

    # Bell
    "bell_top": ["entity/bell/bell_body", "entity/bell/bell", "block/bell_top"],
    "bell_side": ["entity/bell/bell_body", "entity/bell/bell", "block/bell_side"],
    "bell_bottom": ["entity/bell/bell_body", "entity/bell/bell", "block/bell_bottom"],

    # Shulkers
    "shulker_side": ["entity/shulker/shulker", "block/shulker_box"],
    "shulker_bottom": ["entity/shulker/shulker", "block/shulker_box"],

    # Special block names
    "monster_spawner": ["block/spawner", "block/monster_spawner"],
    "monster_egg": ["block/stone", "block/cobblestone", "block/stone_bricks"],
    "wheat_crops": ["block/wheat_stage7", "block/wheat_stage0"],
    "hay_bale": ["block/hay_block_side", "block/hay_block_top"],
    "leaves_2": ["block/acacia_leaves", "block/dark_oak_leaves"],
    "wood_2": ["block/acacia_log", "block/dark_oak_log"],
    "stained_clay": ["block/terracotta"],
    "hardened_clay": ["block/terracotta"],
    "standing_banner": ["entity/banner/banner_base", "entity/banner/base"],
    "wall_banner": ["entity/banner/banner_base", "entity/banner/base"],
    "sign": ["entity/signs/oak", "block/oak_sign", "block/oak_planks"],
    "wall_sign": ["entity/signs/oak", "block/oak_sign", "block/oak_planks"],
    "flower_pot": ["block/flower_pot"],
    "skeleton_skull": ["entity/skeleton/skeleton"],
    "wither_skeleton_skull": ["entity/skeleton/wither_skeleton"],
    "zombie_head": ["entity/zombie/zombie"],
    "creeper_head": ["entity/creeper/creeper"],
    "dragon_head": ["entity/enderdragon/dragon"],
    "piglin_head": ["entity/piglin/piglin"],
    "player_head": ["entity/player/wide/steve"],
    "grass_path": ["block/dirt_path_top", "block/dirt_path_side", "block/grass_path_top"],
    "dirt_path": ["block/dirt_path_top", "block/dirt_path_side"],
    "tall_grass": ["block/short_grass", "block/tall_grass_top", "block/tall_grass_bottom", "block/grass"],
    "large_flowers": ["block/sunflower_front", "block/peony_top", "block/rose_bush_top"],
    "oak_wood": ["block/oak_log", "block/oak_log_top", "block/oak_wood"],
    "spruce_wood": ["block/spruce_log", "block/spruce_log_top", "block/spruce_wood"],
    "birch_wood": ["block/birch_log", "block/birch_log_top", "block/birch_wood"],
    "jungle_wood": ["block/jungle_log", "block/jungle_log_top", "block/jungle_wood"],
    "acacia_wood": ["block/acacia_log", "block/acacia_log_top", "block/acacia_wood"],
    "dark_oak_wood": ["block/dark_oak_log", "block/dark_oak_log_top", "block/dark_oak_wood"],
    "mangrove_wood": ["block/mangrove_log", "block/mangrove_log_top", "block/mangrove_wood"],
    "cherry_wood": ["block/cherry_log", "block/cherry_log_top", "block/cherry_wood"],
}

from ..mineways_atlas import (
    is_mineways_atlas_material,
    is_mineways_atlas_image,
    MINEWAYS_ATLAS_NAME_PATTERNS as MINEWAYS_ATLAS_TEXTURE_PATTERNS,
)


def is_mineways_material(mat: bpy.types.Material | None) -> bool:
    """Detect materials exported by Mineways via naming conventions, image paths, or metadata."""
    if not mat:
        return False
    if is_mozi_material(mat) or is_ice_cube_material(mat) or is_jmc2obj_material(mat):
        return False
    if mat.get("mtk:source_importer") == "mineways":
        return True
    if is_mineways_atlas_material(mat):
        return True

    name = without_blender_suffix(mat.name.strip().lower())

    # 1. Single material export mode
    if name == "mc_material":
        return True

    # 2. Mineways synthesized tile materials (e.g. grass_block_top_y, short_grass_y)
    if name.endswith("_y") or name.startswith("mw_") or name.startswith("mwo_"):
        return True

    # 3. Check attached texture image nodes and node tree metadata
    if mat.use_nodes and mat.node_tree:
        tree_name = without_blender_suffix(mat.node_tree.name.strip().lower()).removesuffix(".png")
        if tree_name == "mc_material" or tree_name.endswith("_y") or tree_name.startswith(("mw_", "mwo_")):
            return True
        if any(tree_name == pat or tree_name.startswith(pat) for pat in MINEWAYS_ATLAS_TEXTURE_PATTERNS):
            return True

        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE":
                if node.image:
                    if is_mineways_atlas_image(node.image):
                        return True
                    fp = (node.image.filepath or node.image.name or "").replace("\\", "/").lower()
                    clean_img_name = without_blender_suffix(node.image.name.lower()).removesuffix(".png")
                    # Mineways synthesized tiles (ending in _y or _y.png)
                    if clean_img_name.endswith("_y"):
                        return True
                    # Mineways internal prefix in image name/path
                    if "mw_" in clean_img_name or "mwo_" in clean_img_name:
                        return True
                    # Mineways default tile export folder: tex/<tile>.png (excluding jmc2obj tex/minecraft/ and tex/jmc2obj/)
                    if "/tex/" in fp or fp.startswith("tex/") or "tex/" in fp:
                        if (
                            "/tex/minecraft/" not in fp
                            and "tex/minecraft/" not in fp
                            and "/tex/jmc2obj/" not in fp
                            and "tex/jmc2obj/" not in fp
                        ):
                            return True
                # Fallback: check node label or custom node name for Mineways signatures
                for attr_val in (node.label, node.name):
                    if attr_val:
                        clean_attr = without_blender_suffix(attr_val.strip().lower()).removesuffix(".png")
                        if clean_attr.endswith("_y") or clean_attr.startswith(("mw_", "mwo_")):
                            return True
                        if "/tex/" in clean_attr or clean_attr.startswith("tex/"):
                            if "tex/minecraft/" not in clean_attr and "tex/jmc2obj/" not in clean_attr:
                                 return True
                        if any(clean_attr == pat or clean_attr.startswith(pat) for pat in MINEWAYS_ATLAS_TEXTURE_PATTERNS):
                            return True

    return False


def mineways_texture_candidates(mat: bpy.types.Material) -> tuple[str, list[str]]:
    """Extract candidate texture keys for materials exported by Mineways."""
    namespace, base_cands = base_texture_candidates(mat)
    if mat.get("mtk:source_namespace"):
        return namespace, base_cands

    candidates: list[str] = []
    source_name = without_blender_suffix(mat.name.strip().lower())
    raw_names = [source_name]

    # Collect raw image names, filepaths, and node labels from texture nodes
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
                        if norm_fp.endswith(".png"):
                            norm_fp = norm_fp[:-4]
                        img_stem = norm_fp.split("/")[-1]
                        if img_stem and img_stem not in raw_names:
                            raw_names.append(img_stem)
                    img_key = normalized_image_key(node.image)
                    if img_key and img_key not in raw_names:
                        raw_names.append(img_key)
                # Fallback: check node label or custom node name
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

        # Strip leading tex/ or /tex/ path prefixes
        if stem.startswith("tex/"):
            stem = stem[4:]
        elif "/tex/" in stem:
            stem = stem.split("/tex/")[-1]

        # Ignore generic Atlas atlas names
        if stem in MINEWAYS_ATLAS_TEXTURE_PATTERNS or stem == "mc_material":
            continue

        # Strip Mineways synthesized suffix '_y' (e.g. grass_block_top_y -> grass_block_top)
        if stem.endswith("_y"):
            stem = stem[:-2]

        # Strip Mineways internal prefixes 'mw_' or 'mwo_'
        if stem.startswith("mwo_"):
            stem = stem[4:]
        elif stem.startswith("mw_"):
            stem = stem[3:]

        # Direct explicit Mineways alias mapping
        if stem in MINEWAYS_BLOCK_NAME_ALIASES:
            candidates.extend(MINEWAYS_BLOCK_NAME_ALIASES[stem])

        # Standard category prefixes
        candidates.append(stem)
        candidates.append(f"block/{stem}")
        candidates.append(f"entity/{stem}")
        candidates.append(f"item/{stem}")

        # Expand semantic Minecraft aliases (beds, signs, slabs, stairs, carpets, etc.)
        candidates.extend(_expand_semantic_candidates(stem))

    # Add base candidates from nodes/name
    candidates.extend(base_cands)

    return namespace, list(dict.fromkeys(c for c in candidates if c))


class MinewaysAdapter(ImporterAdapter):
    """Mineways exported material names, texture paths, and block/tile aliases."""

    identifier = "mineways"
    description = "Mineways exported material names, texture paths, and block/tile aliases"

    def detect(self, mat: bpy.types.Material | None) -> bool:
        return is_mineways_material(mat)

    def extract_keys(self, mat: bpy.types.Material) -> tuple[str, list[str]]:
        return mineways_texture_candidates(mat)

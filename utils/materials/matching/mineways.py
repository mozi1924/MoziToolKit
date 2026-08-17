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
    "redstone_wire": ["block/redstone_dust_line0", "block/redstone_dust_dot", "block/redstone_dust_line"],
    # Beds (Mineways tile parts)
    "bed_feet_top": ["entity/bed/red", "block/red_bed_top", "block/red_bed_head_up", "block/red_bed"],
    "bed_head_top": ["entity/bed/red", "block/red_bed_top", "block/red_bed_head", "block/red_bed_head_up", "block/red_bed"],
    "bed_feet_end": ["entity/bed/red", "block/red_bed_foot", "block/red_bed"],
    "bed_feet_side": ["entity/bed/red", "block/red_bed_side", "block/red_bed"],
    "bed_head_side": ["entity/bed/red", "block/red_bed_side", "block/red_bed"],
    "bed_head_end": ["entity/bed/red", "block/red_bed_head", "block/red_bed"],
    # Chests (Mineways tile parts)
    "chest_front": ["entity/chest/normal", "entity/chest/chest", "block/chest_front"],
    "chest_side": ["entity/chest/normal", "entity/chest/chest", "block/chest_side"],
    "chest_top": ["entity/chest/normal", "entity/chest/chest", "block/chest_top"],
    "chest_latch": ["entity/chest/normal", "entity/chest/chest"],
    # Bell
    "bell_top": ["entity/bell/bell_body", "entity/bell/bell", "block/bell_top"],
    "bell_side": ["entity/bell/bell_body", "entity/bell/bell", "block/bell_side"],
    "bell_bottom": ["entity/bell/bell_body", "entity/bell/bell", "block/bell_bottom"],
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

# Signatures for Mineways textures
MINEWAYS_ATLAS_TEXTURE_PATTERNS = (
    "terrainrgba",
    "terrainrgb",
    "terrainext",
    "terrain",
)


def is_mineways_material(mat: bpy.types.Material | None) -> bool:
    """Detect materials exported by Mineways via naming conventions, image paths, or metadata."""
    if not mat:
        return False
    if is_mozi_material(mat) or is_ice_cube_material(mat) or is_jmc2obj_material(mat):
        return False
    if mat.get("mtk:source_importer") == "mineways":
        return True

    name = without_blender_suffix(mat.name.strip().lower())

    # 1. Single material export mode
    if name == "mc_material":
        return True

    # 2. Mineways synthesized tile materials (e.g. grass_block_top_y, short_grass_y)
    if name.endswith("_y") or name.startswith("mw_") or name.startswith("mwo_"):
        return True

    # 3. Check attached texture image nodes
    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                fp = (node.image.filepath or node.image.name or "").replace("\\", "/").lower()
                clean_img_name = without_blender_suffix(node.image.name.lower()).removesuffix(".png")
                # Mineways terrain atlas textures
                if any(clean_img_name == pat or clean_img_name.startswith(pat) for pat in MINEWAYS_ATLAS_TEXTURE_PATTERNS):
                    return True
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

    return False


def mineways_texture_candidates(mat: bpy.types.Material) -> tuple[str, list[str]]:
    """Extract candidate texture keys for materials exported by Mineways."""
    namespace, base_cands = base_texture_candidates(mat)
    if mat.get("mtk:source_namespace"):
        return namespace, base_cands

    candidates: list[str] = []
    source_name = without_blender_suffix(mat.name.strip().lower())
    raw_names = [source_name]

    # Collect raw image names and filepaths from texture nodes
    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
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

    for item in raw_names:
        stem = without_blender_suffix(item)
        if stem.endswith(".png"):
            stem = stem[:-4]

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

"""
Mineways Presets & Alias Mappings.
Pure data definitions and candidate generation routines.
"""

from __future__ import annotations

import re

MINEWAYS_BLOCK_NAME_ALIASES = {
    # Torches & Redstone Wire
    "redstone_torch": ["block/redstone_torch", "block/redstone_torch_off"],
    "redstone_wire": ["block/redstone_dust_line0", "block/redstone_dust_dot", "block/redstone_dust_line", "block/redstone_dust_overlay"],
    "redstone_dust_line0": ["block/redstone_dust_line0", "block/redstone_dust_overlay", "block/redstone_dust_dot"],
    "redstone_dust_line1": ["block/redstone_dust_line1", "block/redstone_dust_overlay", "block/redstone_dust_dot"],
    "redstone_dust_dot": ["block/redstone_dust_dot", "block/redstone_dust_overlay"],
    "flattened_torch_top": ["block/torch"],
    "flattened_redstone_torch_top": ["block/redstone_torch"],
    "flattened_redstone_torch_top_off": ["block/redstone_torch_off"],
    "flattened_soul_torch_top": ["block/soul_torch"],

    # Beds (Mineways tile parts)
    "bed_feet_top": ["entity/bed/red", "block/red_bed_top", "block/red_bed_head_up", "block/red_bed_foot_up", "block/red_bed"],
    "bed_head_top": ["entity/bed/red", "block/red_bed_top", "block/red_bed_head", "block/red_bed_head_up", "block/red_bed"],
    "bed_feet_end": ["entity/bed/red", "block/red_bed_foot", "block/red_bed", "block/red_bed_foot_up"],
    "bed_feet_side": ["entity/bed/red", "block/red_bed_side", "block/red_bed", "block/red_bed_foot_up"],
    "bed_head_side": ["entity/bed/red", "block/red_bed_side", "block/red_bed", "block/red_bed_head_up"],
    "bed_head_end": ["entity/bed/red", "block/red_bed_head", "block/red_bed", "block/red_bed_head_up"],

    # Chests
    "chest_front": ["entity/chest/normal", "entity/chest/chest", "block/chest_front"],
    "chest_side": ["entity/chest/normal", "entity/chest/chest", "block/chest_side"],
    "chest_top": ["entity/chest/normal", "entity/chest/chest", "block/chest_top"],
    "chest_back": ["entity/chest/normal", "entity/chest/chest"],
    "chest_bottom": ["entity/chest/normal", "entity/chest/chest"],
    "chest_latch": ["entity/chest/normal", "entity/chest/chest"],
    "double_chest_front_left": ["entity/chest/normal_left", "entity/chest/normal"],
    "double_chest_front_right": ["entity/chest/normal_right", "entity/chest/normal"],
    "double_chest_top_left": ["entity/chest/normal_left", "entity/chest/normal"],
    "double_chest_top_right": ["entity/chest/normal_right", "entity/chest/normal"],

    # Ender & Trapped Chests
    "ender_chest_front": ["entity/chest/ender", "entity/chest/ender_chest", "block/ender_chest"],
    "ender_chest_side": ["entity/chest/ender", "entity/chest/ender_chest", "block/ender_chest"],
    "ender_chest_top": ["entity/chest/ender", "entity/chest/ender_chest", "block/ender_chest"],
    "ender_chest_latch": ["entity/chest/ender", "entity/chest/ender_chest", "block/ender_chest"],
    "trapped_chest_front": ["entity/chest/trapped", "block/trapped_chest"],
    "trapped_chest_side": ["entity/chest/trapped", "block/trapped_chest"],
    "trapped_chest_top": ["entity/chest/trapped", "block/trapped_chest"],
    "trapped_chest_latch": ["entity/chest/trapped", "block/trapped_chest"],

    # Wood Types
    "oak_wood": ["block/oak_log", "block/oak_log_top", "block/oak_wood"],
    "spruce_wood": ["block/spruce_log", "block/spruce_log_top", "block/spruce_wood"],
    "birch_wood": ["block/birch_log", "block/birch_log_top", "block/birch_wood"],
    "jungle_wood": ["block/jungle_log", "block/jungle_log_top", "block/jungle_wood"],
    "acacia_wood": ["block/acacia_log", "block/acacia_log_top", "block/acacia_wood"],
    "dark_oak_wood": ["block/dark_oak_log", "block/dark_oak_log_top", "block/dark_oak_wood"],
    "mangrove_wood": ["block/mangrove_log", "block/mangrove_log_top", "block/mangrove_wood"],
    "cherry_wood": ["block/cherry_log", "block/cherry_log_top", "block/cherry_wood"],
}


def clean_mineways_identifier(raw: str) -> str:
    """Clean Mineways synthesized suffixes (_y), internal prefixes (MW_, MWO_), and extensions."""
    s = raw.strip().lower()
    if s.endswith(".png") or s.endswith(".jpg"):
        s = s[:-4]
    if "." in s and s.rsplit(".", 1)[-1].isdigit():
        s = s.rsplit(".", 1)[0]

    prefixes = ("tex/", "textures/block/", "textures/entity/", "textures/", "mw_", "mwo_")
    for p in prefixes:
        if s.startswith(p):
            s = s[len(p):]
            break

    if s.endswith("_y"):
        s = s[:-2]

    return s.replace(" ", "_").replace("-", "_")


def expand_mineways_candidates(raw_name: str) -> list[str]:
    """Generate structured candidate paths for Mineways material names."""
    clean = clean_mineways_identifier(raw_name)
    cands: list[str] = []

    # 1. Direct explicit Mineways alias mapping
    if clean in MINEWAYS_BLOCK_NAME_ALIASES:
        cands.extend(MINEWAYS_BLOCK_NAME_ALIASES[clean])

    # 2. Chest & Bed special checks
    if clean.startswith("chest_") or clean.startswith("bed_"):
        if clean in MINEWAYS_BLOCK_NAME_ALIASES:
            cands.extend(MINEWAYS_BLOCK_NAME_ALIASES[clean])

    # 3. Standard category prefixes
    cands.append(clean)
    cands.append(f"block/{clean}")
    cands.append(f"entity/{clean}")
    cands.append(f"item/{clean}")

    return list(dict.fromkeys(c for c in cands if c))


def build_mineways_swatch_candidates_map() -> dict[int, list[str]]:
    """Build swatch_id -> list of candidate texture names from MINEWAYS_TILES_TABLE."""
    from .mineways_table import MINEWAYS_TILES_TABLE

    swatch_map: dict[int, list[str]] = {}
    for swatch_id, (_x, _y, pri, alt) in MINEWAYS_TILES_TABLE.items():
        cands: list[str] = []
        for raw in (pri, alt):
            if not raw:
                continue
            clean = raw
            if clean.startswith(("MWO_", "MW_")):
                clean = clean.split("_", 1)[1] if clean.startswith("MW_") else clean[4:]
            cands.extend(expand_mineways_candidates(clean))
        if cands:
            swatch_map[swatch_id] = list(dict.fromkeys(cands))
    return swatch_map


def build_mineways_grid_spec(image_width: int = 1024, image_height: int = 1024):
    """
    Construct a GridAtlasSpec for Mineways terrain atlases to pass to libmtk.
    """
    from .mineways_table import MINEWAYS_ATLAS_NAME_PATTERNS, MINEWAYS_ATLAS_SUFFIX_PATTERNS

    try:
        from libmtk_py import GridAtlasSpec
        return GridAtlasSpec(
            swatch_size=18.0,
            tile_size=16.0,
            border=1.0,
            image_width=image_width,
            image_height=image_height,
            atlas_name_patterns=list(MINEWAYS_ATLAS_NAME_PATTERNS),
            atlas_suffix_patterns=list(MINEWAYS_ATLAS_SUFFIX_PATTERNS),
            swatch_to_candidates=build_mineways_swatch_candidates_map(),
        )
    except ImportError:
        return {
            "swatch_size": 18.0,
            "tile_size": 16.0,
            "border": 1.0,
            "image_width": image_width,
            "image_height": image_height,
            "atlas_name_patterns": list(MINEWAYS_ATLAS_NAME_PATTERNS),
            "atlas_suffix_patterns": list(MINEWAYS_ATLAS_SUFFIX_PATTERNS),
            "swatch_to_candidates": build_mineways_swatch_candidates_map(),
        }


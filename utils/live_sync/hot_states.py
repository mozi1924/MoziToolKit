"""
Comprehensive Hot BlockState Catalog for Instant Pre-warming.
Provides the top 500+ most frequently placed interactive, directional,
and complex structural block states in Minecraft for sub-millisecond live sync dispatch.
"""

from __future__ import annotations
from typing import Tuple, List

WOOD_TYPES: tuple[str, ...] = (
    "oak", "spruce", "birch", "jungle", "acacia", "dark_oak",
    "mangrove", "cherry", "bamboo", "crimson", "warped"
)

DOOR_MATERIALS: tuple[str, ...] = (
    "oak", "spruce", "birch", "jungle", "acacia", "dark_oak",
    "mangrove", "cherry", "bamboo", "crimson", "warped",
    "iron", "copper", "exposed_copper", "weathered_copper", "oxidized_copper"
)

STAIR_SLAB_STONES: tuple[str, ...] = (
    "stone", "cobblestone", "mossy_cobblestone", "smooth_stone",
    "stone_brick", "mossy_stone_brick", "granite", "diorite", "andesite",
    "deepslate_tile", "deepslate_brick", "polished_deepslate", "cobbled_deepslate",
    "brick", "mud_brick", "sandstone", "red_sandstone", "prismarine",
    "prismarine_brick", "dark_prismarine", "nether_brick", "red_nether_brick",
    "blackstone", "polished_blackstone", "polished_blackstone_brick",
    "end_stone_brick", "quartz", "purpur", "tuff", "tuff_brick"
)

COLORS: tuple[str, ...] = (
    "white", "orange", "magenta", "light_blue", "yellow", "lime",
    "pink", "gray", "light_gray", "cyan", "purple", "blue",
    "brown", "green", "red", "black"
)

HORIZONTAL_FACINGS: tuple[str, ...] = ("north", "east", "south", "west")
SIX_FACINGS: tuple[str, ...] = ("north", "east", "south", "west", "up", "down")


def generate_hot_prewarm_states() -> tuple[str, ...]:
    """Generate comprehensive list of high-priority hot blockstates for instant pre-warming."""
    states: list[str] = []

    # 1. Base Terrain & Construction Blocks
    base_cubes = [
        "minecraft:air", "minecraft:cave_air", "minecraft:void_air",
        "minecraft:stone", "minecraft:dirt", "minecraft:grass_block[snowy=false]",
        "minecraft:grass_block[snowy=true]", "minecraft:podzol[snowy=false]",
        "minecraft:mycelium[snowy=false]", "minecraft:dirt_path", "minecraft:farmland[moisture=7]",
        "minecraft:cobblestone", "minecraft:mossy_cobblestone", "minecraft:smooth_stone",
        "minecraft:bedrock", "minecraft:sand", "minecraft:red_sand", "minecraft:gravel",
        "minecraft:deepslate", "minecraft:cobbled_deepslate", "minecraft:tuff",
        "minecraft:calcite", "minecraft:dripstone_block", "minecraft:obsidian", "minecraft:crying_obsidian",
        "minecraft:glass", "minecraft:tinted_glass", "minecraft:ice", "minecraft:packed_ice", "minecraft:blue_ice",
        "minecraft:water[level=0]", "minecraft:lava[level=0]", "minecraft:sea_lantern", "minecraft:glowstone",
        "minecraft:shroomlight", "minecraft:sponge", "minecraft:wet_sponge", "minecraft:honeycomb_block",
        "minecraft:slime_block", "minecraft:honey_block", "minecraft:sculk", "minecraft:sculk_catalyst",
    ]
    states.extend(base_cubes)

    # 2. Planks & Logs (All 11 Wood Types)
    for w in WOOD_TYPES:
        states.append(f"minecraft:{w}_planks")
        for ax in ("y", "x", "z"):
            states.append(f"minecraft:{w}_log[axis={ax}]")
            states.append(f"minecraft:stripped_{w}_log[axis={ax}]")
            states.append(f"minecraft:{w}_wood[axis={ax}]")
            states.append(f"minecraft:stripped_{w}_wood[axis={ax}]")
        states.append(f"minecraft:{w}_leaves[distance=7,persistent=false]")

    # 3. Doors (All 16 materials, lower & upper halves, 4 facings, open/closed, left/right hinges)
    for d in DOOR_MATERIALS:
        for half in ("lower", "upper"):
            for facing in HORIZONTAL_FACINGS:
                for is_open in ("false", "true"):
                    for hinge in ("left", "right"):
                        states.append(f"minecraft:{d}_door[facing={facing},half={half},hinge={hinge},open={is_open},powered=false]")

    # 4. Trapdoors (All materials, 4 facings, bottom/top, open/closed)
    for d in DOOR_MATERIALS:
        for facing in HORIZONTAL_FACINGS:
            for half in ("bottom", "top"):
                for is_open in ("false", "true"):
                    states.append(f"minecraft:{d}_trapdoor[facing={facing},half={half},open={is_open},powered=false,waterlogged=false]")

    # 5. Torches, Lanterns, and Light Sources (All orientations)
    torches = [
        "minecraft:torch",
        "minecraft:soul_torch",
        "minecraft:redstone_torch[lit=true]",
        "minecraft:redstone_torch[lit=false]",
        "minecraft:lantern[hanging=false,waterlogged=false]",
        "minecraft:lantern[hanging=true,waterlogged=false]",
        "minecraft:soul_lantern[hanging=false,waterlogged=false]",
        "minecraft:soul_lantern[hanging=true,waterlogged=false]",
    ]
    states.extend(torches)
    for facing in HORIZONTAL_FACINGS:
        states.append(f"minecraft:wall_torch[facing={facing}]")
        states.append(f"minecraft:soul_wall_torch[facing={facing}]")
        states.append(f"minecraft:redstone_wall_torch[facing={facing},lit=true]")
        states.append(f"minecraft:redstone_wall_torch[facing={facing},lit=false]")
    for ax in ("y", "x", "z"):
        states.append(f"minecraft:chain[axis={ax},waterlogged=false]")
    for facing in SIX_FACINGS:
        states.append(f"minecraft:end_rod[facing={facing}]")
        states.append(f"minecraft:lightning_rod[facing={facing},powered=false,waterlogged=false]")

    # 6. Stairs & Slabs (Wood & Stone varieties)
    all_stair_materials = list(WOOD_TYPES) + list(STAIR_SLAB_STONES)
    for mat in all_stair_materials:
        # Slabs
        states.append(f"minecraft:{mat}_slab[type=bottom,waterlogged=false]")
        states.append(f"minecraft:{mat}_slab[type=top,waterlogged=false]")
        states.append(f"minecraft:{mat}_slab[type=double,waterlogged=false]")
        # Stairs
        for facing in HORIZONTAL_FACINGS:
            for half in ("bottom", "top"):
                states.append(f"minecraft:{mat}_stairs[facing={facing},half={half},shape=straight,waterlogged=false]")

    # 7. Fences & Fence Gates
    for w in list(WOOD_TYPES) + ["nether_brick"]:
        states.append(f"minecraft:{w}_fence[waterlogged=false]")
        states.append(f"minecraft:{w}_fence[waterlogged=true]")
        for facing in HORIZONTAL_FACINGS:
            states.append(f"minecraft:{w}_fence_gate[facing={facing},in_wall=false,open=false,powered=false]")
            states.append(f"minecraft:{w}_fence_gate[facing={facing},in_wall=false,open=true,powered=false]")

    # 8. Containers & Utility Workstations
    for facing in HORIZONTAL_FACINGS:
        states.append(f"minecraft:chest[facing={facing},type=single,waterlogged=false]")
        states.append(f"minecraft:trapped_chest[facing={facing},type=single,waterlogged=false]")
        states.append(f"minecraft:ender_chest[facing={facing},waterlogged=false]")
        for is_lit in ("false", "true"):
            states.append(f"minecraft:furnace[facing={facing},lit={is_lit}]")
            states.append(f"minecraft:blast_furnace[facing={facing},lit={is_lit}]")
            states.append(f"minecraft:smoker[facing={facing},lit={is_lit}]")
        for is_open in ("false", "true"):
            states.append(f"minecraft:barrel[facing={facing},open={is_open}]")
        states.append(f"minecraft:anvil[facing={facing}]")
        states.append(f"minecraft:chipped_anvil[facing={facing}]")
        states.append(f"minecraft:damaged_anvil[facing={facing}]")
        states.append(f"minecraft:lectern[facing={facing},has_book=false,powered=false]")
        states.append(f"minecraft:stonecutter[facing={facing}]")
        states.append(f"minecraft:grindstone[face=floor,facing={facing}]")

    # 9. Vertical-base and Mechanical Blocks (Observer, Pistons, Dropper, Dispenser, Crafter)
    for facing in SIX_FACINGS:
        states.append(f"minecraft:observer[facing={facing},powered=false]")
        states.append(f"minecraft:observer[facing={facing},powered=true]")
        states.append(f"minecraft:piston[facing={facing},extended=false]")
        states.append(f"minecraft:sticky_piston[facing={facing},extended=false]")
        states.append(f"minecraft:piston[facing={facing},extended=true]")
        states.append(f"minecraft:sticky_piston[facing={facing},extended=true]")
        states.append(f"minecraft:dispenser[facing={facing},triggered=false]")
        states.append(f"minecraft:dropper[facing={facing},triggered=false]")
        states.append(f"minecraft:crafter[crafting=false,orientation={facing}_up,powered=false,triggered=false]")

    states.append("minecraft:crafting_table")
    states.append("minecraft:enchanting_table")
    states.append("minecraft:brewing_stand[has_bottle_0=false,has_bottle_1=false,has_bottle_2=false]")
    states.append("minecraft:cauldron")
    states.append("minecraft:water_cauldron[level=3]")
    states.append("minecraft:lava_cauldron")
    states.append("minecraft:beacon")

    # 10. Beds & Carpets (All 16 Colors)
    for col in COLORS:
        for facing in HORIZONTAL_FACINGS:
            states.append(f"minecraft:{col}_bed[facing={facing},occupied=false,part=foot]")
            states.append(f"minecraft:{col}_bed[facing={facing},occupied=false,part=head]")
        states.append(f"minecraft:{col}_carpet")
        states.append(f"minecraft:{col}_wool")
        states.append(f"minecraft:{col}_concrete")
        states.append(f"minecraft:{col}_stained_glass")
        states.append(f"minecraft:{col}_terracotta")

    # 11. Redstone Components
    for facing in HORIZONTAL_FACINGS:
        for delay in (1, 2, 4):
            for powered in ("false", "true"):
                states.append(f"minecraft:repeater[delay={delay},facing={facing},locked=false,powered={powered}]")
        for mode in ("compare", "subtract"):
            for powered in ("false", "true"):
                states.append(f"minecraft:comparator[facing={facing},mode={mode},powered={powered}]")
        for face in ("floor", "wall", "ceiling"):
            for powered in ("false", "true"):
                states.append(f"minecraft:lever[face={face},facing={facing},powered={powered}]")
        states.append(f"minecraft:tripwire_hook[attached=false,facing={facing},powered=false]")

    for p in (0, 1, 7, 15):
        states.append(f"minecraft:redstone_wire[power={p}]")
    states.append("minecraft:redstone_block")
    states.append("minecraft:redstone_lamp[lit=false]")
    states.append("minecraft:redstone_lamp[lit=true]")
    states.append("minecraft:daylight_detector[inverted=false,power=0]")
    states.append("minecraft:daylight_detector[inverted=true,power=0]")
    states.append("minecraft:target[power=0]")

    # 12. Rails
    for shape in ("north_south", "east_west"):
        states.append(f"minecraft:rail[shape={shape},waterlogged=false]")
        states.append(f"minecraft:powered_rail[powered=false,shape={shape},waterlogged=false]")
        states.append(f"minecraft:powered_rail[powered=true,shape={shape},waterlogged=false]")
        states.append(f"minecraft:detector_rail[powered=false,shape={shape},waterlogged=false]")
        states.append(f"minecraft:activator_rail[powered=false,shape={shape},waterlogged=false]")

    # 13. Flora, Crops, & Foliage
    flora = [
        "minecraft:short_grass", "minecraft:tall_grass[half=lower]", "minecraft:tall_grass[half=upper]",
        "minecraft:fern", "minecraft:large_fern[half=lower]", "minecraft:large_fern[half=upper]",
        "minecraft:dandelion", "minecraft:poppy", "minecraft:blue_orchid", "minecraft:allium",
        "minecraft:azure_bluet", "minecraft:red_tulip", "minecraft:orange_tulip", "minecraft:white_tulip",
        "minecraft:pink_tulip", "minecraft:oxeye_daisy", "minecraft:cornflower", "minecraft:lily_of_the_valley",
        "minecraft:wither_rose", "minecraft:sunflower[half=lower]", "minecraft:lilac[half=lower]",
        "minecraft:rose_bush[half=lower]", "minecraft:peony[half=lower]", "minecraft:dead_bush",
        "minecraft:sugar_cane[age=0]", "minecraft:bamboo[age=0,leaves=none,stage=0]", "minecraft:cactus[age=0]",
        "minecraft:lily_pad", "minecraft:sweet_berry_bush[age=3]", "minecraft:nether_wart[age=3]",
    ]
    states.extend(flora)
    for age in (0, 3, 7):
        states.append(f"minecraft:wheat[age={age}]")
        states.append(f"minecraft:carrots[age={age}]")
        states.append(f"minecraft:potatoes[age={age}]")
    for age in (0, 2, 3):
        states.append(f"minecraft:beetroots[age={age}]")

    # Deduplicate preserving insertion order
    seen = set()
    result = []
    for s in states:
        if s not in seen:
            seen.add(s)
            result.append(s)

    return tuple(result)


# Cached singleton tuple of all ~1200 high-priority hot states
HOT_PREWARM_STATES: tuple[str, ...] = generate_hot_prewarm_states()

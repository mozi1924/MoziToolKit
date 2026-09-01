"""
Block state classification, rotation calculation, and Atlas material ID resolver.
Designed for ultra-fast Point Cloud attribute evaluation in Blender Geometry Nodes.
"""

from __future__ import annotations
import math
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, Union

class BlockTypeEnum:
    CUBE = 0          # Standard full 1x1x1 cube (dirt, stone, planks, ores, glass, etc.)
    CROSS_PLANT = 1   # X-shaped cross planes (flowers, tall grass, saplings, crops)
    SLAB = 2          # Half-block slab (bottom, top, double)
    STAIRS = 3        # Stairs (straight, inner, outer)
    TORCH = 4         # Torch, wall torch, lantern
    PROP_TEMPLATE = 5 # Pick instance from MC_Block_Templates Collection (doors, beds, chests, etc.)
    PROP = 5          # Alias for PROP_TEMPLATE
    FLUID = 6         # Water and Lava surface planes
    AIR = 7           # Air (skipped)

from ..materials.constants import (
    AIR_BLOCKS,
    FLUID_BLOCKS,
    TRANSPARENT_BLOCKS,
    EMISSIVE_BLOCKS,
)


# Cross Plant blocks (rendered with X-shaped quad)
CROSS_PLANTS = frozenset({
    "minecraft:short_grass", "minecraft:tall_grass", "minecraft:fern", "minecraft:large_fern",
    "minecraft:dandelion", "minecraft:poppy", "minecraft:blue_orchid", "minecraft:allium",
    "minecraft:azure_bluet", "minecraft:red_tulip", "minecraft:orange_tulip", "minecraft:white_tulip",
    "minecraft:pink_tulip", "minecraft:oxeye_daisy", "minecraft:cornflower", "minecraft:lily_of_the_valley",
    "minecraft:wither_rose", "minecraft:sunflower", "minecraft:lilac", "minecraft:rose_bush",
    "minecraft:peony", "minecraft:dead_bush", "minecraft:sapling", "minecraft:wheat",
    "minecraft:carrots", "minecraft:potatoes", "minecraft:beetroots", "minecraft:sweet_berry_bush",
    "minecraft:nether_wart", "minecraft:crimson_roots", "minecraft:warped_roots",
    "short_grass", "tall_grass", "fern", "large_fern", "dandelion", "poppy", "blue_orchid",
    "allium", "azure_bluet", "red_tulip", "orange_tulip", "white_tulip", "pink_tulip",
    "oxeye_daisy", "cornflower", "lily_of_the_valley", "wither_rose", "sunflower",
    "lilac", "rose_bush", "peony", "dead_bush", "sapling", "wheat", "carrots",
    "potatoes", "beetroots", "sweet_berry_bush", "nether_wart", "crimson_roots", "warped_roots",
})

# Skulls and Heads (Entity models)
SKULL_HEAD_BLOCKS = frozenset({
    "player_head", "player_wall_head",
    "zombie_head", "zombie_wall_head",
    "creeper_head", "creeper_wall_head",
    "dragon_head", "dragon_wall_head",
    "piglin_head", "piglin_wall_head",
    "skeleton_skull", "skeleton_wall_skull",
    "wither_skeleton_skull", "wither_skeleton_wall_skull",
})

# Biome Tint categories for Minecraft block states
BIOME_TINT_GRASS = frozenset({
    "minecraft:grass_block", "minecraft:short_grass", "minecraft:tall_grass",
    "minecraft:fern", "minecraft:large_fern", "minecraft:sugar_cane",
    "minecraft:potted_fern", "minecraft:bush", "minecraft:pink_petals", "minecraft:wildflowers",
    "grass_block", "short_grass", "tall_grass", "fern", "large_fern", "sugar_cane",
    "potted_fern", "bush", "pink_petals", "wildflowers",
})
BIOME_TINT_FOLIAGE = frozenset({
    "minecraft:oak_leaves", "minecraft:jungle_leaves", "minecraft:acacia_leaves",
    "minecraft:dark_oak_leaves", "minecraft:mangrove_leaves", "minecraft:vine",
    "minecraft:leaf_litter",
    "oak_leaves", "jungle_leaves", "acacia_leaves", "dark_oak_leaves", "mangrove_leaves", "vine",
    "leaf_litter",
})
BIOME_TINT_WATER = frozenset({
    "minecraft:water", "minecraft:flowing_water", "minecraft:water_cauldron",
    "water", "flowing_water", "water_cauldron",
})

HARDCODED_TINTS = {
    "spruce_leaves": (0.38039, 0.60000, 0.38039, 1.0),
    "birch_leaves": (0.50196, 0.65490, 0.33333, 1.0),
    "lily_pad": (0.12549, 0.50196, 0.18824, 1.0),
    "attached_melon_stem": (0.8784, 0.7804, 0.1098, 1.0),
    "attached_pumpkin_stem": (0.8784, 0.7804, 0.1098, 1.0),
    "melon_stem": (0.8784, 0.7804, 0.1098, 1.0),
    "pumpkin_stem": (0.8784, 0.7804, 0.1098, 1.0),
}

DYE_COLORS_RGB: dict[str, tuple[float, float, float, float]] = {
    "white": (0.976, 0.976, 0.976, 1.0),
    "orange": (0.976, 0.502, 0.114, 1.0),
    "magenta": (0.780, 0.306, 0.741, 1.0),
    "light_blue": (0.227, 0.702, 0.855, 1.0),
    "yellow": (0.996, 0.847, 0.239, 1.0),
    "lime": (0.502, 0.780, 0.122, 1.0),
    "pink": (0.953, 0.545, 0.667, 1.0),
    "gray": (0.278, 0.310, 0.322, 1.0),
    "light_gray": (0.616, 0.616, 0.592, 1.0),
    "cyan": (0.086, 0.612, 0.612, 1.0),
    "purple": (0.537, 0.196, 0.722, 1.0),
    "blue": (0.235, 0.267, 0.667, 1.0),
    "brown": (0.514, 0.329, 0.196, 1.0),
    "green": (0.369, 0.486, 0.086, 1.0),
    "red": (0.690, 0.180, 0.149, 1.0),
    "black": (0.114, 0.114, 0.129, 1.0),
}

from ..mc_baker.state_baker import EMISSIVE_BLOCKS, is_block_emissive


class ParsedBlock:
    __slots__ = (
        'full_state', 'block_id', 'namespace', 'name', 'props',
        'block_type', 'template_name', 'rot_euler', 'offset',
        'tint_color', 'tint_data', 'is_waterlogged', 'is_opaque',
        'is_emissive', 'emissive_level'
    )

    def __init__(
        self,
        full_state: str,
        block_id: str,
        namespace: str,
        name: str,
        props: dict[str, str],
        block_type: int,
        template_name: str,
        rot_euler: tuple[float, float, float],
        offset: tuple[float, float, float],
        tint_color: tuple[float, float, float, float],
        tint_data: tuple[float, float, float, float],
        is_waterlogged: bool,
        is_opaque: int = 1,
        is_emissive: int = 0,
        emissive_level: float = 0.0,
    ):
        self.full_state = full_state
        self.block_id = block_id
        self.namespace = namespace
        self.name = name
        self.props = props
        self.block_type = block_type
        self.template_name = template_name
        self.rot_euler = rot_euler
        self.offset = offset
        self.tint_color = tint_color
        self.tint_data = tint_data
        self.is_waterlogged = is_waterlogged
        self.is_opaque = is_opaque
        self.is_emissive = is_emissive
        self.emissive_level = emissive_level

    @property
    def is_air(self) -> bool:
        return self.block_type == BlockTypeEnum.AIR


# In-memory parsing cache to avoid re-parsing identical state strings (bounded to avoid unbounded memory growth)
MAX_STATE_PARSE_CACHE_SIZE = 4096
_STATE_PARSE_CACHE: dict[str, ParsedBlock] = {}


def clear_parse_cache() -> None:
    """Clear the in-memory block state parsing cache."""
    _STATE_PARSE_CACHE.clear()


def _cache_parsed_block(key: str, parsed: ParsedBlock) -> ParsedBlock:
    if len(_STATE_PARSE_CACHE) >= MAX_STATE_PARSE_CACHE_SIZE:
        _STATE_PARSE_CACHE.clear()
    _STATE_PARSE_CACHE[key] = parsed
    return parsed


def atlas_lookup_keys(parsed_or_name: Union[ParsedBlock, str], props: Optional[Dict[str, str]] = None) -> tuple[str, ...]:
    """Return the mapping keys which can represent this exact block state.

    Resolves state-specific variants (doors, lit furnaces/lamps/torches, snowy grass,
    honey levels, respawn charges, crop ages, etc.) before falling back to base block names.
    Supports both ParsedBlock instances and (block_name, props) argument formats.
    """
    if isinstance(parsed_or_name, str):
        if props is not None:
            prop_str = ",".join(f"{k}={v}" for k, v in sorted(props.items()))
            state_str = f"{parsed_or_name}[{prop_str}]" if prop_str else parsed_or_name
            parsed = parse_and_classify(state_str)
        else:
            parsed = parse_and_classify(parsed_or_name)
    else:
        parsed = parsed_or_name

    keys: list[str] = []
    name = parsed.name
    p = parsed.props

    if name.endswith("_door"):
        half = p.get("half", "lower")
        keys.append(f"{name}_{'top' if half == 'upper' else 'bottom'}")

    is_lit = p.get("lit") == "true"
    if is_lit:
        if name in ("furnace", "blast_furnace", "smoker"):
            keys.append(f"{name}[lit=true]")
            keys.append(f"{name}_lit")
            keys.append(f"{name}_front_on")
        elif name == "redstone_lamp":
            keys.append("redstone_lamp[lit=true]")
            keys.append("redstone_lamp_on")
        elif name in ("redstone_torch", "redstone_wall_torch"):
            keys.append(f"{name}[lit=true]")
            keys.append("redstone_torch")
        elif name in ("campfire", "soul_campfire"):
            keys.append(f"{name}[lit=true]")
            keys.append(f"{name}_fire")
    else:
        if name in ("furnace", "blast_furnace", "smoker"):
            keys.append(f"{name}[lit=false]")
        elif name in ("redstone_torch", "redstone_wall_torch"):
            keys.append(f"{name}[lit=false]")
            keys.append("redstone_torch_off")
        elif name == "redstone_lamp":
            keys.append("redstone_lamp[lit=false]")
            keys.append("redstone_lamp")
        elif name in ("campfire", "soul_campfire"):
            keys.append(f"{name}[lit=false]")
            keys.append(f"{name}_log")

    if name in ("beehive", "bee_nest") and p.get("honey_level") == "5":
        keys.append(f"{name}[honey_level=5]")
        keys.append(f"{name}_front_honey")

    if name == "respawn_anchor" and "charges" in p:
        charges = p.get("charges", "0")
        keys.append(f"respawn_anchor[charges={charges}]")
        if charges == "0":
            keys.append("respawn_anchor_top_off")
        else:
            keys.append("respawn_anchor_top")
            keys.append(f"respawn_anchor_side{charges}")

    if "age" in p:
        age_val = p["age"]
        if name == "wheat":
            keys.append(f"wheat_stage{age_val}")
        elif name in ("carrots", "potatoes", "beetroots", "sweet_berry_bush"):
            keys.append(f"{name}_stage{age_val}")
        elif name == "nether_wart":
            keys.append(f"nether_wart_stage{age_val}")
        elif name == "cocoa":
            keys.append(f"cocoa_stage{age_val}")

    if p.get("snowy") == "true" and name in ("grass_block", "podzol", "mycelium"):
        keys.append("grass_block_snow")

    if name in ("chest", "trapped_chest", "ender_chest"):
        c_type = p.get("type", "single")
        c_stem = "normal" if name == "chest" else ("trapped" if name == "trapped_chest" else "ender")
        if c_type in ("left", "right") and name != "ender_chest":
            keys.append(f"minecraft:entity/chest/{c_stem}_{c_type}")
            keys.append(f"entity/chest/{c_stem}_{c_type}")
        keys.append(f"minecraft:entity/chest/{c_stem}")
        keys.append(f"entity/chest/{c_stem}")
        keys.append("minecraft:block/oak_planks")

    if name.endswith("_banner") or name.endswith("_wall_banner"):
        color = name.replace("_wall_banner", "").replace("_banner", "")
        keys.append("minecraft:entity/banner/banner_base")
        keys.append("entity/banner/banner_base")
        keys.append("minecraft:entity/banner/base")
        keys.append("entity/banner/base")
        keys.append(f"minecraft:block/{color}_wool" if color else "minecraft:block/white_wool")
        keys.append("minecraft:block/oak_planks")

    if name in ("end_portal", "end_gateway"):
        keys.append("minecraft:entity/end_portal")
        keys.append("entity/end_portal")
        keys.append("minecraft:entity/end_portal/end_portal")
        keys.append("entity/end_portal/end_portal")

    if name in SKULL_HEAD_BLOCKS:
        head_type = name.replace("_wall_", "_").removesuffix("_skull").removesuffix("_head")
        if head_type == "skeleton":
            keys.extend(["minecraft:entity/skeleton/skeleton", "entity/skeleton/skeleton"])
        elif head_type == "wither_skeleton":
            keys.extend(["minecraft:entity/skeleton/wither_skeleton", "entity/skeleton/wither_skeleton"])
        elif head_type == "zombie":
            keys.extend(["minecraft:entity/zombie/zombie", "entity/zombie/zombie"])
        elif head_type == "creeper":
            keys.extend(["minecraft:entity/creeper/creeper", "entity/creeper/creeper"])
        elif head_type == "piglin":
            keys.extend(["minecraft:entity/piglin/piglin", "entity/piglin/piglin"])
        elif head_type == "dragon":
            keys.extend(["minecraft:entity/enderdragon/dragon", "entity/enderdragon/dragon"])
        elif head_type == "player":
            keys.extend(["minecraft:entity/player/wide/steve", "entity/player/wide/steve", "minecraft:entity/steve", "entity/steve"])

    if name == "conduit":
        keys.extend(["minecraft:entity/conduit/base", "entity/conduit/base"])

    if name == "decorated_pot":
        keys.extend(["minecraft:entity/decorated_pot/decorated_pot_base", "entity/decorated_pot/decorated_pot_base"])

    if name.endswith("_shulker_box") or name == "shulker_box":
        color = name.removesuffix("_shulker_box")
        if color == "shulker_box" or not color:
            keys.extend(["minecraft:entity/shulker/shulker", "entity/shulker/shulker"])
        else:
            keys.extend([f"minecraft:entity/shulker/shulker_{color}", f"entity/shulker/shulker_{color}", "minecraft:entity/shulker/shulker", "entity/shulker/shulker"])

    if name.endswith("_bed") or name == "bed":
        color = name.removesuffix("_bed") if name.endswith("_bed") else "white"
        keys.extend([f"minecraft:entity/bed/{color}", f"entity/bed/{color}", f"minecraft:block/{color}_wool"])

    keys.extend((name, parsed.block_id, f"minecraft:{name}"))
    return tuple(dict.fromkeys(keys))


def parse_and_classify(state_str: str) -> ParsedBlock:
    """Parse serialized block state string into structured Geometry Nodes attributes."""
    if not state_str:
        return _make_air("")

    if state_str in _STATE_PARSE_CACHE:
        return _STATE_PARSE_CACHE[state_str]

    state_str_clean = state_str.strip()
    if state_str_clean.startswith("{") and state_str_clean.endswith("}"):
        import json
        json_obj = None
        try:
            json_obj = json.loads(state_str_clean)
        except Exception:
            json_obj = None

        if json_obj and isinstance(json_obj, dict):
            raw_state = json_obj.get("state", "")
            base_parsed = parse_and_classify(raw_state) if raw_state else _make_air("")
            # Create clone or update fields
            b_type = int(json_obj["type"]) if "type" in json_obj else base_parsed.block_type
            is_op = int(json_obj["opaque"]) if "opaque" in json_obj else base_parsed.is_opaque
            is_em = int(json_obj["emissive"]) if "emissive" in json_obj else base_parsed.is_emissive
            em_lvl = float(json_obj["emissive_level"]) if "emissive_level" in json_obj else base_parsed.emissive_level

            parsed = ParsedBlock(
                full_state=base_parsed.full_state or raw_state,
                block_id=base_parsed.block_id,
                namespace=base_parsed.namespace,
                name=base_parsed.name,
                props=base_parsed.props,
                block_type=b_type,
                template_name=base_parsed.template_name,
                rot_euler=base_parsed.rot_euler,
                offset=base_parsed.offset,
                tint_color=base_parsed.tint_color,
                tint_data=base_parsed.tint_data,
                is_waterlogged=base_parsed.is_waterlogged,
                is_opaque=is_op,
                is_emissive=is_em,
                emissive_level=em_lvl,
            )
            return _cache_parsed_block(state_str, parsed)

    bracket_idx = state_str_clean.find("[")
    if bracket_idx == -1:
        block_id = state_str_clean
        props = {}
    else:
        block_id = state_str_clean[:bracket_idx]
        props_str = state_str_clean[bracket_idx + 1:].rstrip("]")
        props = {}
        if props_str:
            for pair in props_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    props[k.strip()] = v.strip()

    if ":" in block_id:
        namespace, name = block_id.split(":", 1)
    else:
        namespace, name = "minecraft", block_id
        block_id = f"minecraft:{name}"

    if block_id in AIR_BLOCKS:
        parsed = _make_air(state_str_clean)
        return _cache_parsed_block(state_str, parsed)

    # 1. Determine Biome Tint & Hardcoded Tints
    snowy = props.get("snowy") == "true"
    if name in HARDCODED_TINTS:
        tint_color = HARDCODED_TINTS[name]
        tint_data = (1.0, 1.0, 1.0, 4.0)
    elif name.endswith("_banner") or name.endswith("_wall_banner"):
        color = name.replace("_wall_banner", "").replace("_banner", "")
        tint_color = DYE_COLORS_RGB.get(color, (1.0, 1.0, 1.0, 1.0))
        tint_data = (1.0, 1.0, 1.0, 4.0)
    elif name == "redstone_wire":
        power = int(props.get("power", "0")) if "power" in props else 0
        t = power / 15.0
        r = 0.3 + 0.7 * t
        g = 0.0 if power == 0 else 0.15 * t
        tint_color = (r, g, 0.0, 1.0)
        tint_data = (1.0, 1.0, 1.0, 4.0)
    elif snowy and name in ("grass_block", "podzol", "mycelium"):
        tint_color = (1.0, 1.0, 1.0, 1.0)
        tint_data = (0.0, 0.0, 0.0, 0.0)
    elif block_id in BIOME_TINT_GRASS or name in BIOME_TINT_GRASS:
        tint_color = (0.28, 0.50, 0.10, 1.0)
        tint_data = (1.0, 1.0, 1.0, 1.0)
    elif block_id in BIOME_TINT_FOLIAGE or name in BIOME_TINT_FOLIAGE or (name.endswith("_leaves") and not any(w in name for w in ("cherry", "azalea", "pale_oak", "spruce", "birch"))):
        tint_color = (0.18, 0.41, 0.03, 1.0)
        tint_data = (1.0, 1.0, 1.0, 2.0)
    elif block_id in BIOME_TINT_WATER or "water" in block_id or name in BIOME_TINT_WATER:
        tint_color = (0.05, 0.17, 0.77, 0.8)
        tint_data = (1.0, 1.0, 1.0, 3.0)
    else:
        tint_color = (1.0, 1.0, 1.0, 1.0)
        tint_data = (0.0, 0.0, 0.0, 0.0)

    # 2. Check Waterlogged
    is_waterlogged = (
        props.get("waterlogged", "false") == "true"
        or name in ("seagrass", "tall_seagrass", "kelp", "kelp_plant")
    )

    # 3. Determine Emissive Status and Level
    is_emissive = 1 if is_block_emissive(name, props) or is_block_emissive(block_id, props) else 0
    emissive_level = 1.0 if is_emissive else 0.0
    if name == "respawn_anchor":
        charges = int(props.get("charges", "0")) if "charges" in props else 0
        emissive_level = charges / 4.0 if charges > 0 else 0.0
    elif name == "redstone_wire":
        power = int(props.get("power", "0")) if "power" in props else 0
        emissive_level = power / 15.0 if power > 0 else 0.0

    # 4. Determine Block Type, Rotation & Template Name
    rot_x, rot_y, rot_z = 0.0, 0.0, 0.0
    off_x, off_y, off_z = 0.0, 0.0, 0.0
    facing = props.get("facing", "north")
    axis = props.get("axis", "y")

    if name in ("piston", "sticky_piston", "piston_head", "barrel", "command_block", "chain_command_block", "repeating_command_block"):
        # Vertical-base blocks (Base template naturally points UP at +Z in Blender)
        if facing == "up":
            rot_x, rot_y, rot_z = 0.0, 0.0, 0.0
        elif facing == "down":
            rot_x, rot_y, rot_z = math.radians(180), 0.0, 0.0
        elif facing == "north":
            rot_x, rot_y, rot_z = math.radians(-90), 0.0, 0.0
        elif facing == "south":
            rot_x, rot_y, rot_z = math.radians(90), 0.0, 0.0
        elif facing == "west":
            rot_x, rot_y, rot_z = 0.0, math.radians(-90), 0.0
        elif facing == "east":
            rot_x, rot_y, rot_z = 0.0, math.radians(90), 0.0
    elif "axis" in props or name.endswith(("_log", "_wood", "_stem", "_hyphae", "basalt", "hay_block", "bone_block")):
        # Axis-aligned blocks (Logs, Pillars, Basalt, Hay, Bone)
        if axis == "x":
            rot_y = math.radians(90)
        elif axis == "z":
            rot_x = math.radians(-90)
        else:
            rot_x, rot_y, rot_z = 0.0, 0.0, 0.0
    else:
        # Standard horizontal-base blocks (Base template points NORTH at +Y in Blender: furnace, dispenser, dropper, observer, etc.)
        if facing == "north":
            rot_z = 0.0
        elif facing == "south":
            rot_z = math.radians(180)
        elif facing == "east":
            rot_z = math.radians(-90)
        elif facing == "west":
            rot_z = math.radians(90)
        elif facing == "up":
            rot_x = math.radians(90)
        elif facing == "down":
            rot_x = math.radians(-90)

    if block_id in FLUID_BLOCKS:
        block_type = BlockTypeEnum.FLUID
        template_name = "fluid_plane"

    elif block_id in CROSS_PLANTS or name.endswith("_sapling") or name.endswith("_flower") or name in ("wheat", "carrots", "potatoes", "beetroots", "sweet_berry_bush", "nether_wart", "cocoa"):
        block_type = BlockTypeEnum.CROSS_PLANT
        template_name = "cross_plant"

    elif name.endswith("_stairs"):
        block_type = BlockTypeEnum.STAIRS
        template_name = name
        half = props.get("half", "bottom")
        if half == "top":
            rot_x = math.radians(180)
            rot_z = -rot_z

    elif name.endswith("_slab"):
        slab_type = props.get("type", "bottom")
        if slab_type == "double":
            block_type = BlockTypeEnum.CUBE
            template_name = "cube"
        else:
            block_type = BlockTypeEnum.SLAB
            template_name = name
            if slab_type == "top":
                off_z = 0.5

    elif "torch" in name or name in ("lantern", "soul_lantern"):
        block_type = BlockTypeEnum.TORCH
        template_name = name
        if "wall" in name or ("torch" in name and facing in ("north", "south", "east", "west")):
            rot_x = math.radians(-22.5)

    elif (
        name.endswith((
            "_bed", "_door", "_trapdoor", "_fence", "_fence_gate", "_wall",
            "_carpet", "_chest", "_bell", "_anvil", "_sign", "_wall_sign",
            "_hanging_sign", "_wall_hanging_sign", "_banner", "_wall_banner",
            "_head", "_wall_head", "_skull", "_wall_skull", "_shulker_box",
            "_candle", "_cake", "_pot", "_rod", "_coral", "_fan", "_chain",
        ))
        or name in (
            "chest", "trapped_chest", "ender_chest", "bell", "anvil", "bed",
            "carpet", "trapdoor", "shulker_box", "conduit", "decorated_pot",
            "end_portal_frame", "end_portal", "end_gateway", "chain", "iron_chain",
            "copper_chain", "exposed_copper_chain", "weathered_copper_chain", "oxidized_copper_chain",
            "cauldron", "hopper", "brewing_stand", "lectern", "grindstone", "stonecutter",
            "lever", "tripwire_hook", "repeater", "comparator", "daylight_detector",
            "lightning_rod", "end_rod", "dragon_egg", "flower_pot"
        )
    ):
        block_type = BlockTypeEnum.PROP_TEMPLATE
        template_name = name
        if name.endswith("_bed"):
            part = props.get("part", "foot")
            template_name = f"{name}_{part}"
        elif name.endswith("_door"):
            half = props.get("half", "lower")
            template_name = f"{name}_{half}"
        elif name.endswith("_carpet"):
            off_z = -0.46875

    else:
        # Standard Cube (including glazed terracotta, mushroom blocks, etc.)
        block_type = BlockTypeEnum.CUBE
        template_name = "cube"

    # Determine opacity: only non-transparent full cubes can be opaque
    if (
        block_type != BlockTypeEnum.CUBE
        or block_id in TRANSPARENT_BLOCKS
        or name.endswith(("_glass", "_stained_glass", "_leaves", "_pane"))
        or name in ("glass", "tinted_glass", "ice", "water", "slime_block", "honey_block", "beacon")
    ):
        is_opaque = 0
    else:
        is_opaque = 1

    parsed = ParsedBlock(
        full_state=state_str_clean,
        block_id=block_id,
        namespace=namespace,
        name=name,
        props=props,
        block_type=block_type,
        template_name=template_name,
        rot_euler=(rot_x, rot_y, rot_z),
        offset=(off_x, off_y, off_z),
        tint_color=tint_color,
        tint_data=tint_data,
        is_waterlogged=is_waterlogged,
        is_opaque=is_opaque,
        is_emissive=is_emissive,
        emissive_level=emissive_level,
    )
    return _cache_parsed_block(state_str, parsed)


def _make_air(state_str: str) -> ParsedBlock:
    return ParsedBlock(
        full_state=state_str,
        block_id="minecraft:air",
        namespace="minecraft",
        name="air",
        props={},
        block_type=BlockTypeEnum.AIR,
        template_name="air",
        rot_euler=(0.0, 0.0, 0.0),
        offset=(0.0, 0.0, 0.0),
        tint_color=(1.0, 1.0, 1.0, 1.0),
        tint_data=(0.0, 0.0, 0.0, 0.0),
        is_waterlogged=False,
        is_opaque=0,
        is_emissive=0,
        emissive_level=0.0,
    )


def classify_block_type_and_orientation(
    state_str: str,
    template_catalog: Optional[Any] = None,
) -> Tuple[int, Tuple[float, float, float], int]:
    """Helper: Classifies block type, rotation euler angles, and template index."""
    parsed = parse_and_classify(state_str)
    template_idx = 0
    if parsed.template_name:
        try:
            if template_catalog is not None:
                if hasattr(template_catalog, "get_index"):
                    return parsed.block_type, parsed.rot_euler, template_catalog.get_index(parsed.template_name)
                col = template_catalog if hasattr(template_catalog, "objects") else None
            else:
                import bpy
                from .template_catalog import get_or_create_template_collection
                col = get_or_create_template_collection() if (hasattr(bpy, "data") and hasattr(bpy.data, "collections")) else None
            if col:
                from .template_catalog import get_template_index_map
                idx_map = get_template_index_map(col)
                template_idx = idx_map.get(parsed.template_name, 0)
        except Exception:
            template_idx = 0
    return parsed.block_type, parsed.rot_euler, template_idx


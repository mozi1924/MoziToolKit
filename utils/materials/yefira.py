"""
Yefira Procedural Point-Cloud Material and Geometry Nodes Integration Module.

Provides object detection, attribute mapping, atlas slot configuration,
and Geometry Nodes notification for Yefira-based procedural Minecraft worlds.
"""

from __future__ import annotations

import sys
from typing import Iterable, Optional
import bpy

from .constants import (
    ATTR_UV_ROTATION,
    ATTR_UV_TILING_TRANSFORM,
)
from pathlib import Path
from ..mc_baker import StateBaker

DEFAULT_CLIENT_JAR = "/Users/jaxlocke/26.2-Fabric.jar"
_GLOBAL_STATE_BAKER = StateBaker(
    jar_path=DEFAULT_CLIENT_JAR if Path(DEFAULT_CLIENT_JAR).exists() else None
)


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
    "observer": ["observer_front", "observer_back", "observer_top", "observer_side"],
    "piston": ["piston_top", "piston_bottom", "piston_side"],
    "sticky_piston": ["piston_top_sticky", "piston_bottom", "piston_side"],
    "barrel": ["barrel_top", "barrel_bottom", "barrel_side", "barrel_top_open"],
    "beehive": ["beehive_front", "beehive_front_honey", "beehive_side", "beehive_top", "beehive_bottom"],
    "bee_nest": ["bee_nest_front", "bee_nest_front_honey", "bee_nest_side", "bee_nest_top", "bee_nest_bottom"],
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

EMISSIVE_BLOCK_NAMES = frozenset({
    "glowstone", "sea_lantern", "shroomlight", "magma_block", "magma",
    "crying_obsidian", "jack_o_lantern", "beacon", "end_rod",
    "lantern", "soul_lantern", "torch", "soul_torch", "wall_torch", "soul_wall_torch",
    "lava", "flowing_lava", "fire", "soul_fire", "conduit", "sculk_catalyst",
})

HARDCODED_TINT_BLOCKS = {
    "spruce_leaves": (1.0, 1.0, 1.0, 1.0),
    "birch_leaves": (1.0, 1.0, 1.0, 1.0),
    "lily_pad": (1.0, 1.0, 1.0, 1.0),
    "redstone_wire": (1.0, 1.0, 1.0, 1.0),
}


def parse_block_state_str(state: str) -> tuple[str, dict[str, str]]:
    """Parse a serialized block state string into clean block name and properties dict."""
    state_clean = state.strip()
    bracket_idx = state_clean.find("[")
    if bracket_idx == -1:
        block_name = state_clean
        props = {}
    else:
        block_name = state_clean[:bracket_idx]
        props_str = state_clean[bracket_idx + 1:].rstrip("]")
        props = {}
        if props_str:
            for pair in props_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    props[k.strip()] = v.strip()
    block_name = block_name.removeprefix("minecraft:").removeprefix("block/")
    return block_name, props


def is_block_emissive(block_name: str, props: dict[str, str]) -> int:
    """Return 1 if block/state is emissive (light emitting), else 0."""
    if block_name in EMISSIVE_BLOCK_NAMES or block_name.endswith("_froglight"):
        return 1
    is_lit = props.get("lit") == "true"
    if is_lit and (
        block_name in ("furnace", "blast_furnace", "smoker", "redstone_lamp",
                       "campfire", "soul_campfire", "redstone_ore", "deepslate_redstone_ore")
    ):
        return 1
    if block_name in ("redstone_torch", "redstone_wall_torch"):
        return 1 if props.get("lit", "true") == "true" else 0
    if block_name == "respawn_anchor":
        charges = int(props.get("charges", "0")) if "charges" in props else 0
        return 1 if charges > 0 else 0
    if block_name == "redstone_wire":
        power = int(props.get("power", "0")) if "power" in props else 0
        return 1 if power > 0 else 0
    return 0


def is_yefira_object(obj: Optional[bpy.types.Object]) -> bool:
    """Identify whether a Blender object is a Yefira procedural point-cloud world.

    An object is recognized as Yefira if:
    1. It is a MESH object named 'Yefira_World', or
    2. It has a Geometry Nodes modifier named 'Yefira_WorldModifier', or
    3. Its mesh data contains a point-domain 'block_state' or 'mc_pos' attribute.

    Polygonal meshes or other procedural objects lacking these markers remain
    standard MoziToolKit mesh objects.
    """
    if not obj or getattr(obj, "type", None) != 'MESH' or not getattr(obj, "data", None):
        return False
    if obj.name == "Yefira_World":
        return True
    if hasattr(obj, "modifiers") and any(
        mod.type == 'NODES' and (mod.name == 'Yefira_WorldModifier' or "yefira" in mod.name.lower())
        for mod in obj.modifiers
    ):
        return True
    mesh = obj.data
    if hasattr(mesh, "attributes"):
        state_attr = mesh.attributes.get("block_state")
        if state_attr and state_attr.domain == 'POINT':
            return True
        if "mc_pos" in mesh.attributes:
            return True
    return False


def has_yefira_objects(objects: Iterable[Optional[bpy.types.Object]]) -> bool:
    """Return True if any object in the given collection is a Yefira world."""
    return any(is_yefira_object(obj) for obj in objects if obj)


def write_yefira_point_atlas_attributes(mesh: bpy.types.Mesh, mapping: dict) -> None:
    """Fill Yefira's 6-direction face atlas attributes directly from Mozi's mapping.

    Writes the following POINT domain attributes:
    - ``mtk_material_id`` (INT)
    - ``mtk_is_opaque`` (INT)
    - ``is_opaque`` (INT)
    - ``mtk_emissive`` (INT)
    - ``mtk_tile_{face}`` (FLOAT_VECTOR for east, west, top, bottom, south, north)
    - ``mtk_chunk_{face}`` (INT)
    - ``mtk_texture_{face}`` (INT)
    - ``mtk_is_opaque_{face}`` (INT)
    - ``mtk_tint_data_{face}`` (FLOAT_COLOR: base_weight, overlay_weight, tint_weight, is_hardcoded)
    - ``mtk_anim_timing_{face}`` (FLOAT_COLOR: frame_count, frametime, interpolate, 0)
    - ``mtk_anim_frame_size_{face}`` (FLOAT_COLOR: frame_width, frame_height, 0, 0)
    """
    state_attr = mesh.attributes.get("block_state")
    if not state_attr or state_attr.domain != 'POINT':
        return

    by_name = {
        str(entry.get("name", "")).removeprefix("minecraft:").removeprefix("block/"): entry
        for entry in mapping.get("materials", [])
        if entry.get("name")
    }
    texture_locations = mapping.get("textures", {})

    def texture_location(block_name: str) -> dict:
        """Find a flat texture entry when a block model has no face table."""
        for key in (block_name, f"minecraft:{block_name}", f"minecraft:block/{block_name}"):
            location = texture_locations.get(key)
            if isinstance(location, dict):
                return location
        return {}

    def texture_only_faces(block_name: str, props: dict[str, str]) -> dict:
        """Derive standard cube faces from a texture-only atlas mapping and block state."""
        target_stems = BLOCK_TO_TEXTURE_ALIASES.get(block_name)
        is_lit = props.get("lit") == "true"
        snowy = props.get("snowy") == "true"
        axis = props.get("axis", "y")
        honey_level = props.get("honey_level", "0")
        charges = int(props.get("charges", "0")) if "charges" in props else 0

        # 1. Redstone Lamp
        if block_name == "redstone_lamp":
            lamp_tex = (texture_location("redstone_lamp_on") if is_lit else None) or texture_location("redstone_lamp")
            if lamp_tex:
                return {"+X": lamp_tex, "-X": lamp_tex, "+Y": lamp_tex, "-Y": lamp_tex, "+Z": lamp_tex, "-Z": lamp_tex}

        # 2. Snowy grass/podzol/mycelium
        if block_name in ("grass_block", "podzol", "mycelium"):
            snow_side = texture_location("grass_block_snow") if snowy else None
            top_tex = texture_location(f"{block_name}_top") or texture_location(block_name)
            dirt_tex = texture_location("dirt") or top_tex
            side_tex = snow_side or texture_location(f"{block_name}_side") or top_tex
            if top_tex or side_tex:
                return {"+X": side_tex, "-X": side_tex, "+Y": top_tex, "-Y": dirt_tex, "+Z": side_tex, "-Z": side_tex}

        # 3. Respawn anchor
        if block_name == "respawn_anchor":
            top_loc = texture_location("respawn_anchor_top_off") if charges == 0 else (texture_location("respawn_anchor_top") or texture_location("respawn_anchor_top_off"))
            side_loc = texture_location(f"respawn_anchor_side{charges}") or texture_location("respawn_anchor_side0") or texture_location("respawn_anchor_top_off")
            bottom_loc = texture_location("respawn_anchor_bottom") or side_loc
            return {"+X": side_loc, "-X": side_loc, "+Y": top_loc, "-Y": bottom_loc, "+Z": side_loc, "-Z": side_loc}

        # 4. Mushroom blocks (red_mushroom_block, brown_mushroom_block, mushroom_stem)
        if block_name in ("red_mushroom_block", "brown_mushroom_block", "mushroom_stem"):
            skin = texture_location(block_name)
            inside = texture_location("mushroom_block_inside") or skin
            top_tex = inside if props.get("up") == "false" else skin
            bottom_tex = inside if props.get("down") == "false" else skin
            north_tex = inside if props.get("north") == "false" else skin
            south_tex = inside if props.get("south") == "false" else skin
            east_tex = inside if props.get("east") == "false" else skin
            west_tex = inside if props.get("west") == "false" else skin
            return {"+X": east_tex, "-X": west_tex, "+Y": top_tex, "-Y": bottom_tex, "+Z": south_tex, "-Z": north_tex}

        # 5. Glazed Terracotta
        if block_name.endswith("_glazed_terracotta"):
            loc = texture_location(block_name)
            if loc:
                return {"+X": loc, "-X": loc, "+Y": loc, "-Y": loc, "+Z": loc, "-Z": loc}

        # 6. Axis-oriented blocks (logs, basalt, polished_basalt, hay_block, bone_block, wood/bark)
        is_axis_block = "axis" in props or block_name.endswith(("_log", "_wood", "_stem", "_hyphae", "basalt", "hay_block", "bone_block"))
        if is_axis_block:
            end_loc = (
                texture_location(f"{block_name}_top")
                or texture_location(f"{block_name}_end")
                or (texture_location(f"{block_name[:-4]}log_top") if block_name.endswith("_wood") else None)
                or (texture_location(f"{block_name[:-7]}stem_top") if block_name.endswith("_hyphae") else None)
                or texture_location(block_name)
            )
            side_loc = (
                texture_location(f"{block_name}_side")
                or (texture_location(f"{block_name[:-4]}log") if block_name.endswith("_wood") and not texture_location(block_name) else None)
                or (texture_location(f"{block_name[:-7]}stem") if block_name.endswith("_hyphae") and not texture_location(block_name) else None)
                or texture_location(block_name)
                or end_loc
            )
            if end_loc or side_loc:
                end_loc = end_loc or side_loc
                side_loc = side_loc or end_loc
                if axis == "x":
                    return {"+X": end_loc, "-X": end_loc, "+Y": side_loc, "-Y": side_loc, "+Z": side_loc, "-Z": side_loc}
                elif axis == "z":
                    return {"+X": side_loc, "-X": side_loc, "+Y": side_loc, "-Y": side_loc, "+Z": end_loc, "-Z": end_loc}
                else:
                    return {"+X": side_loc, "-X": side_loc, "+Y": end_loc, "-Y": end_loc, "+Z": side_loc, "-Z": side_loc}

        # 7. Directional / Horizontal blocks with aliases
        if target_stems:
            found_loc = next((texture_location(s) for s in target_stems if texture_location(s)), None)
            if found_loc:
                if is_lit and block_name in ("furnace", "blast_furnace", "smoker"):
                    front_loc = texture_location(f"{block_name}_front_on") or texture_location(f"{block_name}_front") or found_loc
                elif honey_level == "5" and block_name in ("beehive", "bee_nest"):
                    front_loc = texture_location(f"{block_name}_front_honey") or texture_location(f"{block_name}_front") or found_loc
                elif block_name in ("carved_pumpkin", "jack_o_lantern"):
                    front_loc = texture_location(block_name) or found_loc
                else:
                    front_loc = next((texture_location(s) for s in target_stems if s.endswith(("_front", "_front_on", "_front_honey"))), found_loc)

                top_loc = next((texture_location(s) for s in target_stems if s.endswith(("_top", "_top_off"))), None) or texture_location(f"{block_name}_top")
                bottom_loc = next((texture_location(s) for s in target_stems if s.endswith("_bottom")), None) or texture_location(f"{block_name}_bottom")
                back_loc = next((texture_location(s) for s in target_stems if s.endswith("_back")), None)
                side_loc = next((texture_location(s) for s in target_stems if s.endswith(("_side", "_side0"))), found_loc)

                actual_top = top_loc or found_loc
                actual_bottom = bottom_loc or (top_loc if block_name in ("furnace", "blast_furnace", "smoker", "dispenser", "dropper", "carved_pumpkin", "jack_o_lantern") else found_loc)
                actual_back = back_loc or side_loc
                actual_front = front_loc or found_loc

                if "command_block" in block_name:
                    return {"+X": side_loc, "-X": side_loc, "+Y": actual_front, "-Y": actual_back, "+Z": side_loc, "-Z": side_loc}
                elif "piston" in block_name:
                    return {"+X": side_loc, "-X": side_loc, "+Y": actual_top, "-Y": actual_bottom, "+Z": side_loc, "-Z": side_loc}
                elif block_name == "observer":
                    return {"+X": side_loc, "-X": side_loc, "+Y": actual_top, "-Y": side_loc, "+Z": actual_back, "-Z": actual_front}
                elif block_name == "barrel":
                    is_open = props.get("open") == "true"
                    b_top = (texture_location("barrel_top_open") if is_open else None) or actual_top
                    return {"+X": side_loc, "-X": side_loc, "+Y": b_top, "-Y": actual_bottom, "+Z": side_loc, "-Z": side_loc}
                else:
                    return {"+X": side_loc, "-X": side_loc, "+Y": actual_top, "-Y": actual_bottom, "+Z": actual_back, "-Z": actual_front}

        base = texture_location(block_name)
        side = texture_location(f"{block_name}_side") or base
        top = texture_location(f"{block_name}_top") or texture_location(f"{block_name}_end") or side
        bottom = texture_location(f"{block_name}_bottom") or texture_location(f"{block_name}_end") or top
        if block_name == "grass_block":
            bottom = texture_location("dirt") or bottom
        named_variants = any(
            texture_location(f"{block_name}{suffix}")
            for suffix in ("_side", "_top", "_bottom", "_end")
        )
        if not named_variants or not side or not top or not bottom:
            return {}
        return {"+X": side, "-X": side, "+Y": top, "-Y": bottom, "+Z": side, "-Z": side}

    def mapping_names(state: str) -> tuple[str, ...]:
        """Resolve stateful generated models before generic texture fallback."""
        block_name, props = parse_block_state_str(state)
        names = []
        if block_name.endswith("_door"):
            names.append(f"{block_name}_{'top' if props.get('half') == 'upper' else 'bottom'}")

        is_lit = props.get("lit") == "true"
        if is_lit:
            if block_name in ("furnace", "blast_furnace", "smoker"):
                names.append(f"{block_name}[lit=true]")
                names.append(f"{block_name}_front_on")
            elif block_name == "redstone_lamp":
                names.append("redstone_lamp[lit=true]")
                names.append("redstone_lamp_on")
            elif block_name in ("redstone_torch", "redstone_wall_torch"):
                names.append(f"{block_name}[lit=true]")
                names.append("redstone_torch")
            elif block_name == "campfire":
                names.append("campfire_fire")
            elif block_name == "soul_campfire":
                names.append("soul_campfire_fire")
        else:
            if block_name in ("furnace", "blast_furnace", "smoker"):
                names.append(f"{block_name}[lit=false]")
            elif block_name in ("redstone_torch", "redstone_wall_torch"):
                names.append(f"{block_name}[lit=false]")
                names.append("redstone_torch_off")
            elif block_name == "redstone_lamp":
                names.append("redstone_lamp[lit=false]")
                names.append("redstone_lamp")
            elif block_name in ("campfire", "soul_campfire"):
                names.append(f"{block_name}_log")

        if block_name in ("beehive", "bee_nest") and props.get("honey_level") == "5":
            names.append(f"{block_name}[honey_level=5]")
            names.append(f"{block_name}_front_honey")

        if block_name == "respawn_anchor" and "charges" in props:
            charges = props.get("charges", "0")
            names.append(f"respawn_anchor[charges={charges}]")
            if charges == "0":
                names.append("respawn_anchor_top_off")
            else:
                names.append("respawn_anchor_top")
                names.append(f"respawn_anchor_side{charges}")

        if "age" in props:
            age_val = props["age"]
            if block_name == "wheat":
                names.append(f"wheat_stage{age_val}")
            elif block_name in ("carrots", "potatoes", "beetroots", "sweet_berry_bush"):
                names.append(f"{block_name}_stage{age_val}")
            elif block_name == "nether_wart":
                names.append(f"nether_wart_stage{age_val}")
            elif block_name == "cocoa":
                names.append(f"cocoa_stage{age_val}")

        if props.get("snowy") == "true" and block_name in ("grass_block", "podzol", "mycelium"):
            names.append(f"{block_name}[snowy=true]")
            names.append("grass_block_snow")

        names.append(block_name)
        return tuple(dict.fromkeys(names))

    face_specs = (
        ("east", "+X"), ("west", "-X"), ("top", "+Y"),
        ("bottom", "-Y"), ("south", "+Z"), ("north", "-Z"),
    )
    values = {
        name: {
            "tile": [],
            "chunk": [],
            "texture": [],
            "tint_data": [],
            "is_opaque": [],
            "anim_timing": [],
            "anim_frame_size": [],
            "uv_rot": [],
            "uv_bounds": [],
        }
        for name, _ in face_specs
    }
    material_ids = []
    is_opaque_list = []
    emissive_list = []

    state_cache: dict[str, dict[str, Any]] = {}
    import json

    for item in state_attr.data:
        state = item.value.decode("utf-8", errors="replace") if isinstance(item.value, bytes) else str(item.value)
        raw_state = state
        if state and state.startswith("{") and state.endswith("}"):
            try:
                json_obj = json.loads(state)
                if isinstance(json_obj, dict):
                    raw_state = json_obj.get("state", state)
            except Exception:
                pass

        block_name, props = parse_block_state_str(raw_state)
        names = mapping_names(raw_state)
        entry = next((by_name[name] for name in names if name in by_name), None)
        mat_id = int(entry.get("material_id", 0)) if entry else 0
        material_ids.append(mat_id)
        faces_dict = entry.get("faces", {}) if entry else {}

        fallback_location = next((texture_location(name) for name in names if texture_location(name)), {})
        if not fallback_location:
            for name in names:
                if name in BLOCK_TO_TEXTURE_ALIASES:
                    for stem in BLOCK_TO_TEXTURE_ALIASES[name]:
                        loc = texture_location(stem)
                        if loc:
                            fallback_location = loc
                            break
                    if fallback_location:
                        break

        block_state_entry = mapping.get("block_states", {}).get(raw_state)
        baked = None
        if block_state_entry:
            is_opaque_list.append(1 if block_state_entry.get("is_opaque", True) else 0)
            emissive_list.append(1 if block_state_entry.get("is_emissive", False) or is_block_emissive(block_name, props) else 0)
        else:
            baked = _GLOBAL_STATE_BAKER.bake_block_state(raw_state)
            is_opaque_list.append(int(baked.is_opaque) if entry is None or "is_opaque" not in entry else (1 if entry.get("is_opaque", True) else 0))
            emissive_list.append(1 if is_block_emissive(block_name, props) or baked.is_emissive else 0)

        derived_faces = texture_only_faces(block_name, props)

        is_snowy_top = props.get("snowy") == "true" and block_name in ("grass_block", "podzol", "mycelium")
        is_hardcoded_block = block_name in HARDCODED_TINT_BLOCKS

        for face_idx, (attr_face, mapping_face) in enumerate(face_specs):
            baked_face = baked.faces[face_idx] if baked else None
            state_face_entry = block_state_entry.get("faces", {}).get(mapping_face) if block_state_entry else None

            if state_face_entry:
                tex_name = state_face_entry.get("texture_key", "")
                uv_r = float(state_face_entry.get("uv_rotation", 0.0))
                uv_b = tuple(state_face_entry.get("uv_bounds", [0.0, 0.0, 1.0, 1.0]))
                tint_idx = int(state_face_entry.get("tint_index", -1))
            elif baked_face:
                tex_name = baked_face.texture
                uv_r = float(baked_face.uv_rot)
                uv_b = tuple(baked_face.uv_bounds)
                tint_idx = int(baked_face.tint_index)
            else:
                tex_name = ""
                uv_r = 0.0
                uv_b = (0.0, 0.0, 1.0, 1.0)
                tint_idx = -1

            f_mapping = faces_dict.get(mapping_face, {}) if isinstance(faces_dict, dict) else {}
            tex_stem = f_mapping.get("texture", "") if isinstance(f_mapping, dict) else ""

            short_n = tex_name.split(":", 1)[-1]
            if short_n.startswith("block/"):
                short_n = short_n[6:]

            location = (
                texture_location(tex_stem)
                or (f_mapping if isinstance(f_mapping, dict) and ("tile_column" in f_mapping or "kind" in f_mapping or "chunk_id" in f_mapping) else None)
                or derived_faces.get(mapping_face)
                or texture_location(tex_name)
                or texture_location(short_n)
                or texture_location(f"minecraft:{short_n}")
                or texture_location(f"minecraft:block/{short_n}")
                or fallback_location
                or {}
            )

            if location.get("kind") == "animation":
                px = int(location.get("pixel_x", 0))
                fw = max(1, int(location.get("frame_width", 16)))
                tile_col = float(px // fw)
                tile_row = 0.0
            else:
                tile_col = float(location.get("tile_column", 0))
                tile_row = float(location.get("tile_row", 0))

            values[attr_face]["tile"].append((tile_col, tile_row, 0.0))
            values[attr_face]["chunk"].append(int(location.get("chunk_id", 0)))
            values[attr_face]["texture"].append(int(location.get("texture_id", mat_id)))
            values[attr_face]["is_opaque"].append(1 if location.get("is_opaque", True) else 0)

            if is_snowy_top and attr_face == "top":
                values[attr_face]["tint_data"].append((0.0, 0.0, 0.0, 0.0))
            elif is_hardcoded_block:
                values[attr_face]["tint_data"].append((1.0, 1.0, 1.0, 1.0))
            elif isinstance(f_mapping, dict) and ("default_tint_weight" in f_mapping or "default_overlay_tint_weight" in f_mapping or "default_base_tint_weight" in f_mapping):
                values[attr_face]["tint_data"].append((
                    float(f_mapping.get("default_base_tint_weight", 0.0)),
                    float(f_mapping.get("default_overlay_tint_weight", 0.0)),
                    float(f_mapping.get("default_tint_weight", 0.0)),
                    1.0 if f_mapping.get("is_hardcoded", False) else 0.0,
                ))
            elif location.get("default_tint_weight", 0.0) > 0 or location.get("default_overlay_tint_weight", 0.0) > 0 or tint_idx >= 0:
                values[attr_face]["tint_data"].append((
                    float(location.get("default_base_tint_weight", 1.0 if tint_idx >= 0 else 0.0)),
                    float(location.get("default_overlay_tint_weight", 0.0)),
                    float(location.get("default_tint_weight", 1.0 if tint_idx >= 0 else 0.0)),
                    1.0 if location.get("is_hardcoded", False) else 0.0,
                ))
            else:
                values[attr_face]["tint_data"].append((0.0, 0.0, 0.0, 0.0))

            frame_count = float(location.get("frame_count", 1))
            frametime = float(location.get("frametime", 1))
            interpolate = 1.0 if location.get("interpolate", False) else 0.0
            values[attr_face]["anim_timing"].append((frame_count, frametime, interpolate, 0.0))

            fw = float(location.get("frame_width", location.get("tile_size", 16)))
            fh = float(location.get("frame_height", location.get("tile_size", 16)))
            values[attr_face]["anim_frame_size"].append((fw, fh, 0.0, 0.0))

            values[attr_face]["uv_rot"].append(uv_r)
            values[attr_face]["uv_bounds"].append((float(uv_b[0]), float(uv_b[1]), float(uv_b[2]), float(uv_b[3])))

    def point_attr(name: str, data_type: str):
        attr = mesh.attributes.get(name)
        if attr and (attr.domain != 'POINT' or attr.data_type != data_type or len(attr.data) != len(state_attr.data)):
            mesh.attributes.remove(attr)
            attr = None
        return attr or mesh.attributes.new(name=name, type=data_type, domain='POINT')

    point_attr("mtk_material_id", 'INT').data.foreach_set('value', material_ids)
    point_attr("mtk_is_opaque", 'INT').data.foreach_set('value', is_opaque_list)
    point_attr("is_opaque", 'INT').data.foreach_set('value', is_opaque_list)
    point_attr("mtk_emissive", 'INT').data.foreach_set('value', emissive_list)
    for face, _ in face_specs:
        tile_attr = point_attr(f"mtk_tile_{face}", 'FLOAT_VECTOR')
        tile_attr.data.foreach_set('vector', [component for tile in values[face]["tile"] for component in tile])
        point_attr(f"mtk_chunk_{face}", 'INT').data.foreach_set('value', values[face]["chunk"])
        point_attr(f"mtk_texture_{face}", 'INT').data.foreach_set('value', values[face]["texture"])
        point_attr(f"mtk_is_opaque_{face}", 'INT').data.foreach_set('value', values[face]["is_opaque"])
        tint_attr = point_attr(f"mtk_tint_data_{face}", 'FLOAT_COLOR')
        tint_attr.data.foreach_set('color', [component for value in values[face]["tint_data"] for component in value])
        anim_timing_attr = point_attr(f"mtk_anim_timing_{face}", 'FLOAT_COLOR')
        anim_timing_attr.data.foreach_set('color', [component for value in values[face]["anim_timing"] for component in value])
        anim_frame_size_attr = point_attr(f"mtk_anim_frame_size_{face}", 'FLOAT_COLOR')
        anim_frame_size_attr.data.foreach_set('color', [component for value in values[face]["anim_frame_size"] for component in value])
        rot_attr = point_attr(f"mtk_uv_rot_{face}", 'FLOAT')
        rot_attr.data.foreach_set('value', values[face]["uv_rot"])
        bounds_attr = point_attr(f"mtk_uv_bounds_{face}", 'FLOAT_COLOR')
        bounds_attr.data.foreach_set('color', [component for value in values[face]["uv_bounds"] for component in value])


def setup_yefira_point_cloud_attributes(
    mesh: bpy.types.Mesh,
    mapping_data: dict,
    primary_mat: Optional[bpy.types.Material] = None,
    chunk_0: Optional[dict] = None,
    chunk_1: Optional[dict] = None,
) -> None:
    """Initialize tiling, rotation, atlas dimensions, and 6-direction attributes on a point-cloud mesh."""
    if len(mesh.vertices) == 0:
        return

    num_verts = len(mesh.vertices)

    # 1. Ensure ATTR_UV_TILING_TRANSFORM exists
    tiling_attr = mesh.attributes.get(ATTR_UV_TILING_TRANSFORM)
    if not tiling_attr or tiling_attr.data_type != 'FLOAT_COLOR' or tiling_attr.domain != 'POINT' or len(tiling_attr.data) != num_verts:
        if tiling_attr:
            mesh.attributes.remove(tiling_attr)
        tiling_attr = mesh.attributes.new(name=ATTR_UV_TILING_TRANSFORM, type='FLOAT_COLOR', domain='POINT')
    flat_colors = [c for _ in range(num_verts) for c in (1.0, 1.0, 0.0, 0.0)]
    tiling_attr.data.foreach_set('color', flat_colors)

    # 2. Ensure ATTR_UV_ROTATION exists
    rot_attr = mesh.attributes.get(ATTR_UV_ROTATION)
    if not rot_attr or rot_attr.data_type != 'FLOAT' or rot_attr.domain != 'POINT' or len(rot_attr.data) != num_verts:
        if rot_attr:
            mesh.attributes.remove(rot_attr)
        rot_attr = mesh.attributes.new(name=ATTR_UV_ROTATION, type='FLOAT', domain='POINT')
    rot_attr.data.foreach_set('value', [0.0] * num_verts)

    # 3. Write atlas metadata attributes to point domain
    chunks = mapping_data.get("chunks", []) if isinstance(mapping_data, dict) else []
    chunks_by_id = {c.get("chunk_id", i): c for i, c in enumerate(chunks)} if isinstance(chunks, list) else {}
    chunk_0 = chunk_0 or chunks_by_id.get(0, {})
    chunk_1 = chunk_1 or chunks_by_id.get(1, {})

    mat_props = primary_mat or {}
    atlas_metadata = {
        "mtk_atlas_width": float(chunk_0.get("width", mat_props.get("mtk_atlas_width", 1024.0))),
        "mtk_atlas_height": float(chunk_0.get("height", mat_props.get("mtk_atlas_height", 1024.0))),
        "mtk_tile_size": float(chunk_0.get("tile_size", mat_props.get("mtk_tile_size", 16.0))),
        "mtk_tiles_per_row": float(chunk_0.get("tiles_per_row", mat_props.get("mtk_tiles_per_row", 64))),
        "mtk_anim_atlas_width": float(chunk_1.get("width", 896.0)),
        "mtk_anim_atlas_height": float(chunk_1.get("height", 1024.0)),
        "mtk_anim_frame_width": float(chunk_1.get("tile_size", 16.0)),
        "mtk_anim_frame_height": float(chunk_1.get("tile_size", 16.0)),
    }
    for attr_name, attr_value in atlas_metadata.items():
        attr = mesh.attributes.get(attr_name)
        if not attr or attr.data_type != 'FLOAT' or attr.domain != 'POINT' or len(attr.data) != num_verts:
            if attr:
                mesh.attributes.remove(attr)
            attr = mesh.attributes.new(name=attr_name, type='FLOAT', domain='POINT')
        attr.data.foreach_set('value', [attr_value] * num_verts)

    # 4. Fill 6-direction face attributes
    write_yefira_point_atlas_attributes(mesh, mapping_data)


def rebuild_or_update_yefira_material_dispatcher(
    atlas_materials: dict[int, bpy.types.Material],
) -> Optional[bpy.types.GeometryNodeTree]:
    """Ensure Yefira_Material_Dispatcher node group contains the complete multi-chunk Set Material chain."""
    try:
        if "yefira_blender.nodes.groups.material_dispatcher" in sys.modules:
            from yefira_blender.nodes.groups.material_dispatcher import get_or_create_material_dispatcher_group
            return get_or_create_material_dispatcher_group(atlas_materials)
        elif "yefira_blender.nodes.groups" in sys.modules:
            from yefira_blender.nodes.groups import get_or_create_material_dispatcher_group
            return get_or_create_material_dispatcher_group(atlas_materials)
    except Exception:
        pass

    tree = bpy.data.node_groups.get("Yefira_Material_Dispatcher")
    if not tree:
        tree = bpy.data.node_groups.new("Yefira_Material_Dispatcher", "GeometryNodeTree")

    sorted_chunk_ids = sorted(atlas_materials.keys()) if atlas_materials else [0]
    signature_key = ",".join(
        f"{cid}:{atlas_materials[cid].name if atlas_materials.get(cid) else 'None'}"
        for cid in sorted_chunk_ids
    )

    tree.nodes.clear()

    if hasattr(tree, "interface"):
        in_sock = next((s for s in tree.interface.items_tree if getattr(s, "item_type", "") == "SOCKET" and getattr(s, "in_out", "") == "INPUT" and s.name == "Geometry"), None)
        if not in_sock:
            tree.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        out_sock = next((s for s in tree.interface.items_tree if getattr(s, "item_type", "") == "SOCKET" and getattr(s, "in_out", "") == "OUTPUT" and s.name == "Geometry"), None)
        if not out_sock:
            tree.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

    nodes, links = tree.nodes, tree.links
    gin = nodes.new("NodeGroupInput")
    gin.location = (-300, 0)
    gout = nodes.new("NodeGroupOutput")
    last_geo = gin.outputs["Geometry"]
    x_pos = 0

    if 0 in atlas_materials and atlas_materials[0]:
        set_mat0 = nodes.new("GeometryNodeSetMaterial")
        set_mat0.name = "Set Material (Chunk 0)"
        set_mat0.inputs["Material"].default_value = atlas_materials[0]
        set_mat0.location = (x_pos, 0)
        links.new(last_geo, set_mat0.inputs["Geometry"])
        last_geo = set_mat0.outputs["Geometry"]
        x_pos += 200

    other_chunk_ids = [cid for cid in sorted_chunk_ids if cid > 0 and atlas_materials.get(cid)]
    if other_chunk_ids:
        read_chunk_id = nodes.new("GeometryNodeInputNamedAttribute")
        read_chunk_id.data_type = "INT"
        read_chunk_id.inputs["Name"].default_value = "mtk_atlas_chunk_id"
        read_chunk_id.location = (0, -220)

        for cid in other_chunk_ids:
            mat_obj = atlas_materials[cid]
            cmp_chunk = nodes.new("FunctionNodeCompare")
            cmp_chunk.data_type = "INT"
            cmp_chunk.operation = "EQUAL"
            cmp_chunk.inputs["B"].default_value = cid
            cmp_chunk.location = (x_pos, -220)
            links.new(read_chunk_id.outputs["Attribute"], cmp_chunk.inputs["A"])

            set_mat = nodes.new("GeometryNodeSetMaterial")
            set_mat.name = f"Set Material (Chunk {cid})"
            set_mat.inputs["Material"].default_value = mat_obj
            set_mat.location = (x_pos, 0)
            links.new(last_geo, set_mat.inputs["Geometry"])
            links.new(cmp_chunk.outputs["Result"], set_mat.inputs["Selection"])

            last_geo = set_mat.outputs["Geometry"]
            x_pos += 200

    gout.location = (x_pos + 100, 0)
    links.new(last_geo, gout.inputs["Geometry"])
    tree["yefira_dispatcher_signature"] = signature_key
    tree["yefira_role"] = "material_dispatcher"
    return tree


def _update_yefira_geometry_node_materials(
    obj: bpy.types.Object,
    atlas_materials: dict[int, bpy.types.Material],
) -> None:
    """Traverse all Geometry Nodes modifier trees and nested sub-groups on a Yefira object,
    updating Set Material nodes and rebuilding the multi-chunk Material Dispatcher."""
    primary_mat = atlas_materials.get(0) or next(iter(atlas_materials.values()), None)
    if not primary_mat:
        return

    import re

    disp_tree = rebuild_or_update_yefira_material_dispatcher(atlas_materials)
    visited_groups = {disp_tree} if disp_tree else set()

    def update_node_group(group: Optional[bpy.types.NodeTree]) -> None:
        if not group or group in visited_groups or not hasattr(group, "nodes"):
            return
        visited_groups.add(group)

        for n in group.nodes:
            if n.type == 'SET_MATERIAL' and "Material" in n.inputs:
                m = re.search(r"Chunk (\d+)", n.name)
                if m:
                    cid = int(m.group(1))
                    n.inputs["Material"].default_value = atlas_materials.get(cid, primary_mat)
                else:
                    n.inputs["Material"].default_value = primary_mat
            elif n.type == 'GROUP' and getattr(n, "node_tree", None):
                if n.name == "Material Dispatcher" and disp_tree:
                    n.node_tree = disp_tree
                else:
                    update_node_group(n.node_tree)

    for mod in obj.modifiers:
        if mod.type == 'NODES' and mod.node_group:
            update_node_group(mod.node_group)


def notify_yefira_update(obj: Optional[bpy.types.Object] = None) -> None:
    """Notify the Yefira addon to refresh point cloud attributes and rebuild geometry nodes."""
    if obj:
        try:
            if "yefira_blender.nodes.world_tree" in sys.modules:
                from yefira_blender.nodes.world_tree import setup_world_geometry_nodes
                setup_world_geometry_nodes(obj)
            elif "yefira_blender.nodes.geo_nodes" in sys.modules:
                from yefira_blender.nodes.geo_nodes import setup_world_geometry_nodes
                setup_world_geometry_nodes(obj)
            else:
                try:
                    import yefira_blender.nodes.world_tree as ywt
                    ywt.setup_world_geometry_nodes(obj)
                except ImportError:
                    pass
        except Exception:
            pass

    try:
        if hasattr(bpy.ops, "yefira") and hasattr(bpy.ops.yefira, "rebuild_world"):
            bpy.ops.yefira.rebuild_world()
            return
    except Exception:
        pass

    try:
        if "yefira_blender.operators.main_operators" in sys.modules:
            from yefira_blender.operators.main_operators import trigger_point_cloud_update
            trigger_point_cloud_update(bpy.context)
    except Exception:
        pass


def apply_yefira_atlas_materials(
    obj: bpy.types.Object,
    yefira_atlas_materials: dict[int, bpy.types.Material],
    mapping_data: dict,
    chunks_by_id: Optional[dict[int, dict]] = None,
) -> bool:
    """Apply Atlas materials and point cloud attributes to a Yefira procedural world object.

    Configures dense material slot indices (0..max_chunk_id), enables fake user,
    updates all Set Material nodes across Geometry Node trees and Material Dispatcher,
    populates directional and dimension point attributes, and signals Yefira to refresh.
    """
    if not yefira_atlas_materials:
        return False

    primary_mat = yefira_atlas_materials.get(0) or next(iter(yefira_atlas_materials.values()), None)
    if not primary_mat:
        return False

    # Chunk IDs are the Geometry Nodes material indices. Give the point-cloud
    # a dense, deterministic slot table matching chunk IDs 0..max_chunk_id.
    obj.data.materials.clear()
    max_chunk_id = max(yefira_atlas_materials.keys())
    for chunk_id in range(max_chunk_id + 1):
        chunk_material = yefira_atlas_materials.get(chunk_id)
        if chunk_material is None:
            raise RuntimeError(f"Atlas mapping is missing material chunk {chunk_id}")
        chunk_material.use_fake_user = True
        obj.data.materials.append(chunk_material)

    # Update modifier Set Material node and nested Material Dispatcher sub-groups
    _update_yefira_geometry_node_materials(obj, yefira_atlas_materials)

    # Configure mesh point-cloud attributes
    chunk_0 = (chunks_by_id or {}).get(0, {})
    chunk_1 = (chunks_by_id or {}).get(1, {})
    setup_yefira_point_cloud_attributes(
        mesh=obj.data,
        mapping_data=mapping_data,
        primary_mat=primary_mat,
        chunk_0=chunk_0,
        chunk_1=chunk_1,
    )

    # Signal Yefira addon operators / nodes setup
    notify_yefira_update(obj)

    return True

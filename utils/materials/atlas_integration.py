"""
MoziToolKit Atlas Material integration and Shader setup for Yefira Blender Plugin.
"""

from __future__ import annotations
import json
import logging
from typing import Optional, Any
try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

logger = logging.getLogger("Yefira")

MASTER_MATERIAL_NAME = "Yefira_Atlas_Master"
FALLBACK_MATERIAL_NAME = "Yefira_Fallback_PBR"

# Standard 6-face cubic order
FACE_ORDER = ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]


def _fallback_texture_location(mapping: dict, block_name: str) -> Optional[dict]:
    """Resolve generated-model textures that have no explicit six-face map."""
    textures = mapping.get("textures", {})
    short_name = block_name.split(":", 1)[-1]
    if short_name.startswith("block/"):
        short_name = short_name[6:]
    for key in (short_name, f"minecraft:{short_name}", f"minecraft:block/{short_name}"):
        location = textures.get(key)
        if isinstance(location, dict):
            return location
    return None


def _atlas_name_aliases(name: str) -> tuple[str, ...]:
    """Return stable mapping aliases for a Minecraft block/texture name."""
    short_name = name.split(":", 1)[-1]
    if short_name.startswith("block/"):
        short_name = short_name[6:]
    return tuple(dict.fromkeys((name, short_name, f"minecraft:{short_name}", f"minecraft:block/{short_name}")))


def _atlas_short_name(name: str) -> str:
    """Return ``grass_block_top`` for every supported resource-key spelling."""
    name = name.split(":", 1)[-1]
    return name.removeprefix("block/")


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

HARDCODED_TINT_BLOCKS = {
    "spruce_leaves": (1.0, 1.0, 1.0, 1.0),
    "birch_leaves": (1.0, 1.0, 1.0, 1.0),
    "lily_pad": (1.0, 1.0, 1.0, 1.0),
    "redstone_wire": (1.0, 1.0, 1.0, 1.0),
}


def _build_block_face_location_lut(mapping: Optional[dict]) -> tuple[dict[str, list[dict]], dict[str, int]]:
    """Build point-cloud face locations from atlas data, not material names.

    Normal meshes preserve a source texture per polygon.  Yefira instead has
    a Minecraft block state at each point, so a texture-only pack needs a
    small, deterministic bridge from common ``*_side/top/bottom/end`` texture
    sets to the logical block name.  Explicit six-face mappings always win.
    """
    locations_by_name: dict[str, list[dict]] = {}
    material_ids: dict[str, int] = {}
    if not mapping:
        return locations_by_name, material_ids

    textures = mapping.get("textures", {})
    texture_by_stem: dict[str, dict] = {}
    for texture_key, location in textures.items():
        if not isinstance(location, dict):
            continue
        for alias in _atlas_name_aliases(texture_key):
            texture_by_stem.setdefault(_atlas_short_name(alias), location)

    def get_tex(stem: str) -> Optional[dict]:
        return texture_by_stem.get(stem)

    def add(name: str, face_locations: list[dict], material_id: int) -> None:
        for alias in _atlas_name_aliases(name):
            locations_by_name[alias] = face_locations
            material_ids[alias] = material_id

    # 0. First consume authoritative baked block_states if available from AtlasGenerator
    block_states = mapping.get("block_states", {})
    for state_str, state_info in block_states.items():
        faces = state_info.get("faces", {})
        fallback = _fallback_texture_location(mapping, state_str) or {}
        face_locations = [faces.get(face_name) or fallback for face_name in FACE_ORDER]
        mat_id = int(face_locations[0].get("texture_id", 0)) if face_locations and face_locations[0] else 0
        add(state_str, face_locations, mat_id)

    # 1. Next consume the authoritative material mapping.  A real model can
    # encode arbitrary face layouts that texture-name conventions cannot.
    for index, material in enumerate(mapping.get("materials", [])):
        name = material.get("name", "")
        if not name:
            continue
        fallback = _fallback_texture_location(mapping, name) or {}
        faces = material.get("faces", {})
        face_locations = [faces.get(face_name) or fallback for face_name in FACE_ORDER]
        add(name, face_locations, int(material.get("material_id", index)))

    # 2. Stateful and multi-face block definitions (Top/Bottom, Sides, Front/Back)
    # Furnace, Blast Furnace, Smoker
    for base in ("furnace", "blast_furnace", "smoker"):
        top_loc = get_tex(f"{base}_top") or get_tex("furnace_top")
        bottom_loc = get_tex(f"{base}_bottom") or top_loc
        side_loc = get_tex(f"{base}_side") or get_tex("furnace_side")
        front_unlit = get_tex(f"{base}_front") or side_loc
        front_lit = get_tex(f"{base}_front_on") or front_unlit

        if top_loc or side_loc or front_unlit or front_lit:
            primary_loc = front_unlit or side_loc or top_loc
            actual_top = top_loc or primary_loc
            actual_bottom = bottom_loc or primary_loc
            actual_side = side_loc or primary_loc
            mat_id = int(primary_loc.get("texture_id", 0)) if primary_loc else 0

            # Unlit layout: [side, side, top, bottom, side, front]
            mat_id = material_ids.get(base, int(primary_loc.get("texture_id", 0))) if primary_loc else material_ids.get(base, 0)
            unlit_faces = [actual_side, actual_side, actual_top, actual_bottom, actual_side, front_unlit or actual_side]
            add(base, unlit_faces, mat_id)
            add(f"{base}_front", unlit_faces, mat_id)
            add(f"{base}[lit=false]", unlit_faces, mat_id)

            # Lit layout: [side, side, top, bottom, side, front_on]
            lit_mat_id = material_ids.get(f"{base}_front_on", material_ids.get(f"{base}_lit", int(front_lit.get("texture_id", mat_id)))) if front_lit else mat_id
            lit_faces = [actual_side, actual_side, actual_top, actual_bottom, actual_side, front_lit or actual_side]
            add(f"{base}_front_on", lit_faces, lit_mat_id)
            add(f"{base}_lit", lit_faces, lit_mat_id)
            add(f"{base}[lit=true]", lit_faces, lit_mat_id)

    # Beehive and Bee Nest
    for base in ("beehive", "bee_nest"):
        top_loc = get_tex(f"{base}_top")
        bottom_loc = get_tex(f"{base}_bottom") or top_loc
        side_loc = get_tex(f"{base}_side")
        front_unlit = get_tex(f"{base}_front") or side_loc
        front_honey = get_tex(f"{base}_front_honey") or front_unlit

        if top_loc or side_loc or front_unlit or front_honey:
            primary_loc = front_unlit or side_loc or top_loc
            actual_top = top_loc or primary_loc
            actual_bottom = bottom_loc or primary_loc
            actual_side = side_loc or primary_loc
            mat_id = material_ids.get(base, int(primary_loc.get("texture_id", 0))) if primary_loc else material_ids.get(base, 0)

            normal_faces = [actual_side, actual_side, actual_top, actual_bottom, actual_side, front_unlit or actual_side]
            add(base, normal_faces, mat_id)
            add(f"{base}_front", normal_faces, mat_id)

            honey_mat_id = material_ids.get(f"{base}_front_honey", int(front_honey.get("texture_id", mat_id))) if front_honey else mat_id
            honey_faces = [actual_side, actual_side, actual_top, actual_bottom, actual_side, front_honey or actual_side]
            add(f"{base}_front_honey", honey_faces, honey_mat_id)
            add(f"{base}[honey_level=5]", honey_faces, honey_mat_id)

    # Respawn Anchor
    top_off = get_tex("respawn_anchor_top_off")
    top_on = get_tex("respawn_anchor_top") or top_off
    bottom_anchor = get_tex("respawn_anchor_bottom") or top_off
    side0 = get_tex("respawn_anchor_side0") or top_off
    if top_off or top_on or side0:
        base_mat_id = material_ids.get("respawn_anchor", int((top_off or side0).get("texture_id", 0))) if (top_off or side0) else 0
        off_faces = [side0 or top_off, side0 or top_off, top_off or top_on, bottom_anchor or top_off, side0 or top_off, side0 or top_off]
        add("respawn_anchor", off_faces, base_mat_id)
        add("respawn_anchor_top_off", off_faces, base_mat_id)
        add("respawn_anchor_side0", off_faces, base_mat_id)
        add("respawn_anchor[charges=0]", off_faces, base_mat_id)

        for charges in range(1, 5):
            side_c = get_tex(f"respawn_anchor_side{charges}") or side0 or top_on
            c_mat_id = material_ids.get(f"respawn_anchor_side{charges}", int(side_c.get("texture_id", base_mat_id))) if side_c else base_mat_id
            c_faces = [side_c, side_c, top_on or top_off, bottom_anchor or top_off, side_c, side_c]
            add(f"respawn_anchor_side{charges}", c_faces, c_mat_id)
            add(f"respawn_anchor[charges={charges}]", c_faces, c_mat_id)
        if top_on and "respawn_anchor_top" not in locations_by_name:
            top_mat_id = material_ids.get("respawn_anchor_top", int(top_on.get("texture_id", base_mat_id)))
            side_max = get_tex("respawn_anchor_side4") or side0 or top_on
            add("respawn_anchor_top", [side_max, side_max, top_on, bottom_anchor or top_off, side_max, side_max], top_mat_id)

    # Carved Pumpkin & Jack o'Lantern
    pumpkin_top = get_tex("pumpkin_top")
    pumpkin_side = get_tex("pumpkin_side")
    for p_name in ("carved_pumpkin", "jack_o_lantern"):
        front_tex = get_tex(p_name)
        if front_tex or pumpkin_side or pumpkin_top:
            top_loc = pumpkin_top or pumpkin_side or front_tex
            side_loc = pumpkin_side or pumpkin_top or front_tex
            p_mat_id = material_ids.get(p_name, int((front_tex or side_loc).get("texture_id", 0))) if (front_tex or side_loc) else 0
            p_faces = [side_loc, side_loc, top_loc, top_loc, side_loc, front_tex or side_loc]
            add(p_name, p_faces, p_mat_id)

    # Dispenser and Dropper
    for base in ("dispenser", "dropper"):
        top_loc = get_tex(f"{base}_top") or get_tex("furnace_top")
        bottom_loc = get_tex(f"{base}_bottom") or top_loc
        side_loc = get_tex(f"{base}_side") or get_tex("furnace_side")
        front_tex = get_tex(f"{base}_front")
        front_vert = get_tex(f"{base}_front_vertical") or front_tex
        if front_tex or side_loc or top_loc:
            actual_top = top_loc or side_loc or front_tex
            actual_bottom = bottom_loc or actual_top
            actual_side = side_loc or top_loc or front_tex
            d_mat_id = material_ids.get(base, int((front_tex or actual_side).get("texture_id", 0))) if (front_tex or actual_side) else 0
            d_faces = [actual_side, actual_side, actual_top, actual_bottom, actual_side, front_tex or actual_side]
            d_faces_vert = [actual_side, actual_side, actual_top, actual_bottom, actual_side, front_vert or actual_side]
            add(base, d_faces, d_mat_id)
            add(f"{base}_front", d_faces, d_mat_id)
            add(f"{base}_front_vertical", d_faces_vert, d_mat_id)
            add(f"{base}[facing=up]", d_faces_vert, d_mat_id)
            add(f"{base}[facing=down]", d_faces_vert, d_mat_id)

    # Observer
    obs_top = get_tex("observer_top")
    obs_side = get_tex("observer_side")
    obs_back = get_tex("observer_back")
    obs_back_on = get_tex("observer_back_on") or obs_back
    obs_front = get_tex("observer_front")
    if obs_front or obs_side or obs_top:
        primary = obs_front or obs_side or obs_top
        actual_top = obs_top or primary
        actual_bottom = obs_top or primary
        actual_side = obs_side or primary
        actual_back = obs_back or actual_side
        actual_front = obs_front or primary
        obs_mat_id = material_ids.get("observer", int(primary.get("texture_id", 0))) if primary else 0
        obs_faces = [actual_side, actual_side, actual_top, actual_bottom, actual_back, actual_front]
        obs_faces_powered = [actual_side, actual_side, actual_top, actual_bottom, obs_back_on or actual_back, actual_front]
        add("observer", obs_faces, obs_mat_id)
        add("observer_front", obs_faces, obs_mat_id)
        add("observer[powered=false]", obs_faces, obs_mat_id)
        add("observer_on", obs_faces_powered, obs_mat_id)
        add("observer[powered=true]", obs_faces_powered, obs_mat_id)

    # Piston and Sticky Piston
    piston_top = get_tex("piston_top")
    piston_top_sticky = get_tex("piston_top_sticky") or piston_top
    piston_bottom = get_tex("piston_bottom") or piston_top
    piston_side = get_tex("piston_side") or piston_top
    if piston_top or piston_side or piston_bottom:
        primary = piston_top or piston_side
        p_mat_id = material_ids.get("piston", int(primary.get("texture_id", 0))) if primary else 0
        actual_top = piston_top or primary
        actual_bottom = piston_bottom or primary
        actual_side = piston_side or primary
        p_faces = [actual_side, actual_side, actual_top, actual_bottom, actual_side, actual_side]
        sp_faces = [actual_side, actual_side, piston_top_sticky or actual_top, actual_bottom, actual_side, actual_side]
        add("piston", p_faces, p_mat_id)
        add("piston_base", p_faces, p_mat_id)
        add("sticky_piston", sp_faces, material_ids.get("sticky_piston", p_mat_id))

    # Command blocks (Vertical-base: Top=Front, Bottom=Back, 4 Sides=Side)
    for cb in ("command_block", "chain_command_block", "repeating_command_block"):
        front = get_tex(f"{cb}_front")
        back = get_tex(f"{cb}_back")
        side = get_tex(f"{cb}_side")
        cond = get_tex(f"{cb}_conditional") or side
        if front or side:
            primary = front or side
            cb_mat_id = material_ids.get(cb, int(primary.get("texture_id", 0))) if primary else 0
            cb_faces = [side or primary, side or primary, front or primary, back or side or primary, side or primary, side or primary]
            cb_cond_faces = [cond or primary, cond or primary, front or primary, back or side or primary, cond or primary, cond or primary]
            add(cb, cb_faces, cb_mat_id)
            add(f"{cb}[conditional=false]", cb_faces, cb_mat_id)
            add(f"{cb}[conditional=true]", cb_cond_faces, cb_mat_id)

    # Barrel
    barrel_top = get_tex("barrel_top")
    barrel_top_open = get_tex("barrel_top_open") or barrel_top
    barrel_bottom = get_tex("barrel_bottom") or barrel_top
    barrel_side = get_tex("barrel_side") or barrel_top
    if barrel_top or barrel_side:
        primary = barrel_top or barrel_side
        b_mat_id = material_ids.get("barrel", int(primary.get("texture_id", 0))) if primary else 0
        barrel_faces = [barrel_side or primary, barrel_side or primary, barrel_top or primary, barrel_bottom or primary, barrel_side or primary, barrel_side or primary]
        open_faces = [barrel_side or primary, barrel_side or primary, barrel_top_open or primary, barrel_bottom or primary, barrel_side or primary, barrel_side or primary]
        add("barrel", barrel_faces, b_mat_id)
        add("barrel_top", barrel_faces, b_mat_id)
        add("barrel_bottom", barrel_faces, b_mat_id)
        add("barrel_side", barrel_faces, b_mat_id)
        add("barrel[open=false]", barrel_faces, b_mat_id)
        add("barrel[open=true]", open_faces, b_mat_id)
        add("barrel_top_open", open_faces, b_mat_id)

    # Grass block, Podzol, Mycelium
    dirt_loc = get_tex("dirt")
    snow_side = get_tex("grass_block_snow")
    for base in ("grass_block", "podzol", "mycelium"):
        top_loc = get_tex(f"{base}_top")
        side_loc = get_tex(f"{base}_side")
        if top_loc or side_loc:
            actual_top = top_loc or side_loc
            actual_bottom = dirt_loc or actual_top
            actual_side = side_loc or actual_top
            g_mat_id = material_ids.get(base, int((side_loc or top_loc).get("texture_id", 0))) if (side_loc or top_loc) else 0
            g_faces = [actual_side, actual_side, actual_top, actual_bottom, actual_side, actual_side]
            add(base, g_faces, g_mat_id)
            add(f"{base}_top", g_faces, g_mat_id)
            add(f"{base}_side", g_faces, g_mat_id)
            if snow_side:
                snow_faces = [snow_side, snow_side, actual_top, actual_bottom, snow_side, snow_side]
                add(f"{base}[snowy=true]", snow_faces, g_mat_id)
                if base == "grass_block":
                    add("grass_block_snow", snow_faces, g_mat_id)

    # Redstone Lamp
    lamp_off = get_tex("redstone_lamp")
    lamp_on = get_tex("redstone_lamp_on")
    if lamp_off or lamp_on:
        if lamp_off:
            off_id = material_ids.get("redstone_lamp", int(lamp_off.get("texture_id", 0)))
            add("redstone_lamp", [lamp_off] * 6, off_id)
            add("redstone_lamp[lit=false]", [lamp_off] * 6, off_id)
        if lamp_on:
            on_id = material_ids.get("redstone_lamp_on", int(lamp_on.get("texture_id", 0)))
            add("redstone_lamp_on", [lamp_on] * 6, on_id)
            add("redstone_lamp[lit=true]", [lamp_on] * 6, on_id)

    # Other aliases from BLOCK_TO_TEXTURE_ALIASES
    for block_name, target_stems in BLOCK_TO_TEXTURE_ALIASES.items():
        if block_name in locations_by_name:
            continue
        found_loc = next((texture_by_stem.get(s) for s in target_stems if texture_by_stem.get(s)), None)
        if found_loc:
            top_loc = next((texture_by_stem.get(s) for s in target_stems if s.endswith(("_top", "_top_off"))), None) or texture_by_stem.get(f"{block_name}_top")
            bottom_loc = next((texture_by_stem.get(s) for s in target_stems if s.endswith("_bottom")), None) or texture_by_stem.get(f"{block_name}_bottom")
            front_loc = next((texture_by_stem.get(s) for s in target_stems if s.endswith(("_front", "_front_on", "_front_honey")) or s in ("carved_pumpkin", "jack_o_lantern")), None)
            back_loc = next((texture_by_stem.get(s) for s in target_stems if s.endswith("_back")), None)
            side_loc = next((texture_by_stem.get(s) for s in target_stems if s.endswith(("_side", "_side0"))), found_loc)

            if "command_block" in block_name:
                face_locations = [side_loc, side_loc, front_loc or found_loc, back_loc or side_loc, side_loc, side_loc]
            elif "piston" in block_name:
                face_locations = [side_loc, side_loc, top_loc or found_loc, bottom_loc or side_loc, side_loc, side_loc]
            else:
                actual_top = top_loc or found_loc
                actual_bottom = bottom_loc or found_loc
                actual_back = back_loc or side_loc
                actual_front = front_loc or found_loc
                face_locations = [side_loc, side_loc, actual_top, actual_bottom, actual_back, actual_front]

            add(block_name, face_locations, int(found_loc.get("texture_id", 0)))

    # Suffix-based multi-face detection (e.g. oak_log_top, oak_log_side, etc.)
    base_names = set(texture_by_stem)
    for stem in tuple(texture_by_stem):
        for suffix in ("_side", "_top", "_bottom", "_end"):
            if stem.endswith(suffix):
                base_names.add(stem[:-len(suffix)])

    for base_name in base_names:
        base = texture_by_stem.get(base_name)
        side = texture_by_stem.get(f"{base_name}_side") or base
        top = texture_by_stem.get(f"{base_name}_top") or texture_by_stem.get(f"{base_name}_end") or side
        bottom = texture_by_stem.get(f"{base_name}_bottom") or texture_by_stem.get(f"{base_name}_end") or top
        if not side or not top or not bottom:
            continue
        if base_name == "grass_block":
            bottom = texture_by_stem.get("dirt") or bottom
        face_locations = [side, side, top, bottom, side, side]
        existing = locations_by_name.get(base_name)
        has_differentiated_faces = False
        if existing and len(existing) >= 6:
            distinct = {
                (loc.get("tile_column"), loc.get("tile_row"), loc.get("texture_id"), loc.get("texture_key"))
                for loc in existing if isinstance(loc, dict)
            }
            has_differentiated_faces = len(distinct) > 1
        has_named_variants = any(texture_by_stem.get(f"{base_name}{suffix}") for suffix in ("_side", "_top", "_bottom", "_end"))
        if has_named_variants and not has_differentiated_faces:
            add(base_name, face_locations, material_ids.get(base_name, int(side.get("texture_id", 0))))

    # 3. Direct texture entries represent an all-face block unless already populated
    for texture_key, location in textures.items():
        if not isinstance(location, dict):
            continue
        stem = _atlas_short_name(texture_key)
        if stem not in locations_by_name:
            add(stem, [location] * 6, int(location.get("texture_id", 0)))

    return locations_by_name, material_ids


def resolve_block_state_face_locations(
    name: str,
    props: dict[str, str],
    mapping: Optional[dict] = None,
    locations_by_name: Optional[dict] = None,
) -> list[dict]:
    """Resolve dynamic state-aware 6-face locations for a block state.

    Order returned: [+X (East), -X (West), +Y (Top), -Y (Bottom), +Z (South), -Z (North)]
    """
    if locations_by_name is None:
        if mapping:
            locations_by_name, _ = _build_block_face_location_lut(mapping)
        else:
            locations_by_name = {}

    if not locations_by_name:
        return [{}] * 6

    # 1. Furnace, Blast Furnace, Smoker
    if name in ("furnace", "blast_furnace", "smoker"):
        is_lit = props.get("lit") == "true"
        key = f"{name}_front_on" if is_lit else name
        if key in locations_by_name:
            return locations_by_name[key]

    # 2. Beehive and Bee Nest
    if name in ("beehive", "bee_nest"):
        is_honey = props.get("honey_level") == "5"
        key = f"{name}_front_honey" if is_honey else name
        if key in locations_by_name:
            return locations_by_name[key]

    # 3. Respawn Anchor
    if name == "respawn_anchor":
        charges = props.get("charges", "0")
        if charges not in ("0", 0, ""):
            key = f"respawn_anchor_side{charges}"
        else:
            key = "respawn_anchor_top_off"
        if key in locations_by_name:
            return locations_by_name[key]

    # 4. Grass Block, Podzol, Mycelium
    if name in ("grass_block", "podzol", "mycelium"):
        snowy = props.get("snowy") == "true"
        if snowy:
            if f"{name}[snowy=true]" in locations_by_name:
                return locations_by_name[f"{name}[snowy=true]"]
            if "grass_block_snow" in locations_by_name:
                return locations_by_name["grass_block_snow"]
        if name in locations_by_name:
            return locations_by_name[name]

    # 5. Redstone Lamp
    if name == "redstone_lamp":
        is_lit = props.get("lit") == "true"
        key = "redstone_lamp_on" if is_lit else "redstone_lamp"
        if key in locations_by_name:
            return locations_by_name[key]

    # 6. Barrel
    if name == "barrel":
        is_open = props.get("open") == "true"
        if is_open and "barrel_top_open" in locations_by_name:
            return locations_by_name["barrel_top_open"]
        if "barrel" in locations_by_name:
            return locations_by_name["barrel"]

    # 7. Command Blocks
    if "command_block" in name:
        is_cond = props.get("conditional") == "true"
        key = f"{name}[conditional=true]" if is_cond else f"{name}[conditional=false]"
        if key in locations_by_name:
            return locations_by_name[key]

    # 8. Dispenser and Dropper
    if name in ("dispenser", "dropper"):
        facing = props.get("facing", "north")
        if facing in ("up", "down") and f"{name}_front_vertical" in locations_by_name:
            return locations_by_name[f"{name}_front_vertical"]

    # 9. Observer
    if name == "observer":
        is_powered = props.get("powered") == "true"
        key = "observer_on" if is_powered else "observer"
        if key in locations_by_name:
            return locations_by_name[key]

    # 10. Red Mushroom Block, Brown Mushroom Block, Mushroom Stem
    if name in ("red_mushroom_block", "brown_mushroom_block", "mushroom_stem"):
        skin_entry = locations_by_name.get(name)
        skin = skin_entry[0] if skin_entry else {}
        inside_entry = locations_by_name.get("mushroom_block_inside")
        inside = inside_entry[0] if inside_entry else skin
        up = inside if props.get("up") == "false" else skin
        down = inside if props.get("down") == "false" else skin
        east = inside if props.get("east") == "false" else skin
        west = inside if props.get("west") == "false" else skin
        south = inside if props.get("south") == "false" else skin
        north = inside if props.get("north") == "false" else skin
        return [east, west, up, down, south, north]

    # Fallback to direct name in locations_by_name
    if name in locations_by_name:
        return locations_by_name[name]

    return [{}] * 6


def find_active_atlas_material() -> Optional[bpy.types.Material]:
    """Find the best active Atlas material in Blender scene."""
    if not HAS_BPY:
        return None

    # 1. First priority: MoziToolKit Atlas chunk materials (e.g. mtk:minecraft:atlas_chunk_000...)
    for mat in bpy.data.materials:
        if not mat:
            continue
        if "mtk:atlas_chunk_id" in mat or "mtk_atlas_chunk_id" in mat or (mat.name.startswith("mtk:") and "atlas_chunk" in mat.name):
            return mat

    # 2. Second priority: Materials with explicit atlas width/mapping properties
    for mat in bpy.data.materials:
        if not mat:
            continue
        if "mtk_atlas_width" in mat or "mtk:atlas_mapping" in mat or "mtk_atlas_mapping" in mat:
            return mat
        if mat.node_tree and ("mtk:atlas_mapping" in mat.node_tree or "mtk_atlas_mapping" in mat.node_tree):
            return mat

    # 3. Explicit named master materials
    for name in ("MTK_Atlas_Master", "MC_Atlas_Material"):
        if name in bpy.data.materials:
            return bpy.data.materials[name]

    # 4. Fallback to Yefira_Atlas_Master
    if MASTER_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[MASTER_MATERIAL_NAME]

    return None


def find_bound_atlas_material(obj: Optional[bpy.types.Object]) -> Optional[bpy.types.Material]:
    """Return the Atlas material deliberately assigned to a Yefira object.

    ``bpy.data.materials`` is global and iteration order is not a material
    selection policy.  Looking there during every live update could replace a
    freshly applied MoziToolKit atlas with an unrelated chunk from another
    scene/object.  Slot zero is the primary chunk and the authoritative
    source for this world object's dimensions.
    """
    if not obj or not getattr(obj, "data", None):
        return None
    for mat in obj.data.materials:
        if not mat:
            continue
        if (
            "mtk:atlas_mapping" in mat
            or "mtk_atlas_mapping" in mat
            or "mtk:atlas_chunk_id" in mat
            or "mtk_atlas_chunk_id" in mat
        ):
            return mat
    return None


def parse_atlas_mapping(mat: Optional[bpy.types.Material]) -> Optional[dict]:
    """Extract and parse atlas mapping JSON from a material or its node tree."""
    if not mat:
        return None
    raw = None
    for key in ("mtk_atlas_mapping", "mtk:atlas_mapping"):
        if key in mat:
            raw = mat[key]
            break
        if mat.node_tree and key in mat.node_tree:
            raw = mat.node_tree[key]
            break

    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Failed to parse atlas mapping JSON: {e}")
        return None


def build_block_face_lut(mapping: Optional[dict]) -> tuple[dict[str, list[tuple[int, int]]], dict[str, int]]:
    """
    Build lookup table for block stem -> 6 face tile (col, row) coordinates,
    and block stem -> material_id integer mapping.
    Face order: 0: +X, 1: -X, 2: +Y (Top), 3: -Y (Bottom), 4: +Z (South), 5: -Z (North).
    """
    face_lut: dict[str, list[tuple[int, int]]] = {}
    material_id_map: dict[str, int] = {}

    if not mapping:
        return face_lut, material_id_map

    locations_by_name, material_ids = _build_block_face_location_lut(mapping)
    for name, locations in locations_by_name.items():
        coords = []
        for location in locations:
            if location and location.get("kind") == "animation":
                px = int(location.get("pixel_x", 0))
                fw = max(1, int(location.get("frame_width", 16)))
                coords.append((px // fw, 0))
            elif location:
                coords.append((int(location.get("tile_column", 0)), int(location.get("tile_row", 0))))
            else:
                coords.append((0, 0))
        face_lut[name] = coords
    material_id_map.update(material_ids)

    return face_lut, material_id_map


def build_block_face_atlas_ids(mapping: Optional[dict]) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    """Return per-face atlas chunk and texture IDs using MoziToolKit's mapping.

    A tile coordinate is only meaningful within one atlas chunk.  Keeping the
    two IDs alongside the tile LUT lets Geometry Nodes choose the right
    material after it realizes a cube face.
    """
    chunk_lut: dict[str, list[int]] = {}
    texture_lut: dict[str, list[int]] = {}
    if not mapping:
        return chunk_lut, texture_lut

    locations_by_name, _ = _build_block_face_location_lut(mapping)
    for name, locations in locations_by_name.items():
        chunk_lut[name] = [int(location.get("chunk_id", 0)) if location else 0 for location in locations]
        texture_lut[name] = [int(location.get("texture_id", 0)) if location else 0 for location in locations]

    return chunk_lut, texture_lut


def build_block_face_tint_lut(mapping: Optional[dict]) -> dict[str, list[tuple[float, float, float, float]]]:
    """Build face-domain biome-tint weights from Mozi's atlas metadata."""
    tint_lut: dict[str, list[tuple[float, float, float, float]]] = {}
    if not mapping:
        return tint_lut

    locations_by_name, _ = _build_block_face_location_lut(mapping)
    for name, locations in locations_by_name.items():
        short_n = _atlas_short_name(name)
        if short_n in HARDCODED_TINT_BLOCKS:
            tint_lut[name] = [HARDCODED_TINT_BLOCKS[short_n]] * 6
        elif short_n == "grass_block_snow":
            tint_lut[name] = [(0.0, 0.0, 0.0, 0.0)] * 6
        else:
            tint_lut[name] = [
                (
                    float(location.get("default_base_tint_weight", 0.0)),
                    float(location.get("default_overlay_tint_weight", 0.0)),
                    float(location.get("default_tint_weight", 0.0)),
                    1.0 if location.get("is_hardcoded", False) else 0.0,
                )
                if location else (0.0, 0.0, 0.0, 0.0)
                for location in locations
            ]

    return tint_lut


def build_block_face_anim_lut(
    mapping: Optional[dict],
) -> tuple[dict[str, list[tuple[float, float, float, float]]], dict[str, list[tuple[float, float, float, float]]]]:
    """Build per-face animation timing (frame_count, frametime, interpolate, 0) and frame_size LUTs."""
    timing_lut: dict[str, list[tuple[float, float, float, float]]] = {}
    frame_size_lut: dict[str, list[tuple[float, float, float, float]]] = {}
    if not mapping:
        return timing_lut, frame_size_lut

    locations_by_name, _ = _build_block_face_location_lut(mapping)
    for name, locations in locations_by_name.items():
        timing_lut[name] = [
            (
                float(loc.get("frame_count", 1)),
                float(loc.get("frametime", 1)),
                1.0 if loc.get("interpolate", False) else 0.0,
                0.0,
            )
            if loc else (1.0, 1.0, 0.0, 0.0)
            for loc in locations
        ]
        frame_size_lut[name] = [
            (
                float(loc.get("frame_width", loc.get("tile_size", 16))),
                float(loc.get("frame_height", loc.get("tile_size", 16))),
                0.0,
                0.0,
            )
            if loc else (16.0, 16.0, 0.0, 0.0)
            for loc in locations
        ]

    return timing_lut, frame_size_lut


def build_block_face_uv_rot_lut(mapping: Optional[dict]) -> dict[str, list[float]]:
    """Build per-face UV rotation LUT in degrees (0, 90, 180, 270)."""
    rot_lut: dict[str, list[float]] = {}
    if not mapping:
        return rot_lut
    # 1. From block_states
    for state_str, state_info in mapping.get("block_states", {}).items():
        faces = state_info.get("faces", {})
        rots = [float(faces.get(f, {}).get("uv_rotation", 0.0)) if isinstance(faces.get(f), dict) else 0.0 for f in FACE_ORDER]
        for alias in _atlas_name_aliases(state_str):
            rot_lut[alias] = rots
    # 2. From materials
    for material in mapping.get("materials", []):
        name = material.get("name", "")
        if not name:
            continue
        faces = material.get("faces", {})
        rots = [float(faces.get(f, {}).get("uv_rotation", 0.0)) if isinstance(faces.get(f), dict) else 0.0 for f in FACE_ORDER]
        for alias in _atlas_name_aliases(name):
            rot_lut.setdefault(alias, rots)
    return rot_lut


def build_block_face_uv_bounds_lut(mapping: Optional[dict]) -> dict[str, list[tuple[float, float, float, float]]]:
    """Build per-face UV bounds LUT: (u_min, v_min, u_max, v_max)."""
    bounds_lut: dict[str, list[tuple[float, float, float, float]]] = {}
    if not mapping:
        return bounds_lut
    # 1. From block_states
    for state_str, state_info in mapping.get("block_states", {}).items():
        faces = state_info.get("faces", {})
        bounds = []
        for f in FACE_ORDER:
            loc = faces.get(f) if isinstance(faces.get(f), dict) else {}
            u_min = float(loc.get("u_min", 0.0))
            v_min = float(loc.get("v_min", 0.0))
            u_max = float(loc.get("u_max", 1.0))
            v_max = float(loc.get("v_max", 1.0))
            bounds.append((u_min, v_min, u_max, v_max))
        for alias in _atlas_name_aliases(state_str):
            bounds_lut[alias] = bounds
    # 2. From materials
    for material in mapping.get("materials", []):
        name = material.get("name", "")
        if not name:
            continue
        faces = material.get("faces", {})
        bounds = []
        for f in FACE_ORDER:
            loc = faces.get(f) if isinstance(faces.get(f), dict) else {}
            u_min = float(loc.get("u_min", 0.0))
            v_min = float(loc.get("v_min", 0.0))
            u_max = float(loc.get("u_max", 1.0))
            v_max = float(loc.get("v_max", 1.0))
            bounds.append((u_min, v_min, u_max, v_max))
        for alias in _atlas_name_aliases(name):
            bounds_lut.setdefault(alias, bounds)
    return bounds_lut


def extract_atlas_parameters(mat: Optional[bpy.types.Material] = None) -> dict[str, Any]:
    """
    Extract complete Atlas parameters: width, height, tile_size, tiles_per_row, chunk dimensions and LUTs.
    """
    if mat is None:
        mat = find_active_atlas_material()

    res = {
        "material": mat,
        "width": 1024.0,
        "height": 1024.0,
        "tile_size": 16.0,
        "tiles_per_row": 64,
        "chunk_0_width": 4096.0,
        "chunk_0_height": 80.0,
        "chunk_0_tile_size": 16.0,
        "chunk_0_tiles_per_row": 256.0,
        "chunk_1_width": 896.0,
        "chunk_1_height": 1024.0,
        "chunk_1_tile_size": 16.0,
        "mapping": None,
        "block_face_lut": {},
        "block_face_chunk_lut": {},
        "block_face_texture_lut": {},
        "block_face_tint_lut": {},
        "block_face_anim_timing_lut": {},
        "block_face_anim_frame_size_lut": {},
        "material_id_map": {},
    }

    if not mat:
        return res

    mapping = parse_atlas_mapping(mat)
    res["mapping"] = mapping

    if "mtk_atlas_width" in mat:
        res["width"] = float(mat["mtk_atlas_width"])
    if "mtk_atlas_height" in mat:
        res["height"] = float(mat["mtk_atlas_height"])
    if "mtk_tile_size" in mat:
        res["tile_size"] = float(mat["mtk_tile_size"])
    if "mtk_tiles_per_row" in mat:
        res["tiles_per_row"] = int(mat["mtk_tiles_per_row"])

    if mapping:
        if "tile_size" in mapping and "mtk_tile_size" not in mat:
            res["tile_size"] = float(mapping["tile_size"])
        chunks = mapping.get("chunks", [])
        chunks_by_id = {c.get("chunk_id", i): c for i, c in enumerate(chunks)}

        if 0 in chunks_by_id:
            c0 = chunks_by_id[0]
            res["chunk_0_width"] = float(c0.get("width", res["width"]))
            res["chunk_0_height"] = float(c0.get("height", res["height"]))
            res["chunk_0_tile_size"] = float(c0.get("tile_size", res["tile_size"]))
            res["chunk_0_tiles_per_row"] = float(c0.get("tiles_per_row", res["tiles_per_row"]))
            res["width"] = res["chunk_0_width"]
            res["height"] = res["chunk_0_height"]
            res["tile_size"] = res["chunk_0_tile_size"]
            res["tiles_per_row"] = int(res["chunk_0_tiles_per_row"])

        if 1 in chunks_by_id:
            c1 = chunks_by_id[1]
            res["chunk_1_width"] = float(c1.get("width", 896.0))
            res["chunk_1_height"] = float(c1.get("height", 1024.0))
            res["chunk_1_tile_size"] = float(c1.get("tile_size", 16.0))

        face_lut, mat_id_map = build_block_face_lut(mapping)
        face_chunk_lut, face_texture_lut = build_block_face_atlas_ids(mapping)
        face_tint_lut = build_block_face_tint_lut(mapping)
        anim_timing_lut, anim_frame_size_lut = build_block_face_anim_lut(mapping)
        face_uv_rot_lut = build_block_face_uv_rot_lut(mapping)
        face_uv_bounds_lut = build_block_face_uv_bounds_lut(mapping)

        res["block_face_lut"] = face_lut
        res["block_face_chunk_lut"] = face_chunk_lut
        res["block_face_texture_lut"] = face_texture_lut
        res["block_face_tint_lut"] = face_tint_lut
        res["block_face_anim_timing_lut"] = anim_timing_lut
        res["block_face_anim_frame_size_lut"] = anim_frame_size_lut
        res["block_face_uv_rot_lut"] = face_uv_rot_lut
        res["block_face_uv_bounds_lut"] = face_uv_bounds_lut
        res["material_id_map"] = mat_id_map

    return res


def get_or_create_atlas_material() -> Optional[bpy.types.Material]:
    """
    Get existing active Atlas Master Material or create a unified Yefira Atlas Master.
    """
    if not HAS_BPY:
        return None

    active = find_active_atlas_material()
    if active:
        return active

    if MASTER_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[MASTER_MATERIAL_NAME]

    # Build default unified Atlas Master material
    mat = bpy.data.materials.new(name=MASTER_MATERIAL_NAME)
    mat.use_nodes = True
    mat["mtk_atlas_width"] = 1024.0
    mat["mtk_atlas_height"] = 1024.0
    mat["mtk_tile_size"] = 16.0
    mat["mtk_tiles_per_row"] = 64

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Output Node
    output_node = nodes.new(type='ShaderNodeOutputMaterial')
    output_node.location = (600, 0)

    # Principled BSDF
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.location = (300, 0)
    links.new(bsdf.outputs['BSDF'], output_node.inputs['Surface'])

    if 'Roughness' in bsdf.inputs:
        bsdf.inputs['Roughness'].default_value = 0.8

    # Shared Texture Coordinate Node
    tex_coord = nodes.new(type='ShaderNodeTexCoord')
    tex_coord.location = (-600, 100)

    # Albedo Image Texture Node
    tex_image = nodes.new(type='ShaderNodeTexImage')
    tex_image.name = "Atlas Albedo"
    tex_image.interpolation = "Closest"
    tex_image.extension = "CLIP"
    tex_image.location = (-350, 200)
    links.new(tex_coord.outputs['UV'], tex_image.inputs['Vector'])

    # Auto-bind existing atlas image from blender data if available
    atlas_img = None
    for img in bpy.data.images:
        if "atlas_chunk" in img.name and "albedo" in img.name:
            atlas_img = img
            break
        elif "atlas_albedo" in img.name:
            atlas_img = img
            break
    if atlas_img:
        tex_image.image = atlas_img

    # Attribute Node: Biome Tint Color
    attr_tint = nodes.new(type='ShaderNodeAttribute')
    attr_tint.name = "Attr Biome Tint Color"
    attr_tint.attribute_name = "mtk_biome_tint_color"
    attr_tint.location = (-350, -50)

    # Attribute Node: Biome Tint Data
    attr_data = nodes.new(type='ShaderNodeAttribute')
    attr_data.name = "Attr Biome Tint Data"
    attr_data.attribute_name = "mtk_biome_tint_data"
    attr_data.location = (-350, -250)

    # Mix Color Node (Multiply Tint with Base)
    mix_node = nodes.new(type='ShaderNodeMix')
    mix_node.data_type = 'RGBA'
    mix_node.blend_type = 'MULTIPLY'
    mix_node.inputs[0].default_value = 1.0  # Factor
    mix_node.location = (-50, 100)

    links.new(tex_image.outputs['Color'], mix_node.inputs[6]) # Color A
    links.new(attr_tint.outputs['Color'], mix_node.inputs[7]) # Color B

    links.new(mix_node.outputs[2], bsdf.inputs['Base Color'])
    links.new(tex_image.outputs['Alpha'], bsdf.inputs['Alpha'])

    return mat


def find_all_atlas_chunk_materials(
    mapping: Optional[dict] = None,
    bound_material: Optional[bpy.types.Material] = None,
    obj: Optional[bpy.types.Object] = None,
) -> dict[int, bpy.types.Material]:
    """Find all Atlas chunk materials in Blender data, keyed by chunk_id.

    Prioritizes materials matching the bound material's pack hash / mapping
    or currently assigned to obj.data.materials to prevent stale materials from
    previous replacements polluting the material dispatcher.
    """
    if not HAS_BPY:
        return {}

    chunk_materials: dict[int, bpy.types.Material] = {}

    if bound_material is None and obj is not None:
        bound_material = find_bound_atlas_material(obj)

    target_pack_hash = None
    target_uv_source = None
    if bound_material:
        target_pack_hash = bound_material.get("mtk:pack_hash") or bound_material.get("mtk_pack_hash")
        target_uv_source = bound_material.get("mtk:atlas_uv_source")
        # Direct chunk 0 binding
        for key in ("mtk:atlas_chunk_id", "mtk_atlas_chunk_id"):
            if key in bound_material:
                try:
                    cid0 = int(bound_material[key])
                    chunk_materials[cid0] = bound_material
                    break
                except (ValueError, TypeError):
                    pass
        if not chunk_materials:
            chunk_materials[0] = bound_material

    # 1. First priority: Check materials already assigned to object material slots
    if obj and getattr(obj, "data", None) and hasattr(obj.data, "materials"):
        for slot_idx, slot_mat in enumerate(obj.data.materials):
            if not slot_mat:
                continue
            slot_hash = slot_mat.get("mtk:pack_hash") or slot_mat.get("mtk_pack_hash")
            slot_cid = None
            for key in ("mtk:atlas_chunk_id", "mtk_atlas_chunk_id"):
                if key in slot_mat:
                    try:
                        slot_cid = int(slot_mat[key])
                        break
                    except (ValueError, TypeError):
                        pass
            if slot_cid is None and "atlas_chunk_" in slot_mat.name:
                import re
                m = re.search(r"atlas_chunk_(\d+)", slot_mat.name)
                if m:
                    slot_cid = int(m.group(1))

            if slot_cid is not None:
                if target_pack_hash and slot_hash and slot_hash != target_pack_hash:
                    continue
                if slot_cid not in chunk_materials:
                    chunk_materials[slot_cid] = slot_mat

    # Sort materials to prefer ones specialized with :attr:UVMap or :attr:
    mats_sorted = sorted(
        [m for m in bpy.data.materials if m],
        key=lambda m: (
            0 if ":attr:UVMap" in m.name else (1 if ":attr:" in m.name else 2)
        )
    )

    # 2. Match materials in bpy.data.materials filtering by target pack hash & UV source
    for mat in mats_sorted:
        mat_hash = mat.get("mtk:pack_hash") or mat.get("mtk_pack_hash")
        mat_uv = mat.get("mtk:atlas_uv_source")

        # Skip materials from a different resource pack hash
        if target_pack_hash and (not mat_hash or mat_hash != target_pack_hash):
            continue
        # Skip materials with different UV source when target UV source is specified
        if target_uv_source and mat_uv and mat_uv != target_uv_source:
            continue

        cid = None
        for key in ("mtk:atlas_chunk_id", "mtk_atlas_chunk_id"):
            if key in mat:
                try:
                    cid = int(mat[key])
                    break
                except (ValueError, TypeError):
                    pass

        if cid is None and "atlas_chunk_" in mat.name:
            import re
            m = re.search(r"atlas_chunk_(\d+)", mat.name)
            if m:
                cid = int(m.group(1))

        if cid is not None and cid not in chunk_materials:
            chunk_materials[cid] = mat

    # 3. Check mapping chunks metadata fallback
    if mapping and "chunks" in mapping:
        for chunk in mapping["chunks"]:
            cid = int(chunk.get("chunk_id", 0))
            if cid not in chunk_materials:
                if cid == 0:
                    active = bound_material or find_active_atlas_material()
                    if active:
                        chunk_materials[0] = active

    if not chunk_materials:
        active = bound_material or find_active_atlas_material() or get_or_create_atlas_material()
        if active:
            chunk_materials[0] = active

    return chunk_materials


def setup_material_slots_for_object(
    obj: bpy.types.Object,
    mat: Optional[bpy.types.Material] = None,
    mapping: Optional[dict] = None,
):
    """Ensure object has all chunk materials assigned to slots 0..N in order.

    Slot index directly corresponds to mtk_atlas_chunk_id, enabling Geometry Nodes
    to use Set Material Index without overwriting via a single Set Material node.
    """
    if not obj or not getattr(obj, "data", None) or not HAS_BPY:
        return

    if mat is None:
        mat = find_bound_atlas_material(obj) or find_active_atlas_material() or get_or_create_atlas_material()

    if mapping is None and mat:
        mapping = parse_atlas_mapping(mat)

    chunk_materials = find_all_atlas_chunk_materials(mapping=mapping, bound_material=mat, obj=obj)
    if not chunk_materials and mat:
        chunk_materials[0] = mat

    max_chunk_id = max(chunk_materials.keys()) if chunk_materials else 0
    needed_slots = max(1, max_chunk_id + 1)

    while len(obj.data.materials) < needed_slots:
        obj.data.materials.append(None)

    for cid in range(needed_slots):
        target_mat = chunk_materials.get(cid) or mat
        obj.data.materials[cid] = target_mat

"""
6-face lookup table (LUT) generator and stateful block resolvers for Yefira / Atlas integration.
Maps Minecraft blockstates and canonical texture names to 6-face cubic orientations.
"""

from __future__ import annotations

import logging
from typing import Optional, Any

from ..constants import BLOCK_TO_TEXTURE_ALIASES

logger = logging.getLogger("Yefira.FaceLUT")

# Standard 6-face cubic order
FACE_ORDER = ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]

HARDCODED_TINT_BLOCKS = {
    "spruce_leaves": (1.0, 1.0, 1.0, 1.0),
    "birch_leaves": (1.0, 1.0, 1.0, 1.0),
    "lily_pad": (1.0, 1.0, 1.0, 1.0),
    "redstone_wire": (1.0, 1.0, 1.0, 1.0),
    "attached_melon_stem": (1.0, 1.0, 1.0, 1.0),
    "attached_pumpkin_stem": (1.0, 1.0, 1.0, 1.0),
    "melon_stem": (1.0, 1.0, 1.0, 1.0),
    "pumpkin_stem": (1.0, 1.0, 1.0, 1.0),
}


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

    # 1. Lookup via canonical atlas lookup keys
    from ...live_sync.classifier import atlas_lookup_keys
    for key in atlas_lookup_keys(name, props):
        if key in locations_by_name:
            return locations_by_name[key]

    # 2. Lookup via StateBaker resolved 6-face textures
    try:
        from ...mc_baker import get_shared_state_baker
        state_query = f"minecraft:{name}"
        if props:
            p_str = ",".join(f"{k}={v}" for k, v in sorted(props.items()))
            state_query = f"{state_query}[{p_str}]"
        baked = get_shared_state_baker().bake_block_state(state_query)
        if baked and baked.faces:
            res = []
            found_any = False
            for f in baked.faces:
                tex = f.texture
                short_tex = tex.split(":", 1)[-1].removeprefix("block/")
                loc_entry = locations_by_name.get(tex) or locations_by_name.get(short_tex) or locations_by_name.get(f"minecraft:{short_tex}")
                if loc_entry:
                    found_any = True
                    res.append(loc_entry[0] if isinstance(loc_entry, (list, tuple)) else loc_entry)
                else:
                    res.append({})
            if found_any:
                return res
    except Exception:
        pass

    # 3. Fallback to direct name in locations_by_name
    if name in locations_by_name:
        return locations_by_name[name]

    return [{}] * 6


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
            face_tints = []
            for location in locations:
                if not location:
                    face_tints.append((0.0, 0.0, 0.0, 0.0))
                    continue
                base_w = float(location.get("default_base_tint_weight", 0.0))
                overlay_w = float(location.get("default_overlay_tint_weight", 0.0))
                def_w = float(location.get("default_tint_weight", 0.0))
                is_hc = 1.0 if location.get("is_hardcoded", False) else 0.0
                tint_cat = location.get("tint_category")
                if (not def_w or def_w == 0.0) and tint_cat in ("grass", "foliage", "water"):
                    def_w = 1.0
                    base_w = 1.0
                    overlay_w = 1.0
                face_tints.append((base_w, overlay_w, def_w, is_hc))
            tint_lut[name] = face_tints

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


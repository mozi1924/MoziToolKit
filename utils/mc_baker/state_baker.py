"""
Headless Minecraft BlockState Baker.
Bakes arbitrary complex non-full and directional BlockStates (Stairs, Slabs, Fences,
Lanterns, Chains, Doors, etc.) directly from official JAR / resource pack definitions.
"""

from __future__ import annotations
from typing import Optional, Any, Union, Iterator, Tuple, Callable
from pathlib import Path
import copy

from .types import (
    BakedModel, BakedElement, BakedFace,
    MC_DIRECTIONS, DIR_TO_INDEX
)
from .math_utils import (
    rotate_point, rotate_direction, calculate_uv_rotation,
    rotate_element_point, default_face_uv, get_face_raw_vertices,
    get_face_loop_uvs, bake_face_exact
)
from .model_parser import ModelParser
from .blockstate_resolver import BlockStateResolver, parse_block_state_string
from .resource_loader import JarResourceLoader
from .obj_loader import resolve_obj_model_for_state, build_bell_model

from ..materials.constants import EMISSIVE_BLOCKS



def is_block_emissive(block_name: str, props: Optional[dict[str, str]] = None) -> bool:
    """Return True if block/state is emissive (light emitting), else False."""
    p = props or {}
    short_name = block_name.split(":", 1)[-1].removeprefix("block/")
    if short_name in EMISSIVE_BLOCKS or short_name.endswith("_froglight"):
        return True
    is_lit = p.get("lit") == "true"
    if is_lit and (
        short_name in ("furnace", "blast_furnace", "smoker", "redstone_lamp",
                       "campfire", "soul_campfire", "redstone_ore", "deepslate_redstone_ore")
    ):
        return True
    if short_name in ("redstone_torch", "redstone_wall_torch"):
        return p.get("lit", "true") == "true"
    if short_name == "respawn_anchor":
        charges = int(p.get("charges", "0")) if "charges" in p else 0
        return charges > 0
    if short_name == "redstone_wire":
        power = int(p.get("power", "0")) if "power" in p else 0
        return power > 0
    return False


_GLOBAL_STATE_BAKER: Optional[StateBaker] = None
_last_pack_fingerprint: Optional[tuple[str, ...]] = None
_last_configured_loader = None


def get_shared_state_baker() -> StateBaker:
    """Return the shared global StateBaker singleton instance."""
    global _GLOBAL_STATE_BAKER
    if _GLOBAL_STATE_BAKER is None:
        _GLOBAL_STATE_BAKER = StateBaker()
    return _GLOBAL_STATE_BAKER


def refresh_shared_baker_sources(force_precompile_if_missing: bool = False) -> StateBaker:
    """Synchronize shared StateBaker with the active Resource Pack Stack.
    Loads precompiled models from disk cache if available.
    """
    global _last_pack_fingerprint, _last_configured_loader
    baker = get_shared_state_baker()
    try:
        from ..materials.pack import get_configured_pack_stack, get_pack_stack_fingerprint
        current_fingerprint = get_pack_stack_fingerprint()
        if current_fingerprint != _last_pack_fingerprint or (force_precompile_if_missing and not baker._bake_cache):
            _last_pack_fingerprint = current_fingerprint
            stack = get_configured_pack_stack()
            composite_loader = stack.get_composite_loader()
            _last_configured_loader = composite_loader
            baker.resource_loader = composite_loader
            baker.model_parser.model_loader_fn = composite_loader.load_model if composite_loader else None
            baker.state_resolver.blockstate_loader_fn = composite_loader.load_blockstate if composite_loader else None
            baker.clear_cache()
            if stack.is_models_baked():
                manifest_path = stack.get_baked_models_dir() / "models_manifest.json"
                baker.load_precompiled_manifest(manifest_path)
            elif force_precompile_if_missing and stack.packs:
                stack.precompile_models()
                if stack.is_models_baked():
                    manifest_path = stack.get_baked_models_dir() / "models_manifest.json"
                    baker.load_precompiled_manifest(manifest_path)
    except Exception:
        pass
    return baker


def clear_shared_baker_cache() -> None:
    """Clear shared StateBaker cache and reset cached resource pack fingerprints."""
    global _GLOBAL_STATE_BAKER, _last_pack_fingerprint, _last_configured_loader
    if _GLOBAL_STATE_BAKER is not None:
        _GLOBAL_STATE_BAKER.clear_cache()
    _last_pack_fingerprint = None
    _last_configured_loader = None


# ---------------------------------------------------------------------------
# Fallback Texture Resolution Rules
# ---------------------------------------------------------------------------

_WOOD_TYPES = ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove", "cherry", "pale_oak", "bamboo", "crimson", "warped")
_BRICK_VARIANTS = ("stone_brick", "mossy_stone_brick", "nether_brick", "red_nether_brick", "end_stone_brick", "deepslate_brick", "deepslate_tile", "polished_blackstone_brick", "mud_brick", "tuff_brick")
_DERIVATIVE_SUFFIXES = ("_slab", "_stairs", "_wall", "_fence_gate", "_fence", "_button", "_pressure_plate")


def _resolve_derivative_stem(short_name: str) -> str:
    """Resolve derivative block stems (slabs, stairs, walls, signs, carpets, beds, waxed)."""
    stem = short_name
    if stem.startswith("waxed_"):
        stem = stem.removeprefix("waxed_")
    if stem.startswith("potted_"):
        stem = stem.removeprefix("potted_")
    elif stem.endswith("_carpet"):
        return stem.replace("_carpet", "_wool")
    elif stem.endswith("_bed"):
        return stem.replace("_bed", "_wool")
    elif stem.endswith("_banner") or stem.endswith("_wall_banner"):
        color = stem.replace("_wall_banner", "").replace("_banner", "")
        return f"{color}_wool" if color else "white_wool"
    elif stem.endswith("_wood"):
        return stem.replace("_wood", "_log")
    elif stem.endswith("_hyphae"):
        return stem.replace("_hyphae", "_stem")
    elif "_wall_hanging_sign" in stem:
        wood = stem.replace("_wall_hanging_sign", "")
        return f"{wood}_hanging_sign"
    elif "_hanging_sign" in stem:
        wood = stem.replace("_hanging_sign", "")
        return f"{wood}_hanging_sign"
    elif "_wall_sign" in stem:
        return stem.replace("_wall_sign", "_planks")
    elif "_sign" in stem:
        return stem.replace("_sign", "_planks")

    for suffix in _DERIVATIVE_SUFFIXES:
        if stem.endswith(suffix):
            base = stem[:-len(suffix)]
            if base in _WOOD_TYPES:
                return f"{base}_planks"
            elif base == "bamboo_mosaic":
                return "bamboo_mosaic"
            elif base in _BRICK_VARIANTS:
                return f"{base}s"
            elif base == "brick":
                return "bricks"
            elif base == "smooth_sandstone":
                return "sandstone_top"
            elif base == "smooth_red_sandstone":
                return "red_sandstone_top"
            elif base == "smooth_quartz":
                return "quartz_block_bottom"
            elif base == "quartz":
                return "quartz_block_side"
            elif base == "purpur":
                return "purpur_block"
            return base

    return stem


class StateBaker:
    def __init__(
        self,
        jar_path: Optional[Union[str, Path]] = None,
        model_parser: Optional[ModelParser] = None,
        state_resolver: Optional[BlockStateResolver] = None
    ):
        self.resource_loader: Optional[JarResourceLoader] = None
        if jar_path:
            self.resource_loader = JarResourceLoader(jar_path)

        loader_state_fn = self.resource_loader.load_blockstate if self.resource_loader else None
        loader_model_fn = self.resource_loader.load_model if self.resource_loader else None

        self.model_parser = model_parser or ModelParser(model_loader_fn=loader_model_fn)
        self.state_resolver = state_resolver or BlockStateResolver(blockstate_loader_fn=loader_state_fn)
        self._bake_cache: dict[str, BakedModel] = {}

    def set_resource_source(self, jar_path: Union[str, Path]):
        """Set or switch the underlying Minecraft JAR/resource pack source."""
        if not self.resource_loader:
            self.resource_loader = JarResourceLoader(jar_path)
        else:
            self.resource_loader.set_source(jar_path)

        self.model_parser.model_loader_fn = self.resource_loader.load_model
        self.state_resolver.blockstate_loader_fn = self.resource_loader.load_blockstate
        self.clear_cache()

    def is_available(self) -> bool:
        """Check if resource loader is active and valid."""
        return self.resource_loader is not None and bool(self.resource_loader._file_index)

    def clear_cache(self):
        self._bake_cache.clear()
        self.model_parser._model_cache.clear()
        self.state_resolver._state_cache.clear()
        try:
            from ..culling import get_shared_face_culler
            get_shared_face_culler().clear_cache()
        except Exception:
            pass

    @staticmethod
    def _resolve_base_face_textures(short_name: str, props: dict[str, str], fallback: str) -> dict[str, str]:
        """Resolve unrotated base 6-face texture stems in local model space."""
        is_lit = props.get("lit") == "true"

        # 1. Furnace, Blast Furnace, Smoker
        if short_name in ("furnace", "blast_furnace", "smoker"):
            top = f"minecraft:block/{short_name}_top"
            side = f"minecraft:block/{short_name}_side"
            front = f"minecraft:block/{short_name}_front_on" if is_lit else f"minecraft:block/{short_name}_front"
            return {"east": side, "west": side, "up": top, "down": top, "south": side, "north": front}

        # 2. Beehive, Bee Nest
        if short_name in ("beehive", "bee_nest"):
            is_honey = props.get("honey_level") == "5"
            top = f"minecraft:block/{short_name}_top"
            bottom = f"minecraft:block/{short_name}_bottom"
            side = f"minecraft:block/{short_name}_side"
            front = f"minecraft:block/{short_name}_front_honey" if is_honey else f"minecraft:block/{short_name}_front"
            return {"east": side, "west": side, "up": top, "down": bottom, "south": side, "north": front}

        # 3. Carved Pumpkin, Jack o'Lantern
        if short_name in ("carved_pumpkin", "jack_o_lantern"):
            top = "minecraft:block/pumpkin_top"
            side = "minecraft:block/pumpkin_side"
            front = f"minecraft:block/{short_name}"
            return {"east": side, "west": side, "up": top, "down": top, "south": side, "north": front}

        # 4. Dispenser, Dropper
        if short_name in ("dispenser", "dropper"):
            is_vertical = props.get("facing") in ("up", "down")
            top = "minecraft:block/furnace_top"
            if is_vertical:
                front = f"minecraft:block/{short_name}_front_vertical"
                return {"east": top, "west": top, "up": front, "down": top, "south": top, "north": top}
            side = f"minecraft:block/furnace_side"
            front = f"minecraft:block/{short_name}_front"
            return {"east": side, "west": side, "up": top, "down": top, "south": side, "north": front}

        # 5. Crafter
        if short_name == "crafter":
            is_crafting = props.get("crafting") == "true"
            is_triggered = props.get("triggered") == "true"
            is_powered = props.get("powered") == "true"
            top = "minecraft:block/crafter_top_triggered" if is_triggered else ("minecraft:block/crafter_top_crafting" if is_crafting else "minecraft:block/crafter_top")
            front = "minecraft:block/crafter_front_powered" if is_powered else "minecraft:block/crafter_front"
            bottom = "minecraft:block/crafter_bottom"
            side = "minecraft:block/crafter_side"
            return {"east": "minecraft:block/crafter_east", "west": "minecraft:block/crafter_west", "up": top, "down": bottom, "south": side, "north": front}

        # 6. Glazed Terracotta / Redstone Lamp
        if "glazed_terracotta" in short_name:
            pattern = f"minecraft:block/{short_name}"
            return {d: pattern for d in MC_DIRECTIONS}
        if short_name == "redstone_lamp":
            lamp = "minecraft:block/redstone_lamp_on" if is_lit else "minecraft:block/redstone_lamp"
            return {d: lamp for d in MC_DIRECTIONS}

        # 7. Observer
        if short_name == "observer":
            return {
                "east": "minecraft:block/observer_side", "west": "minecraft:block/observer_side",
                "up": "minecraft:block/observer_top", "down": "minecraft:block/observer_top",
                "south": "minecraft:block/observer_back", "north": "minecraft:block/observer_front"
            }

        # 8. Piston, Sticky Piston, Piston Head
        if short_name in ("piston", "sticky_piston", "piston_head"):
            is_sticky = short_name == "sticky_piston" or props.get("type") == "sticky"
            top = "minecraft:block/piston_top_sticky" if is_sticky else "minecraft:block/piston_top"
            side = "minecraft:block/piston_side"
            bottom = "minecraft:block/piston_bottom"
            return {"east": side, "west": side, "up": side, "down": side, "south": bottom, "north": top}

        # 9. Barrel
        if short_name == "barrel":
            top = "minecraft:block/barrel_top_open" if props.get("open") == "true" else "minecraft:block/barrel_top"
            bottom = "minecraft:block/barrel_bottom"
            side = "minecraft:block/barrel_side"
            return {"east": side, "west": side, "up": top, "down": bottom, "south": side, "north": side}

        # 10. Respawn Anchor
        if short_name == "respawn_anchor":
            charges = props.get("charges", "0")
            has_charges = str(charges) not in ("0", "")
            top = "minecraft:block/respawn_anchor_top" if has_charges else "minecraft:block/respawn_anchor_top_off"
            bottom = "minecraft:block/respawn_anchor_bottom"
            side = f"minecraft:block/respawn_anchor_side{charges}" if has_charges else "minecraft:block/respawn_anchor_side0"
            return {"east": side, "west": side, "up": top, "down": bottom, "south": side, "north": side}

        # 11. Command Blocks
        if "command_block" in short_name:
            return {
                "east": f"minecraft:block/{short_name}_side", "west": f"minecraft:block/{short_name}_side",
                "up": f"minecraft:block/{short_name}_side", "down": f"minecraft:block/{short_name}_side",
                "south": f"minecraft:block/{short_name}_back", "north": f"minecraft:block/{short_name}_front"
            }

        # 12. Grass Block, Podzol, Mycelium
        if short_name in ("grass_block", "podzol", "mycelium"):
            snowy = props.get("snowy") == "true"
            top = f"minecraft:block/{short_name}_top"
            side = "minecraft:block/grass_block_snow" if snowy else f"minecraft:block/{short_name}_side"
            return {"east": side, "west": side, "up": top, "down": "minecraft:block/dirt", "south": side, "north": side}

        # 13. Mushroom Blocks
        if short_name in ("red_mushroom_block", "brown_mushroom_block", "mushroom_stem"):
            skin = f"minecraft:block/{short_name}"
            inside = "minecraft:block/mushroom_block_inside"
            return {d: (inside if props.get(d) == "false" else skin) for d in MC_DIRECTIONS}

        # 14. Axis Blocks (Logs, Wood, Hyphae, Basalt, Hay, Bone)
        is_axis = "axis" in props or short_name.endswith(("_log", "_wood", "_stem", "_hyphae", "basalt", "hay_block", "bone_block"))
        if is_axis:
            top_stem = f"{short_name}_top" if not short_name.endswith(("_wood", "_hyphae")) else (f"{short_name[:-4]}log_top" if short_name.endswith("_wood") else f"{short_name[:-7]}stem_top")
            top = f"minecraft:block/{top_stem}"
            side = f"minecraft:block/{short_name}"
            return {"east": side, "west": side, "up": top, "down": top, "south": side, "north": side}

        # 15. Smart Derivative Fallbacks
        resolved_stem = _resolve_derivative_stem(short_name)
        if resolved_stem != short_name:
            fallback = f"minecraft:block/{resolved_stem}"

        return {d: fallback for d in MC_DIRECTIONS}

    def _resolve_base_face_elements(
        self,
        short_name: str,
        props: dict[str, str],
        fallback_texture: str,
        resolved_textures: dict[str, str]
    ) -> list[dict]:
        """Construct fallback 1x1x1 cuboid elements with canonical face rotations matching official model templates."""
        base_face_textures = self._resolve_base_face_textures(short_name, props, fallback_texture)

        rotations = {d: 0.0 for d in MC_DIRECTIONS}
        if "command_block" in short_name or short_name in ("piston", "sticky_piston"):
            rotations["down"] = 180.0
            rotations["east"] = 90.0
            rotations["west"] = 270.0
        elif "glazed_terracotta" in short_name:
            rotations["north"] = 90.0
            rotations["south"] = 270.0
            rotations["east"] = 180.0
            rotations["west"] = 0.0
        elif short_name == "observer":
            rotations["up"] = 180.0
        elif props.get("axis") in ("x", "z") or short_name.endswith(("_log", "_wood", "_stem", "_hyphae", "basalt", "hay_block", "bone_block")):
            if props.get("axis") in ("x", "z"):
                rotations["up"] = 180.0

        faces_dict = {}
        for d in MC_DIRECTIONS:
            tex = resolved_textures.get(d) or base_face_textures.get(d, fallback_texture)
            face_entry = {"texture": tex, "cullface": d}
            if rotations.get(d, 0.0) != 0.0:
                face_entry["rotation"] = rotations[d]
            faces_dict[d] = face_entry

        return [{"from": [0, 0, 0], "to": [16, 16, 16], "faces": faces_dict}]



    def bake_block_state(self, state_str: str) -> BakedModel:
        """
        Bake a BlockState string into a fully resolved BakedModel containing all elements,
        quad vertices in [0..1] block space, loop UV coordinates, and 6-face summary.
        """
        state_str_clean = state_str.strip()
        if state_str_clean in self._bake_cache:
            return self._bake_cache[state_str_clean]

        block_id, props = parse_block_state_string(state_str_clean)
        short_name = block_id.split(":", 1)[-1]
        fallback_texture = f"minecraft:block/{short_name}"
        is_emissive = is_block_emissive(short_name, props)

        # 1. Resolve JSON blockstate variants and models first
        variant_matches = self.state_resolver.resolve_state(state_str_clean)

        resolved_models: list[tuple[Any, dict[str, Any]]] = []
        has_json_elements = False
        for match in variant_matches:
            resolved_model = self.model_parser.resolve_model(match.model_id)
            resolved_models.append((match, resolved_model))
            if resolved_model.get("elements"):
                has_json_elements = True

        # 2. Fallback to 1:1 author-crafted OBJ model if no valid JSON elements exist
        # (e.g. true entity blocks like Chest, Shulker Box, Banner, Skull, Conduit, End Portal, or legacy resource packs)
        if not has_json_elements:
            obj_model = resolve_obj_model_for_state(block_id, props, fallback_texture)
            if obj_model:
                obj_model.is_emissive = is_emissive
                self._bake_cache[state_str_clean] = obj_model
                return obj_model

        baked_elements: list[BakedElement] = []
        six_faces: list[Optional[BakedFace]] = [None] * 6

        is_opaque = not any(w in short_name for w in (
            "glass", "leaves", "ice", "water", "air", "pane", "fence", "door",
            "trapdoor", "bars", "chain", "lantern", "stairs", "slab", "chest",
            "banner", "bed", "carpet", "pot", "sign", "hanging_sign", "head",
            "skull", "rod", "hook", "lever", "rail", "torch", "candle",
            "flower", "plant", "sapling", "vine", "bush", "wire", "repeater",
            "comparator", "cauldron", "hopper", "bell", "anvil", "stand",
            "frame", "portal", "conduit", "grindstone", "cutter", "piston"
        ))

        for match, resolved_model in resolved_models:
            raw_elements = resolved_model.get("elements", [])

            if not raw_elements:
                if not has_json_elements:
                    raw_elements = self._resolve_base_face_elements(
                        short_name, props, fallback_texture, resolved_model.get("textures", {})
                    )
                else:
                    raw_elements = []

            for elem in raw_elements:
                from_pos = tuple(elem.get("from", [0, 0, 0]))
                to_pos = tuple(elem.get("to", [16, 16, 16]))
                elem_rot = elem.get("rotation")
                elem_faces: dict[str, BakedFace] = {}
                is_full_cuboid = (from_pos == (0, 0, 0) and to_pos == (16, 16, 16) and not elem_rot)

                # Filter zero-thickness opposing faces (e.g. cross models, crops, lily pads, vines)
                # to prevent internal overlapping faces and Z-fighting in Blender
                is_zero_x = abs(from_pos[0] - to_pos[0]) < 1e-5
                is_zero_y = abs(from_pos[1] - to_pos[1]) < 1e-5
                is_zero_z = abs(from_pos[2] - to_pos[2]) < 1e-5

                raw_faces_items = list(elem.get("faces", {}).items())
                if is_zero_z and "north" in elem.get("faces", {}) and "south" in elem.get("faces", {}):
                    raw_faces_items = [(d, fd) for d, fd in raw_faces_items if d != "south"]
                if is_zero_x and "west" in elem.get("faces", {}) and "east" in elem.get("faces", {}):
                    raw_faces_items = [(d, fd) for d, fd in raw_faces_items if d != "east"]
                if is_zero_y and "up" in elem.get("faces", {}) and "down" in elem.get("faces", {}):
                    raw_faces_items = [(d, fd) for d, fd in raw_faces_items if d != "down"]

                for orig_dir, face_data in raw_faces_items:
                    texture = face_data.get("texture", fallback_texture)
                    cullface = face_data.get("cullface")
                    if not cullface and is_full_cuboid:
                        cullface = orig_dir
                    face_rot = float(face_data.get("rotation", 0.0))
                    tint_index = int(face_data.get("tintindex", -1))

                    raw_uv = face_data.get("uv")
                    uv_bounds_raw = (float(raw_uv[0]), float(raw_uv[1]), float(raw_uv[2]), float(raw_uv[3])) if raw_uv else None
                    uv_base = float(face_data.get("uv_size", 16.0))
                    if uv_base == 16.0 and raw_uv and max(raw_uv) > 16.0:
                        uv_base = 64.0

                    # Exact Minecraft 26.2 FaceBakery baking
                    new_dir, uv_rot, transformed_verts, loop_uvs, uv_bounds = bake_face_exact(
                        orig_dir=orig_dir,
                        from_pos=from_pos,
                        to_pos=to_pos,
                        uv_bounds=uv_bounds_raw,
                        face_rotation_deg=face_rot,
                        rot_x=match.rot_x,
                        rot_y=match.rot_y,
                        elem_rotation=elem_rot,
                        uvlock=match.uvlock,
                        uv_base=uv_base,
                    )

                    baked_face = BakedFace(
                        direction=new_dir,
                        texture=texture,
                        uv_rot=uv_rot,
                        uv_bounds=uv_bounds,
                        tint_index=tint_index,
                        cullface=rotate_direction(cullface, match.rot_x, match.rot_y) if cullface else None,
                        vertices=tuple(transformed_verts),
                        uvs=tuple(loop_uvs),
                    )

                    elem_faces[orig_dir] = baked_face

                    face_idx = DIR_TO_INDEX.get(new_dir)
                    if face_idx is not None and six_faces[face_idx] is None:
                        six_faces[face_idx] = baked_face

                baked_elements.append(BakedElement(
                    from_pos=from_pos,
                    to_pos=to_pos,
                    faces=elem_faces,
                    rotation=elem_rot,
                ))

        # Fill 6-face summary
        if baked_elements:
            for elem in baked_elements:
                for f in elem.faces.values():
                    if f and f.texture:
                        fallback_texture = f.texture
                        break
                if fallback_texture != f"minecraft:block/{short_name}":
                    break

        final_six_faces: list[BakedFace] = []
        for i in range(6):
            if six_faces[i] is not None:
                final_six_faces.append(six_faces[i])
            else:
                dir_name = MC_DIRECTIONS[i]
                final_six_faces.append(BakedFace(
                    direction=dir_name,
                    texture=fallback_texture,
                    uv_rot=0.0,
                    uv_bounds=(0.0, 0.0, 1.0, 1.0),
                ))

        is_known_non_cube = any(w in short_name for w in (
            "glass_pane", "pane", "fence", "door", "trapdoor", "bars", "chain", "lantern",
            "stairs", "slab", "chest", "banner", "bed", "carpet", "pot", "sign", "hanging_sign",
            "head", "skull", "rod", "hook", "lever", "rail", "torch", "candle", "flower",
            "plant", "sapling", "vine", "bush", "wire", "repeater", "comparator", "cauldron",
            "hopper", "bell", "anvil", "stand", "frame", "portal", "conduit", "grindstone",
            "stonecutter", "scaffolding", "dripstone", "amethyst", "sensor", "shrieker"
        )) and not (short_name.endswith("_slab") and props.get("type") == "double")

        is_cube = (
            not is_known_non_cube
            and len(baked_elements) >= 1
            and all(
                el.from_pos == (0, 0, 0) and el.to_pos == (16, 16, 16) and not el.rotation
                for el in baked_elements
            )
        )

        # Check if hybrid block (e.g. Bell: JSON support frame + OBJ bell body)
        if short_name == "bell":
            rot_y = variant_matches[0].rot_y if variant_matches else None
            baked_model = build_bell_model(
                block_state=state_str_clean,
                props=props,
                support_elements=baked_elements,
                support_faces=final_six_faces,
                rot_y=rot_y,
            )
            self._bake_cache[state_str_clean] = baked_model
            return baked_model

        baked_model = BakedModel(
            block_state=state_str_clean,
            elements=baked_elements,
            faces=final_six_faces,
            is_cube=is_cube,
            is_opaque=is_opaque,
            is_emissive=is_emissive,
            emissive_level=1.0 if is_emissive else 0.0,
        )

        self._bake_cache[state_str_clean] = baked_model
        return baked_model

    def bake_all_pack_states_iter(self) -> Iterator[Tuple[float, str, dict[str, BakedModel]]]:
        """
        Scan and bake all blockstates in the resource pack / JAR incrementally.
        Yields (fraction: float, message: str, current_baked_dict: dict[str, BakedModel]).
        """
        if not self.resource_loader:
            return
        all_block_ids = self.resource_loader.list_all_blockstates()
        total_blocks = max(1, len(all_block_ids))
        baked_dict: dict[str, BakedModel] = {}
        for idx, block_id in enumerate(all_block_ids):
            state_json = self.resource_loader.load_blockstate(block_id)
            if not state_json:
                continue
            short_name = block_id.split(":", 1)[-1]
            if "variants" in state_json:
                for variant_key in state_json["variants"].keys():
                    if variant_key == "":
                        full_state = block_id
                    else:
                        full_state = f"{block_id}[{variant_key}]"
                    try:
                        baked = self.bake_block_state(full_state)
                        baked_dict[full_state] = baked

                        # Expand common unconstrained Minecraft properties so exact state string queries hit
                        if short_name in ("dispenser", "dropper"):
                            baked_dict[f"{block_id}[{variant_key},triggered=false]"] = baked
                            baked_dict[f"{block_id}[{variant_key},triggered=true]"] = baked
                            baked_dict[f"{block_id}[triggered=false,{variant_key}]"] = baked
                            baked_dict[f"{block_id}[triggered=true,{variant_key}]"] = baked
                        elif "command_block" in short_name:
                            baked_dict[f"{block_id}[conditional=false,{variant_key}]"] = baked
                            baked_dict[f"{block_id}[conditional=true,{variant_key}]"] = baked
                            baked_dict[f"{block_id}[{variant_key},conditional=false]"] = baked
                            baked_dict[f"{block_id}[{variant_key},conditional=true]"] = baked
                        elif short_name in ("piston", "sticky_piston"):
                            baked_dict[f"{block_id}[extended=false,{variant_key}]"] = baked
                            baked_dict[f"{block_id}[extended=true,{variant_key}]"] = baked
                            baked_dict[f"{block_id}[{variant_key},extended=false]"] = baked
                            baked_dict[f"{block_id}[{variant_key},extended=true]"] = baked
                        elif short_name == "observer":
                            baked_dict[f"{block_id}[{variant_key},powered=false]"] = baked
                            baked_dict[f"{block_id}[{variant_key},powered=true]"] = baked
                            baked_dict[f"{block_id}[powered=false,{variant_key}]"] = baked
                            baked_dict[f"{block_id}[powered=true,{variant_key}]"] = baked
                        elif short_name == "barrel":
                            baked_dict[f"{block_id}[{variant_key},open=false]"] = baked
                            baked_dict[f"{block_id}[{variant_key},open=true]"] = baked
                            baked_dict[f"{block_id}[open=false,{variant_key}]"] = baked
                            baked_dict[f"{block_id}[open=true,{variant_key}]"] = baked
                        elif short_name == "crafter":
                            baked_dict[f"{block_id}[{variant_key},powered=false]"] = baked
                            baked_dict[f"{block_id}[{variant_key},powered=true]"] = baked
                            baked_dict[f"{block_id}[powered=false,{variant_key}]"] = baked
                            baked_dict[f"{block_id}[powered=true,{variant_key}]"] = baked
                    except Exception:
                        pass
            elif "multipart" in state_json:
                try:
                    baked_dict[block_id] = self.bake_block_state(block_id)
                    baked_dict[f"{block_id}[waterlogged=false]"] = self.bake_block_state(f"{block_id}[waterlogged=false]")
                    baked_dict[f"{block_id}[waterlogged=true]"] = self.bake_block_state(f"{block_id}[waterlogged=true]")
                except Exception:
                    pass
                try:
                    baked_dict[block_id] = self.bake_block_state(block_id)
                except Exception:
                    pass

            if idx % 10 == 0 or idx == total_blocks - 1:
                frac = (idx + 1) / total_blocks
                yield (frac, f"Baking models: {short_name} ({idx + 1}/{total_blocks})", baked_dict)

    def bake_all_pack_states(self, progress_callback: Optional[Callable[[float, str], None]] = None) -> dict[str, BakedModel]:
        """
        Scan and bake all blockstates in the resource pack / JAR.
        Returns mapping from state_str to BakedModel.
        """
        final_dict: dict[str, BakedModel] = {}
        for frac, msg, cur_dict in self.bake_all_pack_states_iter():
            if progress_callback:
                try:
                    progress_callback(frac, msg)
                except Exception:
                    pass
            final_dict = cur_dict
        return final_dict

    def save_precompiled_manifest_iter(
        self, output_file: Union[str, Path]
    ) -> Iterator[Tuple[float, str, Optional[int]]]:
        """
        Bake all pack states and save to a JSON manifest file on disk with progress updates.
        Yields (fraction: float, message: str, baked_count: Optional[int]).
        """
        import json
        baked_dict: dict[str, BakedModel] = {}
        for frac, msg, cur_dict in self.bake_all_pack_states_iter():
            baked_dict = cur_dict
            yield (frac * 0.95, msg, None)

        yield (0.96, f"Saving {len(baked_dict)} baked models to manifest...", None)
        manifest_data = {
            "format_version": "1.0.0",
            "models_count": len(baked_dict),
            "models": {k: v.to_dict() for k, v in baked_dict.items()},
        }
        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, separators=(",", ":"))

        yield (1.0, f"Successfully baked and cached {len(baked_dict)} models.", len(baked_dict))

    def save_precompiled_manifest(
        self, output_file: Union[str, Path], progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> int:
        """
        Bake all pack states and save to a JSON manifest file on disk.
        Returns the number of baked models saved.
        """
        final_count = 0
        for frac, msg, count in self.save_precompiled_manifest_iter(output_file):
            if progress_callback:
                try:
                    progress_callback(frac, msg)
                except Exception:
                    pass
            if count is not None:
                final_count = count
        return final_count

    def load_precompiled_manifest(self, source: Union[str, Path, dict]) -> int:
        """
        Load precompiled baked models directly into the internal cache.
        Returns the number of loaded models.
        """
        import json
        if isinstance(source, dict):
            data = source
        else:
            p = Path(source)
            if not p.exists():
                return 0
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)

        models_map = data.get("models", {})
        loaded_count = 0
        for state_str, model_dict in models_map.items():
            try:
                baked = BakedModel.from_dict(model_dict)
                self._bake_cache[state_str] = baked
                loaded_count += 1
            except Exception:
                pass
        return loaded_count

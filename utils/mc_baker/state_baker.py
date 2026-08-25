"""
Headless Minecraft BlockState Baker.
Bakes arbitrary complex non-full and directional BlockStates (Stairs, Slabs, Fences,
Lanterns, Chains, Doors, etc.) directly from official JAR / resource pack definitions.
"""

from __future__ import annotations
from typing import Optional, Any, Union
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

# Known Emissive blocks in Minecraft
EMISSIVE_BLOCKS = frozenset({
    "glowstone", "sea_lantern", "shroomlight", "magma_block", "magma",
    "crying_obsidian", "jack_o_lantern", "beacon", "end_rod",
    "lantern", "soul_lantern", "torch", "soul_torch", "wall_torch", "soul_wall_torch",
    "lava", "flowing_lava", "fire", "soul_fire", "conduit", "sculk_catalyst",
    "ochre_froglight", "pearlescent_froglight", "verdant_froglight",
    "minecraft:glowstone", "minecraft:sea_lantern", "minecraft:shroomlight",
    "minecraft:magma_block", "minecraft:magma", "minecraft:crying_obsidian",
    "minecraft:jack_o_lantern", "minecraft:beacon", "minecraft:end_rod",
    "minecraft:lantern", "minecraft:soul_lantern", "minecraft:torch",
    "minecraft:soul_torch", "minecraft:wall_torch", "minecraft:soul_wall_torch",
    "minecraft:lava", "minecraft:flowing_lava", "minecraft:fire",
    "minecraft:soul_fire", "minecraft:conduit", "minecraft:sculk_catalyst",
    "minecraft:ochre_froglight", "minecraft:pearlescent_froglight", "minecraft:verdant_froglight",
})


def is_block_emissive(block_name: str, props: Optional[dict[str, str]] = None) -> bool:
    """Return True if block/state is emissive (light emitting), else False."""
    p = props or {}
    short_name = block_name.split(":", 1)[-1].removeprefix("block/")
    if short_name in EMISSIVE_BLOCKS or block_name in EMISSIVE_BLOCKS or short_name.endswith("_froglight"):
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


def refresh_shared_baker_sources(force_precompile_if_missing: bool = True) -> StateBaker:
    """Synchronize shared StateBaker with the active Resource Pack Stack.
    Enforces that all model sources are 100% precompiled. If precompiled models do not
    exist on disk for the current stack, immediately executes on-the-fly full precompilation.
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
                # Precompiled model cache missing: immediately compile ALL models on the fly!
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

    @staticmethod
    def _resolve_base_face_textures(short_name: str, props: dict[str, str], fallback: str) -> dict[str, str]:
        """Resolve unrotated base 6-face texture stems in local model space."""
        is_lit = props.get("lit") == "true"

        # 1. Furnace, Blast Furnace, Smoker
        if short_name in ("furnace", "blast_furnace", "smoker"):
            top = f"minecraft:block/{short_name}_top"
            bottom = f"minecraft:block/{short_name}_top"
            side = f"minecraft:block/{short_name}_side"
            front = f"minecraft:block/{short_name}_front_on" if is_lit else f"minecraft:block/{short_name}_front"
            return {"east": side, "west": side, "up": top, "down": bottom, "south": side, "north": front}

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
            if is_vertical:
                front = f"minecraft:block/{short_name}_front_vertical"
                top = "minecraft:block/furnace_top"
                return {"east": top, "west": top, "up": front, "down": top, "south": top, "north": top}
            else:
                top = "minecraft:block/furnace_top"
                bottom = "minecraft:block/furnace_top"
                side = "minecraft:block/furnace_side"
                front = f"minecraft:block/{short_name}_front"
                return {"east": side, "west": side, "up": top, "down": bottom, "south": side, "north": front}

        # 4.5 Crafter
        if short_name == "crafter":
            is_crafting = props.get("crafting") == "true"
            is_triggered = props.get("triggered") == "true"
            is_powered = props.get("powered") == "true"
            top = "minecraft:block/crafter_top_triggered" if is_triggered else ("minecraft:block/crafter_top_crafting" if is_crafting else "minecraft:block/crafter_top")
            front = "minecraft:block/crafter_front_powered" if is_powered else "minecraft:block/crafter_front"
            bottom = "minecraft:block/crafter_bottom"
            side = "minecraft:block/crafter_side"
            east = "minecraft:block/crafter_east"
            west = "minecraft:block/crafter_west"
            return {"east": east, "west": west, "up": top, "down": bottom, "south": side, "north": front}

        # 4.6 Glazed Terracotta
        if "glazed_terracotta" in short_name:
            pattern = f"minecraft:block/{short_name}"
            return {d: pattern for d in MC_DIRECTIONS}

        # 5. Observer
        if short_name == "observer":
            top = "minecraft:block/observer_top"
            side = "minecraft:block/observer_side"
            back = "minecraft:block/observer_back"
            front = "minecraft:block/observer_front"
            return {"east": side, "west": side, "up": top, "down": top, "south": back, "north": front}

        # 6. Piston, Sticky Piston
        if short_name in ("piston", "sticky_piston"):
            top = "minecraft:block/piston_top_sticky" if short_name == "sticky_piston" else "minecraft:block/piston_top"
            bottom = "minecraft:block/piston_bottom"
            side = "minecraft:block/piston_side"
            return {"east": side, "west": side, "up": side, "down": side, "south": bottom, "north": top}

        # 7. Barrel
        if short_name == "barrel":
            is_open = props.get("open") == "true"
            top = "minecraft:block/barrel_top_open" if is_open else "minecraft:block/barrel_top"
            bottom = "minecraft:block/barrel_bottom"
            side = "minecraft:block/barrel_side"
            return {"east": side, "west": side, "up": top, "down": bottom, "south": side, "north": side}

        # 8. Respawn Anchor
        if short_name == "respawn_anchor":
            charges = props.get("charges", "0")
            has_charges = str(charges) not in ("0", "")
            top = "minecraft:block/respawn_anchor_top" if has_charges else "minecraft:block/respawn_anchor_top_off"
            bottom = "minecraft:block/respawn_anchor_bottom"
            side = f"minecraft:block/respawn_anchor_side{charges}" if has_charges else "minecraft:block/respawn_anchor_side0"
            return {"east": side, "west": side, "up": top, "down": bottom, "south": side, "north": side}

        # 9. Command Blocks
        if "command_block" in short_name:
            front = f"minecraft:block/{short_name}_front"
            back = f"minecraft:block/{short_name}_back"
            side = f"minecraft:block/{short_name}_side"
            return {"east": side, "west": side, "up": side, "down": side, "south": back, "north": front}

        # 10. Grass Block, Podzol, Mycelium
        if short_name in ("grass_block", "podzol", "mycelium"):
            snowy = props.get("snowy") == "true"
            top = f"minecraft:block/{short_name}_top"
            bottom = "minecraft:block/dirt"
            side = "minecraft:block/grass_block_snow" if snowy else f"minecraft:block/{short_name}_side"
            return {"east": side, "west": side, "up": top, "down": bottom, "south": side, "north": side}

        # 11. Mushroom Blocks
        if short_name in ("red_mushroom_block", "brown_mushroom_block", "mushroom_stem"):
            skin = f"minecraft:block/{short_name}"
            inside = "minecraft:block/mushroom_block_inside"
            return {
                "east": inside if props.get("east") == "false" else skin,
                "west": inside if props.get("west") == "false" else skin,
                "up": inside if props.get("up") == "false" else skin,
                "down": inside if props.get("down") == "false" else skin,
                "south": inside if props.get("south") == "false" else skin,
                "north": inside if props.get("north") == "false" else skin,
            }

        # 12. Axis Blocks (Logs, Wood, Hyphae, Basalt, Hay, Bone)
        is_axis = "axis" in props or short_name.endswith(("_log", "_wood", "_stem", "_hyphae", "basalt", "hay_block", "bone_block"))
        if is_axis:
            top_stem = f"{short_name}_top" if not short_name.endswith(("_wood", "_hyphae")) else (f"{short_name[:-4]}log_top" if short_name.endswith("_wood") else f"{short_name[:-7]}stem_top")
            top = f"minecraft:block/{top_stem}"
            side = f"minecraft:block/{short_name}" if short_name.endswith(("_wood", "_hyphae")) else f"minecraft:block/{short_name}"
            return {"east": side, "west": side, "up": top, "down": top, "south": side, "north": side}

        # 13. Redstone Lamp
        if short_name == "redstone_lamp":
            lamp = "minecraft:block/redstone_lamp_on" if is_lit else "minecraft:block/redstone_lamp"
            return {d: lamp for d in MC_DIRECTIONS}

        # 14. Smart Derivative Fallbacks (Slabs, Stairs, Walls, Fences, Gates, Buttons, Plates, Waxed, Beds, Carpets, Banners)
        stem = short_name
        if stem.startswith("waxed_"):
            stem = stem.removeprefix("waxed_")
        if stem.startswith("potted_"):
            stem = stem.removeprefix("potted_")
        elif stem.endswith("_carpet"):
            stem = stem.replace("_carpet", "_wool")
        elif stem.endswith("_bed"):
            stem = stem.replace("_bed", "_wool")
        elif stem.endswith("_banner") or stem.endswith("_wall_banner"):
            color = stem.replace("_wall_banner", "").replace("_banner", "")
            stem = f"{color}_wool" if color else "white_wool"
        elif stem.endswith("_wood"):
            stem = stem.replace("_wood", "_log")
        elif stem.endswith("_hyphae"):
            stem = stem.replace("_hyphae", "_stem")
        elif "_wall_hanging_sign" in stem:
            wood = stem.replace("_wall_hanging_sign", "")
            stem = f"stripped_{wood}_log" if not wood.startswith("stripped_") else f"{wood}_log"
        elif "_hanging_sign" in stem:
            wood = stem.replace("_hanging_sign", "")
            stem = f"stripped_{wood}_log" if not wood.startswith("stripped_") else f"{wood}_log"
        elif "_wall_sign" in stem:
            stem = stem.replace("_wall_sign", "_planks")
        elif "_sign" in stem:
            stem = stem.replace("_sign", "_planks")
        else:
            for suffix in ("_slab", "_stairs", "_wall", "_fence_gate", "_fence", "_button", "_pressure_plate"):
                if stem.endswith(suffix):
                    base = stem[:-len(suffix)]
                    if base in ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove", "cherry", "pale_oak", "bamboo", "crimson", "warped"):
                        stem = f"{base}_planks"
                    elif base == "bamboo_mosaic":
                        stem = "bamboo_mosaic"
                    elif base in ("stone_brick", "mossy_stone_brick", "nether_brick", "red_nether_brick", "end_stone_brick", "deepslate_brick", "deepslate_tile", "polished_blackstone_brick", "mud_brick", "tuff_brick"):
                        stem = f"{base}s"
                    elif base == "brick":
                        stem = "bricks"
                    elif base == "smooth_sandstone":
                        stem = "sandstone_top"
                    elif base == "smooth_red_sandstone":
                        stem = "red_sandstone_top"
                    elif base == "smooth_quartz":
                        stem = "quartz_block_bottom"
                    elif base == "quartz":
                        stem = "quartz_block_side"
                    elif base == "purpur":
                        stem = "purpur_block"
                    else:
                        stem = base
                    break

        if stem != short_name:
            fallback = f"minecraft:block/{stem}"
            return {d: fallback for d in MC_DIRECTIONS}

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

    @staticmethod
    def _resolve_chest_elements(short_name: str, props: dict[str, str]) -> list[dict]:
        """Construct multipart 3D elements for chests (box + lid + front latch)."""
        facing = props.get("facing", "north")
        chest_type = props.get("type", "single")

        if short_name == "ender_chest":
            tex = "minecraft:entity/chest/ender"
        elif short_name == "trapped_chest":
            if chest_type == "left":
                tex = "minecraft:entity/chest/trapped_left"
            elif chest_type == "right":
                tex = "minecraft:entity/chest/trapped_right"
            else:
                tex = "minecraft:entity/chest/trapped"
        else:
            if chest_type == "left":
                tex = "minecraft:entity/chest/normal_left"
            elif chest_type == "right":
                tex = "minecraft:entity/chest/normal_right"
            else:
                tex = "minecraft:entity/chest/normal"

        rot_angle = 0.0
        if facing == "south":
            rot_angle = 180.0
        elif facing == "west":
            rot_angle = 270.0
        elif facing == "east":
            rot_angle = 90.0

        elem_rot = {"origin": [8, 8, 8], "axis": "y", "angle": rot_angle} if rot_angle != 0.0 else None

        if chest_type == "left":
            body_from = [1, 0, 1]
            body_to = [16, 14, 15]
            latch_from = [15, 7, 0]
            latch_to = [16, 11, 1]
        elif chest_type == "right":
            body_from = [0, 0, 1]
            body_to = [15, 14, 15]
            latch_from = [0, 7, 0]
            latch_to = [1, 11, 1]
        else:
            body_from = [1, 0, 1]
            body_to = [15, 14, 15]
            latch_from = [7, 7, 0]
            latch_to = [9, 11, 1]

        body_faces = {
            "up": {"texture": tex, "uv": [14, 0, 28, 14]},
            "down": {"texture": tex, "uv": [28, 0, 42, 14]},
            "north": {"texture": tex, "uv": [14, 14, 28, 28]},
            "south": {"texture": tex, "uv": [42, 14, 56, 28]},
            "west": {"texture": tex, "uv": [0, 14, 14, 28]},
            "east": {"texture": tex, "uv": [28, 14, 42, 28]},
        }

        latch_faces = {
            "north": {"texture": tex, "uv": [1, 1, 3, 5]},
            "up": {"texture": tex, "uv": [1, 0, 3, 1]},
            "down": {"texture": tex, "uv": [3, 0, 5, 1]},
            "west": {"texture": tex, "uv": [0, 1, 1, 5]},
            "east": {"texture": tex, "uv": [3, 1, 4, 5]},
        }

        elements = [
            {"from": body_from, "to": body_to, "faces": body_faces},
            {"from": latch_from, "to": latch_to, "faces": latch_faces},
        ]
        if elem_rot:
            for elem in elements:
                elem["rotation"] = elem_rot

        return elements

    @staticmethod
    def _resolve_banner_elements(short_name: str, props: dict[str, str]) -> list[dict]:
        """Construct multipart 3D elements for standing and wall banners."""
        is_wall = "_wall_banner" in short_name
        if is_wall:
            color = short_name.replace("_wall_banner", "")
            facing = props.get("facing", "north")
            rot_angle = 0.0
            if facing == "south":
                rot_angle = 180.0
            elif facing == "west":
                rot_angle = 270.0
            elif facing == "east":
                rot_angle = 90.0

            elem_rot = {"origin": [8, 8, 8], "axis": "y", "angle": rot_angle} if rot_angle != 0.0 else None

            wood_tex = "minecraft:block/oak_planks"
            cloth_tex = f"minecraft:block/{color}_wool" if color else "minecraft:block/white_wool"

            crossbar = {
                "from": [2, 12, 14],
                "to": [14, 14, 16],
                "faces": {
                    "north": {"texture": wood_tex, "uv": [2, 12, 14, 14]},
                    "south": {"texture": wood_tex, "uv": [2, 12, 14, 14]},
                    "up": {"texture": wood_tex, "uv": [2, 14, 14, 16]},
                    "down": {"texture": wood_tex, "uv": [2, 14, 14, 16]},
                    "west": {"texture": wood_tex, "uv": [14, 12, 16, 14]},
                    "east": {"texture": wood_tex, "uv": [14, 12, 16, 14]},
                }
            }
            cloth = {
                "from": [3, -5, 14.5],
                "to": [13, 13, 15.5],
                "faces": {
                    "north": {"texture": cloth_tex, "uv": [3, 0, 13, 16]},
                    "south": {"texture": cloth_tex, "uv": [3, 0, 13, 16]},
                    "west": {"texture": cloth_tex, "uv": [14, 0, 15, 16]},
                    "east": {"texture": cloth_tex, "uv": [14, 0, 15, 16]},
                    "down": {"texture": cloth_tex, "uv": [3, 14, 13, 15]},
                }
            }
            elements = [crossbar, cloth]
            if elem_rot:
                for elem in elements:
                    elem["rotation"] = elem_rot
            return elements
        else:
            color = short_name.replace("_banner", "")
            rot_idx = int(props.get("rotation", "0")) if "rotation" in props else 0
            angle = (rot_idx * 22.5) % 360.0
            elem_rot = {"origin": [8, 8, 8], "axis": "y", "angle": angle} if angle != 0.0 else None

            wood_tex = "minecraft:block/oak_planks"
            cloth_tex = f"minecraft:block/{color}_wool" if color else "minecraft:block/white_wool"

            pole = {
                "from": [7.5, 0, 7.5],
                "to": [8.5, 16, 8.5],
                "faces": {
                    "north": {"texture": wood_tex, "uv": [7, 0, 8, 16]},
                    "south": {"texture": wood_tex, "uv": [7, 0, 8, 16]},
                    "east": {"texture": wood_tex, "uv": [7, 0, 8, 16]},
                    "west": {"texture": wood_tex, "uv": [7, 0, 8, 16]},
                    "up": {"texture": wood_tex, "uv": [7, 7, 8, 8]},
                    "down": {"texture": wood_tex, "uv": [7, 7, 8, 8]},
                }
            }
            crossbar = {
                "from": [2, 19, 7.5],
                "to": [14, 20.5, 8.5],
                "faces": {
                    "north": {"texture": wood_tex, "uv": [2, 14, 14, 15]},
                    "south": {"texture": wood_tex, "uv": [2, 14, 14, 15]},
                    "east": {"texture": wood_tex, "uv": [7, 14, 8, 15]},
                    "west": {"texture": wood_tex, "uv": [7, 14, 8, 15]},
                    "up": {"texture": wood_tex, "uv": [2, 7, 14, 8]},
                    "down": {"texture": wood_tex, "uv": [2, 7, 14, 8]},
                }
            }
            cloth = {
                "from": [3, 1, 7.8],
                "to": [13, 19.5, 8.2],
                "faces": {
                    "north": {"texture": cloth_tex, "uv": [3, 0, 13, 16]},
                    "south": {"texture": cloth_tex, "uv": [3, 0, 13, 16]},
                    "east": {"texture": cloth_tex, "uv": [7, 0, 8, 16]},
                    "west": {"texture": cloth_tex, "uv": [7, 0, 8, 16]},
                    "down": {"texture": cloth_tex, "uv": [3, 7, 13, 8]},
                }
            }
            elements = [pole, crossbar, cloth]
            if elem_rot:
                for elem in elements:
                    elem["rotation"] = elem_rot
            return elements

    @staticmethod
    def _resolve_bed_elements(short_name: str, props: dict[str, str]) -> list[dict]:
        """Construct multipart 3D elements for beds (legs + mattress + blanket/pillow)."""
        color = short_name.replace("_bed", "")
        part = props.get("part", "foot")
        facing = props.get("facing", "north")

        rot_angle = 0.0
        if facing == "south":
            rot_angle = 180.0
        elif facing == "west":
            rot_angle = 270.0
        elif facing == "east":
            rot_angle = 90.0

        elem_rot = {"origin": [8, 8, 8], "axis": "y", "angle": rot_angle} if rot_angle != 0.0 else None

        wood_tex = "minecraft:block/oak_planks"
        wool_tex = f"minecraft:block/{color}_wool" if color else "minecraft:block/red_wool"
        white_wool = "minecraft:block/white_wool"

        elements = []
        if part == "foot":
            elements.append({
                "from": [0, 0, 0], "to": [3, 3, 3],
                "faces": {d: {"texture": wood_tex} for d in MC_DIRECTIONS}
            })
            elements.append({
                "from": [13, 0, 0], "to": [16, 3, 3],
                "faces": {d: {"texture": wood_tex} for d in MC_DIRECTIONS}
            })
            elements.append({
                "from": [0, 3, 0], "to": [16, 9, 16],
                "faces": {
                    "up": {"texture": wool_tex},
                    "down": {"texture": wood_tex},
                    "north": {"texture": wool_tex},
                    "south": {"texture": wool_tex},
                    "east": {"texture": wool_tex},
                    "west": {"texture": wool_tex},
                }
            })
        else:
            elements.append({
                "from": [0, 0, 13], "to": [3, 3, 16],
                "faces": {d: {"texture": wood_tex} for d in MC_DIRECTIONS}
            })
            elements.append({
                "from": [13, 0, 13], "to": [16, 3, 16],
                "faces": {d: {"texture": wood_tex} for d in MC_DIRECTIONS}
            })
            elements.append({
                "from": [0, 3, 0], "to": [16, 9, 16],
                "faces": {
                    "up": {"texture": white_wool},
                    "down": {"texture": wood_tex},
                    "north": {"texture": wool_tex},
                    "south": {"texture": white_wool},
                    "east": {"texture": wool_tex},
                    "west": {"texture": wool_tex},
                }
            })

        if elem_rot:
            for elem in elements:
                elem["rotation"] = elem_rot
        return elements

    def bake_block_state(self, state_str: str) -> BakedModel:
        """
        Bake a BlockState string into a fully resolved BakedModel containing all elements,
        quad vertices in [0..1] block space, loop UV coordinates, and 6-face summary.
        """
        state_str_clean = state_str.strip()
        if state_str_clean in self._bake_cache:
            return self._bake_cache[state_str_clean]

        block_id, props = parse_block_state_string(state_str_clean)
        variant_matches = self.state_resolver.resolve_state(state_str_clean)

        baked_elements: list[BakedElement] = []
        six_faces: list[Optional[BakedFace]] = [None] * 6

        short_name = block_id.split(":", 1)[-1]
        fallback_texture = f"minecraft:block/{short_name}"

        is_opaque = not any(w in short_name for w in ("glass", "leaves", "ice", "water", "air", "pane", "fence", "door", "trapdoor", "bars", "chain", "lantern", "stairs", "slab", "chest", "banner", "bed", "carpet", "pot"))
        is_emissive = is_block_emissive(short_name, props)

        for match in variant_matches:
            resolved_model = self.model_parser.resolve_model(match.model_id)
            raw_elements = resolved_model.get("elements", [])

            if not raw_elements:
                if short_name in ("chest", "trapped_chest", "ender_chest"):
                    raw_elements = self._resolve_chest_elements(short_name, props)
                elif short_name.endswith(("_banner", "_wall_banner")):
                    raw_elements = self._resolve_banner_elements(short_name, props)
                elif short_name.endswith("_bed"):
                    raw_elements = self._resolve_bed_elements(short_name, props)
                else:
                    raw_elements = self._resolve_base_face_elements(
                        short_name, props, fallback_texture, resolved_model.get("textures", {})
                    )

            for elem in raw_elements:
                from_pos = tuple(elem.get("from", [0, 0, 0]))
                to_pos = tuple(elem.get("to", [16, 16, 16]))
                elem_rot = elem.get("rotation")
                elem_faces: dict[str, BakedFace] = {}
                is_full_cuboid = (from_pos == (0, 0, 0) and to_pos == (16, 16, 16) and not elem_rot)

                for orig_dir, face_data in elem.get("faces", {}).items():
                    texture = face_data.get("texture", fallback_texture)
                    cullface = face_data.get("cullface")
                    if not cullface and is_full_cuboid:
                        cullface = orig_dir
                    face_rot = float(face_data.get("rotation", 0.0))
                    tint_index = int(face_data.get("tintindex", -1))

                    raw_uv = face_data.get("uv")
                    uv_bounds_16 = (float(raw_uv[0]), float(raw_uv[1]), float(raw_uv[2]), float(raw_uv[3])) if raw_uv else None

                    # Exact Minecraft 26.2 FaceBakery baking
                    new_dir, uv_rot, transformed_verts, loop_uvs, uv_bounds = bake_face_exact(
                        orig_dir=orig_dir,
                        from_pos=from_pos,
                        to_pos=to_pos,
                        uv_bounds=uv_bounds_16,
                        face_rotation_deg=face_rot,
                        rot_x=match.rot_x,
                        rot_y=match.rot_y,
                        elem_rotation=elem_rot,
                        uvlock=match.uvlock,
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

        is_cube = (
            len(baked_elements) >= 1
            and all(
                el.from_pos == (0, 0, 0) and el.to_pos == (16, 16, 16) and not el.rotation
                for el in baked_elements
            )
        )

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

    def bake_all_pack_states(self) -> dict[str, BakedModel]:
        """
        Scan and bake all blockstates in the resource pack / JAR.
        Returns mapping from state_str to BakedModel.
        """
        if not self.resource_loader:
            return {}
        all_block_ids = self.resource_loader.list_all_blockstates()
        baked_dict: dict[str, BakedModel] = {}
        for block_id in all_block_ids:
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
            else:
                try:
                    baked_dict[block_id] = self.bake_block_state(block_id)
                except Exception:
                    pass
        return baked_dict

    def save_precompiled_manifest(self, output_file: Union[str, Path]) -> int:
        """
        Bake all pack states and save to a JSON manifest file on disk.
        Returns the number of baked models saved.
        """
        import json
        baked_dict = self.bake_all_pack_states()
        manifest_data = {
            "format_version": "1.0.0",
            "models_count": len(baked_dict),
            "models": {k: v.to_dict() for k, v in baked_dict.items()},
        }
        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, separators=(",", ":"))
        return len(baked_dict)

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


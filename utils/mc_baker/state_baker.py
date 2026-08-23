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
            face_entry = {"texture": tex}
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
        variant_matches = self.state_resolver.resolve_state(state_str_clean)

        baked_elements: list[BakedElement] = []
        six_faces: list[Optional[BakedFace]] = [None] * 6

        short_name = block_id.split(":", 1)[-1]
        fallback_texture = f"minecraft:block/{short_name}"

        is_opaque = not any(w in short_name for w in ("glass", "leaves", "ice", "water", "air", "pane", "fence", "door", "trapdoor", "bars", "chain", "lantern", "stairs", "slab"))
        is_emissive = any(w in short_name for w in ("glowstone", "sea_lantern", "shroomlight", "magma", "lava", "fire", "lantern", "torch", "crying_obsidian", "beacon", "end_rod"))
        if props.get("lit") == "true":
            is_emissive = True
        if short_name == "respawn_anchor" and int(props.get("charges", "0")) > 0:
            is_emissive = True

        for match in variant_matches:
            resolved_model = self.model_parser.resolve_model(match.model_id)
            raw_elements = resolved_model.get("elements", [])

            if not raw_elements:
                # Default 1x1x1 cube fallback with canonical rotation and state-aware multi-face textures
                raw_elements = self._resolve_base_face_elements(
                    short_name, props, fallback_texture, resolved_model.get("textures", {})
                )

            for elem in raw_elements:
                from_pos = tuple(elem.get("from", [0, 0, 0]))
                to_pos = tuple(elem.get("to", [16, 16, 16]))
                elem_rot = elem.get("rotation")
                elem_faces: dict[str, BakedFace] = {}

                for orig_dir, face_data in elem.get("faces", {}).items():
                    texture = face_data.get("texture", fallback_texture)
                    cullface = face_data.get("cullface")
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

                    elem_faces[new_dir] = baked_face

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
            len(baked_elements) == 1
            and baked_elements[0].from_pos == (0, 0, 0)
            and baked_elements[0].to_pos == (16, 16, 16)
            and not baked_elements[0].rotation
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
            else:
                try:
                    baked_dict[block_id] = self.bake_block_state(block_id)
                except Exception:
                    pass
        return baked_dict


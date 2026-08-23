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

    def clear_cache(self):
        self._bake_cache.clear()
        self.model_parser._model_cache.clear()
        self.state_resolver._state_cache.clear()

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
                # Default 1x1x1 cube fallback
                raw_elements = [
                    {
                        "from": [0, 0, 0],
                        "to": [16, 16, 16],
                        "faces": {
                            d: {"texture": resolved_model.get("textures", {}).get(d, fallback_texture)}
                            for d in MC_DIRECTIONS
                        }
                    }
                ]

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

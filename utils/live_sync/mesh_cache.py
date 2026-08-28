"""
Metadata cache and pre-warming system for Minecraft blockstates during live sync.
Precomputes ParsedBlock, BakedModel, cull metadata, and resolved face textures into RAM.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set
import bpy

from .classifier import (
    parse_and_classify,
    BlockTypeEnum,
    ParsedBlock,
    AIR_BLOCKS,
    TRANSPARENT_BLOCKS,
    FLUID_BLOCKS,
)
from .constants import (
    DIR_TO_INDEX,
    FACES,
)
from ..mc_baker import (
    StateBaker,
    BakedModel,
    BakedFace,
    get_shared_state_baker,
    refresh_shared_baker_sources,
)
from .material_manager import LiveSyncMaterialManager, ResolvedFaceTexture
from ..culling import (
    get_shared_face_culler,
    BlockCullMeta,
)
from .material_binding import (
    get_shared_material_manager,
    clear_shared_material_manager,
    _GLOBAL_MAT_MANAGER,
)
from .hot_states import HOT_PREWARM_STATES

logger = logging.getLogger("MoziToolKit.MeshCache")


class CachedStateMeta:
    """Precomputed metadata and resolved face textures for a unique block state."""
    __slots__ = (
        'state_str', 'parsed', 'is_cube', 'is_opaque', 'is_air',
        'is_fluid', 'is_transparent', 'baked_model', 'faces_info',
        'tex_to_res', 'cull_meta'
    )

    def __init__(self, state_str: str, mat_manager: LiveSyncMaterialManager, baker: StateBaker):
        self.state_str = state_str
        self.parsed: ParsedBlock = parse_and_classify(state_str)
        name_low = self.parsed.name.lower()
        self.is_air = (
            not state_str
            or state_str.strip() in ("", "minecraft:air", "air")
            or name_low in AIR_BLOCKS
            or self.parsed.block_type == BlockTypeEnum.AIR
            or name_low.endswith("air")
        )
        self.is_fluid = not self.is_air and (self.parsed.name in FLUID_BLOCKS or self.parsed.block_type == BlockTypeEnum.FLUID)
        self.is_transparent = not self.is_air and (self.parsed.name in TRANSPARENT_BLOCKS)

        baked: Optional[BakedModel] = None
        if not self.is_air:
            try:
                baked = baker.bake_block_state(self.parsed.full_state)
            except Exception:
                baked = None

        self.baked_model = baked
        if self.is_air:
            self.is_cube = False
            self.is_opaque = False
        elif self.is_fluid:
            self.is_cube = False
            self.is_opaque = False
        elif baked is not None:
            self.is_cube = baked.is_cube
            self.is_opaque = (self.parsed.is_opaque != 0) and not self.is_transparent
        else:
            self.is_cube = self.parsed.block_type == BlockTypeEnum.CUBE
            self.is_opaque = (self.parsed.is_opaque != 0) and not self.is_transparent

        self.cull_meta: BlockCullMeta = get_shared_face_culler().get_meta(
            state_str=self.state_str,
            baked_model=self.baked_model,
            is_opaque_hint=self.is_opaque,
        )

        self.faces_info: dict[str, ResolvedFaceTexture] = {}
        self.tex_to_res: dict[str, ResolvedFaceTexture] = {}

        if not self.is_air:
            json_faces = None
            if self.state_str and self.state_str.startswith("{") and self.state_str.endswith("}"):
                try:
                    import json
                    j_obj = json.loads(self.state_str)
                    if isinstance(j_obj, dict) and isinstance(j_obj.get("faces"), dict):
                        json_faces = j_obj["faces"]
                except Exception:
                    json_faces = None

            # Resolve 6 standard directions
            for f_idx, f_name in enumerate(FACES):
                baked_face = self.baked_model.faces[f_idx] if (self.baked_model and len(self.baked_model.faces) > f_idx) else None
                j_face = json_faces.get(f_name) if json_faces else None
                resolved = mat_manager.resolve_block_face(
                    parsed=self.parsed,
                    face_name=f_name,
                    face_index=f_idx,
                    baked_face=baked_face,
                    json_face_info=j_face,
                )
                self.faces_info[f_name] = resolved
                if f_name == "top":
                    self.faces_info["up"] = resolved
                elif f_name == "bottom":
                    self.faces_info["down"] = resolved

                if baked_face and baked_face.texture:
                    j_tex = j_face.get("tex") if j_face else None
                    if not j_tex or j_tex == baked_face.texture or baked_face.texture not in self.tex_to_res:
                        self.tex_to_res[baked_face.texture] = resolved

            # Also resolve any element-specific textures if present
            if self.baked_model and self.baked_model.elements:
                for elem in self.baked_model.elements:
                    for f_dir, bf in elem.faces.items():
                        if bf.texture and bf.texture not in self.tex_to_res:
                            f_idx = DIR_TO_INDEX.get(f_dir, 0)
                            res = mat_manager.resolve_block_face(
                                parsed=self.parsed,
                                face_name=f_dir,
                                face_index=f_idx,
                                baked_face=bf,
                            )
                            self.tex_to_res[bf.texture] = res

    def get_face_res(self, baked_face: Optional[BakedFace], direction: str) -> ResolvedFaceTexture:
        """Retrieve resolved face texture metadata for a given BakedFace or direction."""
        base_res = None
        if baked_face and baked_face.texture in self.tex_to_res:
            base_res = self.tex_to_res[baked_face.texture]
        else:
            base_res = self.faces_info.get(direction, self.faces_info.get("east", next(iter(self.faces_info.values()), None)))

        if not base_res:
            return base_res

        if baked_face:
            needs_override = False
            rot = base_res.uv_rot if self.is_fluid else 0.0
            if self.is_fluid and baked_face.uv_rot != base_res.uv_rot:
                rot = baked_face.uv_rot
                needs_override = True

            use_tint = base_res.use_tint
            if baked_face.tint_index >= 0 and not use_tint:
                use_tint = True
                needs_override = True

            if needs_override:
                tint_weight = 1.0 if use_tint else 0.0
                hardcoded_weight = base_res.biome_tint_data[3]
                b_tint_data = (base_res.biome_tint_data[0], base_res.biome_tint_data[1], tint_weight, hardcoded_weight)
                b_tint_col = self.parsed.tint_color if use_tint else base_res.biome_tint_color
                return ResolvedFaceTexture(
                    chunk_id=base_res.chunk_id,
                    slot_index=base_res.slot_index,
                    uv_rot=rot,
                    use_tint=use_tint,
                    tint_color=b_tint_col,
                    calc_uv_fn=base_res.calc_uv_fn,
                    anim_timing=base_res.anim_timing,
                    anim_frame_size=base_res.anim_frame_size,
                    uv_tiling_transform=base_res.uv_tiling_transform,
                    biome_tint_data=b_tint_data,
                    biome_tint_color=b_tint_col,
                    source_texture_key=base_res.source_texture_key,
                    model_uv_scale=base_res.model_uv_scale,
                )

        return base_res


_GLOBAL_STATE_META_CACHE: dict[str, CachedStateMeta] = {}
_MAX_STATE_META_CACHE_SIZE: int = 1024

COMMON_PREWARM_STATES = (
    "minecraft:air",
    "minecraft:stone",
    "minecraft:dirt",
    "minecraft:grass_block[snowy=false]",
    "minecraft:glass",
    "minecraft:oak_planks",
    "minecraft:cobblestone",
    "minecraft:water[level=0]",
    "minecraft:lava[level=0]",
)


def get_cached_state_meta(
    state_str: str,
    mat_manager: LiveSyncMaterialManager,
    baker: StateBaker,
) -> CachedStateMeta:
    """Retrieve or compute CachedStateMeta using the bounded global cache."""
    meta = _GLOBAL_STATE_META_CACHE.get(state_str)
    if meta is None:
        if len(_GLOBAL_STATE_META_CACHE) >= _MAX_STATE_META_CACHE_SIZE:
            # Evict oldest entry to keep memory footprint bounded
            oldest_key = next(iter(_GLOBAL_STATE_META_CACHE))
            _GLOBAL_STATE_META_CACHE.pop(oldest_key, None)
        meta = CachedStateMeta(state_str, mat_manager, baker)
        _GLOBAL_STATE_META_CACHE[state_str] = meta
    return meta


def _idle_prewarm_tick() -> None:
    """Legacy stub maintained for backward compatibility (idle timer loop is deprecated)."""
    return None


def preload_sync_world_data(
    palette: Optional[Iterable[str]] = None,
    world_obj: Optional[bpy.types.Object] = None,
    atlas_params: Optional[dict[str, Any]] = None,
) -> int:
    """
    Pre-load and pre-warm active blockstate models, elements, face textures,
    atlas UV mappings, and materials into RAM upon initial world synchronization.
    Only warms active palette and hot common states, avoiding blind full-pack memory bloat.
    """
    refresh_shared_baker_sources()
    baker = get_shared_state_baker()
    mat_manager = get_shared_material_manager(world_obj=world_obj, atlas_params=atlas_params)

    # 1. Warm core high-priority states
    states_to_warm = set(COMMON_PREWARM_STATES)

    # 2. Warm snapshot palette directly without redundant conversion
    if palette:
        for s in palette:
            if s and s.strip():
                states_to_warm.add(s.strip())

    warmed_count = 0
    for state_str in states_to_warm:
        if state_str not in _GLOBAL_STATE_META_CACHE:
            try:
                meta = CachedStateMeta(state_str, mat_manager, baker)
                _GLOBAL_STATE_META_CACHE[state_str] = meta
                warmed_count += 1
            except Exception as e:
                logger.debug(f"Prewarm skipped for {state_str}: {e}")

    logger.info(f"Live Sync: Pre-warmed {len(_GLOBAL_STATE_META_CACHE)} active blockstates in memory ({warmed_count} newly loaded).")
    return len(_GLOBAL_STATE_META_CACHE)


def clear_mesh_builder_caches() -> None:
    """Clear all global state metadata and material manager caches."""
    clear_shared_material_manager()
    _GLOBAL_STATE_META_CACHE.clear()

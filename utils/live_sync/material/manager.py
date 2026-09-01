"""
Dynamic Material Manager and Texture UV Resolver for MoziToolKit Live Sync.
Responsible for:
- Discovering and loading precompiled Atlas Chunk materials into the active Blender scene.
- Dynamically managing material slots on world mesh objects based on active voxel chunks.
- Precise per-face texture addressing (Chunk ID, Atlas Global UV, UV rotation, Biome Tint).
- Full support for standard resolution and HD / High-Resolution Resource Packs (16x - 512x+).
- Reusing standard Atlas Layout and Replacement Engine pipeline rules.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, Set
from pathlib import Path
import bpy
from mathutils import Vector

def _canonical_texture_key(namespace: str, texture_name: str) -> str:
    namespace = (namespace or "minecraft").strip().lower()
    texture_name = (texture_name or "").strip().lower().removesuffix(".png")
    return f"{namespace}:{texture_name}" if texture_name else ""


def _split_texture_key(value: str) -> tuple[str, str]:
    value = (value or "").strip().lower().removesuffix(".png")
    if not value:
        return "minecraft", ""
    if ":" in value:
        namespace, texture_name = value.split(":", 1)
        return namespace or "minecraft", texture_name
    return "minecraft", value


def _remap_local_to_target_uv(
    u_local: float,
    v_local: float,
    target_location: Optional[dict] = None,
    target_chunk: Optional[dict] = None,
) -> tuple[float, float]:
    """Project local UV [0..1] to global Atlas UV [0..1] at Frame 0 for animated and rect textures across HD and standard packs."""
    if target_location and target_chunk:
        packing = target_location.get("packing") or target_chunk.get("packing", "grid")
        is_anim = (target_location.get("kind") == "animation") or (target_chunk.get("kind") == "animation")
        if is_anim or packing in ("rect_bin_pack", "rect", "vertical_columns") or "pixel_x" in target_location:
            px = float(target_location.get("pixel_x", 0))
            # Animation textures place Frame 0 at vertical offset 0 (top of the column strip)
            py = float(target_location.get("pixel_y", 0))
            rw = float(target_location.get("rect_width") or target_location.get("frame_width") or target_chunk.get("tile_size", 16))
            rh = float(target_location.get("rect_height") or target_location.get("frame_height") or target_chunk.get("tile_size", 16))
            aw = float(target_chunk.get("width", 16))
            ah = float(target_chunk.get("height", 16))
            return (
                (px + u_local * rw) / aw,
                1.0 - (py + (1.0 - v_local) * rh) / ah,
            )
        else:
            col = int(target_location.get("tile_column", 0))
            row = int(target_location.get("tile_row", 0))
            ts = float(target_chunk.get("tile_size", 16))
            aw = float(target_chunk.get("width", 16))
            ah = float(target_chunk.get("height", 16))
            return (
                (float(col) + u_local) * ts / aw,
                1.0 - (float(row) + 1.0 - v_local) * ts / ah,
            )
    return u_local, v_local

PROP_PACK_HASH = "mtk:pack_hash"
PROP_PACK_HASH_SHORT = "mtk:pack_hash_short"
PROP_ATLAS_CHUNK_ID = "mtk:atlas_chunk_id"
PROP_ATLAS_MAPPING = "mtk:atlas_mapping"

from ...mc_baker import StateBaker, BakedModel, BakedFace
from ...materials.atlas.addressing import AtlasAddressResolver, ResolvedAtlasAddress
from ...materials.pipeline.provenance import get_effective_pack_hash, is_material_hash_valid
from ...materials.constants import (
    ATLAS_CATEGORY_BLOCKS,
    ATLAS_CATEGORY_CHEST,
    ATLAS_CATEGORY_SHULKER_BOXES,
    ATLAS_CATEGORY_BANNER_PATTERNS,
    ATLAS_CATEGORY_DECORATED_POT,
    ATLAS_CATEGORY_ENTITIES,
)
from ..constants import (
    DEFAULT_ATLAS_WIDTH,
    DEFAULT_ATLAS_HEIGHT,
    DEFAULT_TILE_SIZE,
    DEFAULT_TILES_PER_ROW,
    DEFAULT_ANIM_ATLAS_WIDTH,
    DEFAULT_ANIM_ATLAS_HEIGHT,
    DEFAULT_ANIM_FRAME_WIDTH,
    DEFAULT_ANIM_FRAME_HEIGHT,
    FACES,
)
from ..classifier import (
    ParsedBlock,
    atlas_lookup_keys,
    BlockTypeEnum,
    AIR_BLOCKS,
    FLUID_BLOCKS,
    TRANSPARENT_BLOCKS,
)

logger = logging.getLogger("MoziToolKit.LiveSync.MaterialManager")

# A streamed block can be represented by a multipart model whose faces refer
# to one of these non-block texture categories.  Keep this list deliberately
# narrow: UI/map/painting/etc. chunks are not valid world-block materials and
# must not become material slots on every live-sync object.
LIVE_SYNC_MODEL_ATLAS_CATEGORIES = frozenset({
    ATLAS_CATEGORY_BLOCKS,
    ATLAS_CATEGORY_CHEST,
    ATLAS_CATEGORY_SHULKER_BOXES,
    ATLAS_CATEGORY_BANNER_PATTERNS,
    ATLAS_CATEGORY_DECORATED_POT,
    ATLAS_CATEGORY_ENTITIES,
})


class ResolvedFaceTexture(NamedTuple):
    chunk_id: int
    slot_index: int
    uv_rot: float
    use_tint: bool
    tint_color: tuple[float, float, float, float]
    # Function to calculate Atlas UV from local (u, v) in [0..1]
    calc_uv_fn: Any
    # Shader node attributes
    anim_timing: tuple[float, float, float, float] = (1.0, 1.0, 0.0, 1.0)
    anim_frame_size: tuple[float, float, float, float] = (16.0, 16.0, 0.0, 0.0)
    uv_tiling_transform: tuple[float, float, float, float] = (1.0, 1.0, 0.0, 0.0)
    biome_tint_data: tuple[float, float, float, float] = (1.0, 1.0, 0.0, 0.0)
    biome_tint_color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    source_texture_key: str = ""
    material_props: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    # StateBaker returns Minecraft model UVs normalized against its canonical
    # 16x16 model unit grid.  Entity rectangles (chests, banners, shulkers)
    # are often 64x64, so they need an additional local-space scale before
    # atlas projection.
    model_uv_scale: tuple[float, float] = (1.0, 1.0)


class LiveSyncMaterialManager:
    """
    Dynamic material manager that links precompiled Atlas materials to the scene
    and resolves face-level texture addressing on the fly with full HD resolution support.
    """

    def __init__(self, world_obj: Optional[bpy.types.Object] = None, atlas_params: Optional[dict[str, Any]] = None):
        self.world_obj = world_obj
        self.atlas_params: dict[str, Any] = {}
        if atlas_params:
            self.atlas_params.update(atlas_params)
        self.chunk_materials: dict[int, bpy.types.Material] = {}
        # Atlas chunk identity and Blender material slots are intentionally
        # different domains.  This ordered list is the sole runtime bridge
        # between them; its indices are the only values allowed in
        # MeshPolygon.material_index.
        self._slot_to_chunk: list[int] = []
        self.chunk_to_slot: dict[int, int] = {}
        self.resolver = AtlasAddressResolver(self.atlas_params.get("mapping"), fallback_params=self.atlas_params)
        self._texture_map: dict[str, dict] = self.resolver._locations
        self._chunks_by_id: dict[int, dict] = self.resolver._chunks_by_id
        self._state_face_cache: dict[str, dict[str, ResolvedFaceTexture]] = {}
        self._last_mat_signature: Optional[tuple] = None
        self._atlas_dir: Optional[Path] = None
        self._target_pack_hash: str = ""
        self.refresh()

    def refresh(self) -> None:
        """Synchronize with active scene materials or precompiled pack caches with Hash validation."""
        self._state_face_cache.clear()
        try:
            self._ensure_chunk_materials_with_hash_validation()
            self._build_texture_index_map()
        except Exception as e:
            logger.warning(f"Error during MaterialManager refresh: {e}")

    def _build_texture_index_map(self) -> None:
        """Build multi-key lookup table supporting HD packs, animations, rect-packing, and aliases."""
        mapping = self.atlas_params.get("mapping")
        self.resolver.set_mapping(mapping if isinstance(mapping, dict) else {}, fallback_params=self.atlas_params)
        self._texture_map = self.resolver._locations
        self._chunks_by_id = self.resolver._chunks_by_id

    def _ensure_chunk_materials_with_hash_validation(self) -> None:
        """
        Validates materials against the prebaked pack hash and loads every
        atlas category a block model can reference. If existing materials in
        scene have outdated hash, they are completely rebuilt from the authoritative cache.
        """
        from ...materials.atlas.builder import build_atlas_chunk_materials
        from ...materials.pack.pack_stack import get_configured_pack_stack
        from ...materials.pack.resource_pack import get_cache_dir

        target_pack_hash = get_effective_pack_hash(self.atlas_params)
        if not target_pack_hash:
            try:
                pack_stack = get_configured_pack_stack()
                target_pack_hash = get_effective_pack_hash(pack_stack)
            except Exception:
                pack_stack = None

        atlas_dir: Optional[Path] = None
        cache_root = get_cache_dir()
        if target_pack_hash:
            for cand in (
                cache_root / target_pack_hash / "yefira_world",
                cache_root / target_pack_hash / "full_scene",
                cache_root / target_pack_hash,
            ):
                if cand.exists() and (cand / "atlas_mapping.json").exists():
                    atlas_dir = cand
                    break

        self._atlas_dir = atlas_dir
        self._target_pack_hash = target_pack_hash

        # Determine mapping data authoritatively from cache directory
        mapping = self.atlas_params.get("mapping")
        if not mapping and atlas_dir:
            try:
                import json
                with open(atlas_dir / "atlas_mapping.json", "r", encoding="utf-8") as f:
                    mapping = json.load(f)
                    self.atlas_params["mapping"] = mapping
            except Exception:
                mapping = None

        chunks = mapping.get("chunks", []) if isinstance(mapping, dict) else []
        for c in chunks:
            if isinstance(c, dict) and "chunk_id" in c:
                self._chunks_by_id[int(c["chunk_id"])] = c

        # Load all chunks that are valid sources for a streamed block model.
        default_chunk_ids = [
            int(c.get("chunk_id", i)) for i, c in enumerate(chunks)
            if c.get("category", ATLAS_CATEGORY_BLOCKS) in LIVE_SYNC_MODEL_ATLAS_CATEGORIES
        ] if chunks else []
        if not default_chunk_ids and chunks:
            default_chunk_ids = [int(chunks[0].get("chunk_id", 0))]

        self.chunk_materials.clear()

        # Check existing materials in bpy.data.materials matching chunk_id and target_pack_hash
        candidate_mats: dict[int, list[bpy.types.Material]] = {}
        for mat in bpy.data.materials:
            cid = mat.get(PROP_ATLAS_CHUNK_ID, mat.get("mtk:atlas_chunk_id", None))
            if cid is not None:
                try:
                    cid_int = int(cid)
                except (ValueError, TypeError):
                    continue
                if not default_chunk_ids or cid_int in default_chunk_ids:
                    mat_hash = get_effective_pack_hash(mat)
                    if not target_pack_hash or not mat_hash or mat_hash == target_pack_hash:
                        candidate_mats.setdefault(cid_int, []).append(mat)

        def _score_candidate(m: bpy.types.Material, c_id: int) -> int:
            score = 0
            m_hash = get_effective_pack_hash(m)
            if target_pack_hash and m_hash == target_pack_hash:
                score += 1000
            elif not target_pack_hash and m_hash:
                score += 500
            elif not m_hash:
                score += 100
            if self.world_obj:
                world_mat_names = {slot.material.name for slot in self.world_obj.material_slots if slot.material}
                if m.name in world_mat_names:
                    score += 200
            if m.name == f"MC_Atlas_Chunk_{c_id}":
                score += 100
            elif "." in m.name and m.name.rsplit(".", 1)[1].isdigit():
                score -= 100
            return score

        for cid_int, mats in candidate_mats.items():
            if mats:
                mats.sort(key=lambda m: _score_candidate(m, cid_int), reverse=True)
                self.chunk_materials[cid_int] = mats[0]

        # Check if any required default chunk material is missing or outdated and rebuild from prebaked atlas
        missing_chunks = [cid for cid in default_chunk_ids if cid not in self.chunk_materials]
        if missing_chunks and atlas_dir:
            try:
                rebuilt_mats = build_atlas_chunk_materials(
                    atlas_dir=atlas_dir,
                    pack_hash=target_pack_hash,
                    pack_textures=True,
                    uv_attribute=None,  # Use native Blender UVMap
                    chunk_ids=missing_chunks,
                    enable_uv_tiling=False,
                )
                for r_cid, r_mat in rebuilt_mats.items():
                    self.chunk_materials[r_cid] = r_mat
            except Exception as e:
                logger.warning(f"Failed to build precompiled atlas chunk materials: {e}")

        # Setup object material slots
        if self.world_obj:
            self._sync_object_material_slots()
        else:
            self._refresh_flat_slot_mapping()

    def ensure_chunk_loaded(self, chunk_id: int) -> int:
        """Dynamically load and bind a material chunk on demand if not already loaded in the scene."""
        if chunk_id in self.chunk_materials:
            current_mat = self.chunk_materials[chunk_id]
            cur_hash = get_effective_pack_hash(current_mat)
            if not self._target_pack_hash or not cur_hash or cur_hash == self._target_pack_hash:
                if chunk_id not in self.chunk_to_slot:
                    if self.world_obj:
                        self._sync_object_material_slots()
                    else:
                        self._refresh_flat_slot_mapping()
                return self.chunk_to_slot.get(chunk_id, 0)

        # 1. Try finding existing valid material in bpy.data.materials
        matching_mats = []
        for mat in bpy.data.materials:
            cid = mat.get(PROP_ATLAS_CHUNK_ID, mat.get("mtk:atlas_chunk_id", None))
            if cid is not None:
                try:
                    if int(cid) == chunk_id:
                        mat_hash = get_effective_pack_hash(mat)
                        if not self._target_pack_hash or not mat_hash or mat_hash == self._target_pack_hash:
                            matching_mats.append(mat)
                except (ValueError, TypeError):
                    continue

        found_mat = None
        if matching_mats:
            def _score_loaded(m: bpy.types.Material) -> int:
                score = 0
                m_hash = get_effective_pack_hash(m)
                if self._target_pack_hash and m_hash == self._target_pack_hash:
                    score += 1000
                elif not m_hash:
                    score += 100
                if self.world_obj:
                    world_mat_names = {slot.material.name for slot in self.world_obj.material_slots if slot.material}
                    if m.name in world_mat_names:
                        score += 200
                if m.name == f"MC_Atlas_Chunk_{chunk_id}":
                    score += 100
                elif "." in m.name and m.name.rsplit(".", 1)[1].isdigit():
                    score -= 100
                return score

            matching_mats.sort(key=_score_loaded, reverse=True)
            found_mat = matching_mats[0]

        if found_mat:
            self.chunk_materials[chunk_id] = found_mat
        elif self._atlas_dir:
            try:
                from ...materials.atlas.builder import build_atlas_chunk_materials
                rebuilt_mats = build_atlas_chunk_materials(
                    atlas_dir=self._atlas_dir,
                    pack_hash=self._target_pack_hash,
                    pack_textures=True,
                    uv_attribute=None,
                    chunk_ids=[chunk_id],
                    enable_uv_tiling=False,
                )
                for r_cid, r_mat in rebuilt_mats.items():
                    self.chunk_materials[r_cid] = r_mat
            except Exception as e:
                logger.warning(f"Failed to on-demand build chunk {chunk_id}: {e}")

        if self.world_obj:
            self._sync_object_material_slots()
        else:
            self._refresh_flat_slot_mapping()

        return self.chunk_to_slot.get(chunk_id, 0)

    def _sync_object_material_slots(self) -> None:
        """Synchronize the root object's compact, stable chunk-to-slot layout."""
        if self.world_obj and getattr(self.world_obj, "data", None) is not None and hasattr(self.world_obj.data, "materials"):
            self.sync_material_slots(self.world_obj)
        else:
            self._refresh_flat_slot_mapping()

    def _refresh_flat_slot_mapping(self) -> None:
        """Maintain a compact mapping without treating sparse chunk IDs as slots."""
        loaded = {cid for cid, mat in self.chunk_materials.items() if mat}
        retained = [cid for cid in self._slot_to_chunk if cid in loaded]
        retained_set = set(retained)
        # New chunks append instead of reordering existing slots.  Cached
        # geometry therefore remains valid during an incremental sync.
        retained.extend(sorted(loaded - retained_set))
        self._slot_to_chunk = retained
        self.chunk_to_slot = {cid: slot for slot, cid in enumerate(retained)}

    def sync_material_slots(self, obj: bpy.types.Object) -> bool:
        """Apply the flattened slot layout to any Live Sync mesh object.

        This is deliberately separate from atlas chunk IDs: a chunk numbered
        11 may occupy Blender slot 4, and no empty intermediate slots are
        created.
        Returns True if material slots were changed, False if already up-to-date.
        """
        self._refresh_flat_slot_mapping()
        if not obj or getattr(obj, "data", None) is None or not hasattr(obj.data, "materials"):
            return False
        expected = [self.chunk_materials[cid] for cid in self._slot_to_chunk]
        slots = obj.data.materials
        if list(slots) == expected:
            return False
        slots.clear()
        for material in expected:
            slots.append(material)
        return True

    def _update_chunk_to_slot_map(self) -> None:
        """Compatibility wrapper for callers of the former slot-scanning API."""
        self._refresh_flat_slot_mapping()

    def get_slot_for_chunk(self, chunk_id: int) -> int:
        """Return the material slot index for a given Chunk ID, loading it on-demand if necessary."""
        if chunk_id in self.chunk_to_slot and chunk_id in self.chunk_materials:
            return self.chunk_to_slot[chunk_id]
        return self.ensure_chunk_loaded(chunk_id)

    def resolve_block_face(
        self,
        parsed: ParsedBlock,
        face_name: str,
        face_index: int,
        baked_face: Optional[BakedFace] = None,
        json_face_info: Optional[dict[str, Any]] = None,
    ) -> ResolvedFaceTexture:
        """
        Dynamically address texture chunk and UV coordinate rule for a specific block face.
        Fully supports standard & High-Resolution (HD 16x - 512x) Texture Packs and Animation/Rect Chunks.
        Delegates authoritative atlas addressing to AtlasAddressResolver.
        """
        c_lut = self.atlas_params.get("block_face_chunk_lut")
        t_lut = self.atlas_params.get("block_face_tint_lut")
        res = self.resolver.resolve_dynamic_face(
            parsed=parsed,
            face_name=face_name,
            face_index=face_index,
            baked_face=baked_face,
            json_face_info=json_face_info,
            block_face_chunk_lut=c_lut,
            block_face_tint_lut=t_lut,
            fallback_params=self.atlas_params,
        )
        slot_index = self.get_slot_for_chunk(res.chunk_id)
        location = res.location or {}
        target_chunk = self.resolver.get_target_chunk(res.chunk_id, fallback_params=self.atlas_params)
        packing = location.get("packing") or target_chunk.get("packing", "grid")
        is_rect = (
            packing in ("rect_bin_pack", "rect", "vertical_columns")
            or "pixel_x" in location
        )
        # StateBaker models and external assets (JMC2OBJ, ICECube) adhere to
        # canonical [0..1] normalized UV coordinates for their target texture rect.
        model_uv_scale = (1.0, 1.0)
        return ResolvedFaceTexture(
            chunk_id=res.chunk_id,
            slot_index=slot_index,
            uv_rot=res.uv_rot,
            use_tint=bool(res.biome_tint_data[2] > 0 or res.biome_tint_data[3] > 0),
            tint_color=res.biome_tint_color,
            calc_uv_fn=res.calc_uv_fn,
            anim_timing=res.anim_timing,
            anim_frame_size=res.anim_frame_size,
            uv_tiling_transform=res.uv_tiling_transform,
            biome_tint_data=res.biome_tint_data,
            biome_tint_color=res.biome_tint_color,
            source_texture_key=res.source_texture_key,
            material_props=getattr(res, "material_props", (0.0, 0.0, 0.0, 0.0)),
            model_uv_scale=model_uv_scale,
        )

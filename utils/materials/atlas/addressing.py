"""
Unified Authoritative Atlas Addressing System for MoziToolKit.

Provides the single source of truth for texture addressing into Atlas Chunks:
1. Static Mesh Replacement (Mineways, Jmc2Obj, Ice-Cube, Generic OBJ/FBX, Face Provenance)
2. Dynamic Mesh Sync (Live Sync / Direct Mesh real-time voxel streaming patch)
3. Model Baking (mc_baker custom resource pack models and elements)

Features:
- Authoritative multi-level texture indexing (canonical keys, stems, aliases)
- Scene Object Blacklist enforcement (filters living mob entities, UI, and map graphics)
- Sub-pixel precise UV projection for standard and HD packs (16x to 512x+)
- Animation Frame 0 column-strip coordinate mapping and timing metadata
- Consistent face provenance generation (mtk_source_texture_key)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set, Tuple, Union

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from ..constants import (
    DEFAULT_NAMESPACE,
    FACE_ORDER,
    FALLBACK_TEXTURE_KEY,
    BLOCK_TO_TEXTURE_ALIASES,
    is_scene_blacklisted,
    ATTR_SOURCE_TEXTURE_KEY,
    ATTR_ATLAS_CHUNK_ID,
    ATTR_ATLAS_TEXTURE_ID,
)
from ..pipeline.provenance import (
    canonical_texture_key,
    split_texture_key,
    detect_material_mode,
)
from .layout import (
    remap_local_to_target_uv,
    find_texture_id_from_atlas_uv,
)

logger = logging.getLogger("MoziToolKit.AtlasAddressing")

# Canonical animated block name aliases (water, lava, fire, portal, sea_lantern, etc.)
ANIMATED_BLOCK_ALIASES: dict[str, list[str]] = {
    "water": ["water_still", "minecraft:block/water_still", "water_flow", "minecraft:block/water_flow"],
    "flowing_water": ["water_flow", "minecraft:block/water_flow", "water_still"],
    "lava": ["lava_still", "minecraft:block/lava_still", "lava_flow", "minecraft:block/lava_flow"],
    "flowing_lava": ["lava_flow", "minecraft:block/lava_flow", "lava_still"],
    "fire": ["fire_0", "minecraft:block/fire_0", "fire_1", "minecraft:block/fire_1"],
    "soul_fire": ["soul_fire_0", "minecraft:block/soul_fire_0", "soul_fire_1", "minecraft:block/soul_fire_1"],
    "portal": ["nether_portal", "minecraft:block/nether_portal"],
    "nether_portal": ["nether_portal", "minecraft:block/nether_portal"],
    "sea_lantern": ["sea_lantern", "minecraft:block/sea_lantern"],
    "magma_block": ["magma", "minecraft:block/magma", "magma_block", "minecraft:block/magma_block"],
    "magma": ["magma", "minecraft:block/magma"],
    "prismarine": ["prismarine", "minecraft:block/prismarine"],
    "campfire": ["campfire_fire", "minecraft:block/campfire_fire"],
    "soul_campfire": ["soul_campfire_fire", "minecraft:block/soul_campfire_fire"],
    "respawn_anchor": ["respawn_anchor_top", "minecraft:block/respawn_anchor_top"],
    "kelp": ["kelp", "minecraft:block/kelp", "kelp_plant"],
    "lantern": ["lantern", "minecraft:block/lantern"],
    "soul_lantern": ["soul_lantern", "minecraft:block/soul_lantern"],
    "sculk_sensor": ["sculk_sensor_top", "minecraft:block/sculk_sensor_top"],
    "sculk_shrieker": ["sculk_shrieker_top", "minecraft:block/sculk_shrieker_top"],
    "sculk_catalyst": ["sculk_catalyst_top", "minecraft:block/sculk_catalyst_top"],
}

# Canonical entity and special block texture aliases
ENTITY_BLOCK_ALIASES: dict[str, list[str]] = {
    "chest": ["entity/chest/normal", "chest/normal", "minecraft:entity/chest/normal"],
    "trapped_chest": ["entity/chest/trapped", "chest/trapped", "minecraft:entity/chest/trapped"],
    "ender_chest": ["entity/chest/ender", "chest/ender", "minecraft:entity/chest/ender"],
    "banner_base": ["entity/banner/base", "entity/banner_base", "minecraft:entity/banner/base"],
    "banner": ["entity/banner/base", "entity/banner_base", "minecraft:entity/banner/base"],
}

# Standard hardcoded tint blocks for vanilla blocks that do not use colormaps
HARDCODED_TINTS: dict[str, tuple[float, float, float, float]] = {
    "spruce_leaves": (0.380, 0.600, 0.380, 1.0),
    "birch_leaves": (0.502, 0.655, 0.333, 1.0),
    "lily_pad": (0.125, 0.502, 0.188, 1.0),
    "redstone_wire": (0.620, 0.004, 0.004, 1.0),
}


class ResolvedAtlasAddress(NamedTuple):
    """Immutable resolved Atlas address containing chunk ID, texture ID, and projection functions."""
    chunk_id: int
    texture_id: int
    location: dict
    calc_uv_fn: Callable[[float, float], tuple[float, float]]
    source_texture_key: str
    is_animated: bool
    anim_timing: tuple[float, float, float, float] = (1.0, 1.0, 0.0, 1.0)
    anim_frame_size: tuple[float, float, float, float] = (16.0, 16.0, 0.0, 0.0)
    biome_tint_data: tuple[float, float, float, float] = (1.0, 1.0, 0.0, 0.0)
    biome_tint_color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    uv_rot: float = 0.0
    uv_tiling_transform: tuple[float, float, float, float] = (1.0, 1.0, 0.0, 0.0)


class AtlasAddressResolver:
    """
    Authoritative single-source-of-truth Atlas Address Resolver.

    Ingests an Atlas mapping dictionary (or builds from disk) and provides:
    - O(1) texture index lookup with fallback aliases and blacklist filtering
    - UV projection from local [0..1] quad space to global Atlas UV [0..1]
    - Static mesh face provenance resolution
    - Dynamic voxel face resolution (as a Live Sync patch)
    - mc_baker custom model face bridging
    """

    def __init__(self, mapping: Optional[dict[str, Any]] = None, fallback_params: Optional[dict[str, Any]] = None):
        self.mapping: dict[str, Any] = mapping or {}
        self.fallback_params: dict[str, Any] = dict(fallback_params or {})
        self._chunks_by_id: dict[int, dict] = {}
        self._locations: dict[str, dict] = {}
        self._reverse_locations: dict[tuple[int, int], dict] = {}
        self._animations_by_chunk: dict[int, list[dict]] = {}
        self._animations_by_key: dict[str, dict] = {}
        self._block_states: dict[str, dict] = {}
        self._build_index()

    def set_mapping(self, mapping: dict[str, Any], fallback_params: Optional[dict[str, Any]] = None) -> None:
        """Update mapping data and rebuild internal lookup tables."""
        self.mapping = mapping or {}
        if fallback_params is not None:
            self.fallback_params = dict(fallback_params)
        self._build_index()

    def _build_index(self) -> None:
        """Build high-performance multi-key lookup indices with blacklist filtering."""
        self._chunks_by_id.clear()
        self._locations.clear()
        self._reverse_locations.clear()
        self._animations_by_chunk.clear()
        self._animations_by_key.clear()
        self._block_states.clear()

        if not isinstance(self.mapping, dict):
            return

        # 1. Index chunks
        for chunk in self.mapping.get("chunks", []):
            if isinstance(chunk, dict) and "chunk_id" in chunk:
                self._chunks_by_id[int(chunk["chunk_id"])] = chunk

        # 2. Index raw textures from mapping
        raw_textures = self.mapping.get("textures", {})
        if isinstance(raw_textures, dict):
            for name, location in raw_textures.items():
                if not isinstance(location, dict):
                    continue

                tex_key = location.get("texture_key", name)
                # Scene Blacklist check: living mobs, UI, and map graphics must not pollute the index
                if is_scene_blacklisted(tex_key) or is_scene_blacklisted(name):
                    continue

                ns, tex_name = split_texture_key(tex_key)
                canon = canonical_texture_key(ns, tex_name)
                self._locations[canon] = location
                self._locations[tex_key] = location
                self._locations[name] = location

                leg_ns, leg_tex = split_texture_key(name)
                self._locations.setdefault(canonical_texture_key(leg_ns, leg_tex), location)

                # Index reverse location for fast (chunk_id, texture_id) lookup
                try:
                    cid = int(location.get("chunk_id", 0))
                    tid = int(location.get("texture_id", 0))
                    self._reverse_locations[(cid, tid)] = location
                except (TypeError, ValueError):
                    cid = 0

                # Register unqualified short-name aliases only for scene-compatible categories
                target_chunk = self._chunks_by_id.get(cid, {})
                category = location.get("category") or target_chunk.get("category", "blocks")
                if category in ("blocks", "items", "chest", "banner_patterns", "shulker_boxes", "entities"):
                    short_name = tex_name.rsplit("/", 1)[-1] if "/" in tex_name else tex_name
                    if not is_scene_blacklisted(short_name):
                        self._locations.setdefault(short_name, location)
                        self._locations.setdefault(f"minecraft:{short_name}", location)
                        if category == "blocks":
                            self._locations.setdefault(f"minecraft:block/{short_name}", location)
                        elif category == "items":
                            self._locations.setdefault(f"minecraft:item/{short_name}", location)
                        elif category == "chest":
                            self._locations.setdefault(f"minecraft:entity/chest/{short_name}", location)

        # 3. Index animations (overwrites static fallbacks for animated textures)
        animations = self.mapping.get("animations", [])
        if isinstance(animations, list):
            for anim in animations:
                if not isinstance(anim, dict):
                    continue
                tex_key = anim.get("texture_key") or anim.get("name", "")
                if is_scene_blacklisted(tex_key):
                    continue

                cid = int(anim.get("chunk_id", 0))
                target_chunk = self._chunks_by_id.get(cid, {})
                anim_loc = {
                    "chunk_id": cid,
                    "texture_id": int(anim.get("texture_id", 0)),
                    "kind": "animation",
                    "category": anim.get("category", "blocks"),
                    "namespace": anim.get("namespace", "minecraft"),
                    "pixel_x": float(anim.get("pixel_x", 0)),
                    "pixel_y": 0.0,  # Always Frame 0
                    "frame_width": float(anim.get("frame_width") or target_chunk.get("tile_size", 16)),
                    "frame_height": float(anim.get("frame_height") or target_chunk.get("tile_size", 16)),
                    "frame_count": int(anim.get("frame_count", 1)),
                    "frametime": int(anim.get("frametime", 2)),
                    "interpolate": bool(anim.get("interpolate", False)),
                    "default_tint_weight": float(anim.get("default_tint_weight", 0.0)),
                    "texture_key": tex_key,
                }

                ns, tex_name = split_texture_key(tex_key)
                canon = canonical_texture_key(ns, tex_name)
                self._locations[canon] = anim_loc
                self._locations[tex_key] = anim_loc
                if anim.get("name"):
                    self._locations[anim["name"]] = anim_loc

                short_name = tex_name.rsplit("/", 1)[-1] if "/" in tex_name else tex_name
                self._locations[short_name] = anim_loc
                self._locations[f"minecraft:{short_name}"] = anim_loc
                self._locations[f"minecraft:block/{short_name}"] = anim_loc

                # Reverse location & animation tables
                tid = int(anim.get("texture_id", 0))
                self._reverse_locations[(cid, tid)] = anim_loc
                self._animations_by_chunk.setdefault(cid, []).append(anim)
                self._animations_by_key[canon] = anim
                self._animations_by_key[tex_key] = anim

        # 4. Standard animated block aliases
        for base_key, cands in ANIMATED_BLOCK_ALIASES.items():
            for cand in cands:
                cand_ns, cand_name = split_texture_key(cand)
                canon_cand = canonical_texture_key(cand_ns, cand_name)
                cand_loc = self._locations.get(canon_cand) or self._locations.get(cand)
                if cand_loc:
                    self._locations.setdefault(base_key, cand_loc)
                    self._locations.setdefault(f"minecraft:{base_key}", cand_loc)
                    self._locations.setdefault(f"minecraft:block/{base_key}", cand_loc)
                    break

        # 5. Entity block aliases (chest, banner, etc.)
        for base_key, cands in ENTITY_BLOCK_ALIASES.items():
            for cand in cands:
                cand_ns, cand_name = split_texture_key(cand)
                canon_cand = canonical_texture_key(cand_ns, cand_name)
                cand_loc = self._locations.get(canon_cand) or self._locations.get(cand)
                if cand_loc:
                    self._locations.setdefault(base_key, cand_loc)
                    self._locations.setdefault(f"minecraft:{base_key}", cand_loc)
                    break

        # 6. BlockStates pre-baked table
        block_states = self.mapping.get("block_states", {})
        if isinstance(block_states, dict):
            self._block_states.update(block_states)

    def is_blacklisted(self, texture_key_or_path: str) -> bool:
        """Check if a candidate texture is rejected by the scene object blacklist."""
        return is_scene_blacklisted(texture_key_or_path)

    def lookup_texture(
        self,
        candidate_or_candidates: Union[str, list[str], tuple[str, ...]],
        namespace: str = DEFAULT_NAMESPACE,
    ) -> Optional[dict]:
        """
        Authoritative lookup resolving a candidate or list of candidates to an Atlas location dict.
        Filters out scene-blacklisted candidates (Mobs, UI, Map graphics).
        """
        if isinstance(candidate_or_candidates, str):
            candidates = [candidate_or_candidates]
        else:
            candidates = list(candidate_or_candidates)

        for cand in candidates:
            if not cand or not isinstance(cand, str):
                continue
            cand_clean = cand.strip()
            if self.is_blacklisted(cand_clean):
                continue

            # 1. Exact lookup
            if cand_clean in self._locations:
                return self._locations[cand_clean]

            cand_ns, cand_name = split_texture_key(cand_clean)
            target_ns = cand_ns if cand_ns != DEFAULT_NAMESPACE else namespace

            # 2. Canonical key lookup
            canon = canonical_texture_key(target_ns, cand_name)
            if canon in self._locations:
                return self._locations[canon]

            # 3. Path variations: try block/ or item/ prefix
            if "/" not in cand_name:
                cand_block = f"{target_ns}:block/{cand_name}"
                if cand_block in self._locations:
                    return self._locations[cand_block]
                cand_item = f"{target_ns}:item/{cand_name}"
                if cand_item in self._locations:
                    return self._locations[cand_item]

            # 4. Short stem lookup
            stem = cand_name.rsplit("/", 1)[-1]
            if stem and not self.is_blacklisted(stem):
                if stem in self._locations:
                    return self._locations[stem]
                stem_canon = canonical_texture_key(target_ns, stem)
                if stem_canon in self._locations:
                    return self._locations[stem_canon]

            # 5. Check BLOCK_TO_TEXTURE_ALIASES
            if stem in BLOCK_TO_TEXTURE_ALIASES:
                for alt in BLOCK_TO_TEXTURE_ALIASES[stem]:
                    alt_loc = self.lookup_texture(alt, namespace=target_ns)
                    if alt_loc:
                        return alt_loc

        return None

    def remap_uv(
        self,
        u_local: float,
        v_local: float,
        location: Optional[dict] = None,
        chunk: Optional[dict] = None,
    ) -> tuple[float, float]:
        """
        Authoritatively project local [0..1] UV to global Atlas UV [0..1].
        Supports Standard and HD Packs (16x to 512x+), Rect Packing, and Animation Strips (Frame 0).
        """
        if not location:
            return u_local, v_local

        cid = int(location.get("chunk_id", 0))
        target_chunk = chunk or self._chunks_by_id.get(cid, {})
        return remap_local_to_target_uv(u_local, v_local, target_location=location, target_chunk=target_chunk)

    def get_target_chunk(
        self,
        chunk_id: int,
        fallback_params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Return chunk metadata, falling back to mapping or runtime parameters if not in chunks."""
        if chunk_id in self._chunks_by_id:
            return self._chunks_by_id[chunk_id]

        fp = fallback_params if fallback_params is not None else self.fallback_params
        w = float(fp.get("width") or self.mapping.get("width") or 1024)
        h = float(fp.get("height") or self.mapping.get("height") or 512)
        ts = float(fp.get("tile_size") or self.mapping.get("tile_size") or 16)
        tpr = int(fp.get("tiles_per_row") or self.mapping.get("tiles_per_row") or 64)

        return {
            "chunk_id": chunk_id,
            "width": w,
            "height": h,
            "tile_size": ts,
            "tiles_per_row": tpr,
        }

    def get_calc_uv_fn(
        self,
        location: Optional[dict] = None,
        chunk: Optional[dict] = None,
        fallback_params: Optional[dict[str, Any]] = None,
    ) -> Callable[[float, float], tuple[float, float]]:
        """Return a self-contained closure that maps local UV to global Atlas UV for a specific location."""
        captured_loc = location
        cid = int(location.get("chunk_id", 0)) if location else 0
        captured_chunk = chunk or self.get_target_chunk(cid, fallback_params=fallback_params)

        def calc_uv(u: float, v: float) -> tuple[float, float]:
            return self.remap_uv(u, v, location=captured_loc, chunk=captured_chunk)

        return calc_uv

    def resolve_static_face(
        self,
        mesh: bpy.types.Mesh,
        poly_idx: int,
        slot_mat: Optional[bpy.types.Material],
        source_key: str = "",
        orig_mode: Optional[str] = None,
    ) -> tuple[str, list[str], Optional[dict]]:
        """
        Resolve texture candidates and Atlas location for a static mesh polygon face.
        Preserves established static mesh replacement logic (face provenance, Mineways UV decode,
        prior atlas chunk attributes, and format adapter candidates).
        """
        provenance = None
        if source_key:
            namespace, texture_name = split_texture_key(source_key)
            if texture_name and not self.is_blacklisted(texture_name):
                cands = [texture_name]
                if "/" in texture_name:
                    stem = texture_name.rsplit("/", 1)[-1]
                    if stem and stem != texture_name:
                        cands.append(stem)
                provenance = (namespace, cands)

        mat_mode = orig_mode or (detect_material_mode(slot_mat) if slot_mat else "GENERIC")

        # 1. Reverse lookup from existing Atlas Chunk attributes if present
        if mat_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and mesh:
            chunk_attr = mesh.attributes.get(ATTR_ATLAS_CHUNK_ID) or mesh.attributes.get("atlas_chunk_id")
            tex_attr = mesh.attributes.get(ATTR_ATLAS_TEXTURE_ID) or mesh.attributes.get("atlas_texture_id")
            chunk_id = None
            texture_id = None
            if chunk_attr and poly_idx < len(chunk_attr.data):
                val = chunk_attr.data[poly_idx].value
                if val >= 0:
                    chunk_id = int(val)
            if tex_attr and poly_idx < len(tex_attr.data):
                val = tex_attr.data[poly_idx].value
                if val >= 0:
                    texture_id = int(val)
            if chunk_id is None and slot_mat and "mtk:atlas_chunk_id" in slot_mat:
                chunk_id = int(slot_mat["mtk:atlas_chunk_id"])

            if chunk_id is not None and texture_id is not None:
                existing_loc = self._reverse_locations.get((chunk_id, texture_id))
                if existing_loc:
                    ns, tname = split_texture_key(existing_loc.get("texture_key", ""))
                    return (*provenance, existing_loc) if provenance else (ns, [tname], existing_loc)

        # 2. Mineways Atlas UV decoding
        if mat_mode == "MINEWAYS_ATLAS" and mesh and slot_mat:
            from ..matching.mineways_atlas import find_mineways_atlas_image, decode_mineways_face_uv
            from ..matching.mineways import MINEWAYS_BLOCK_NAME_ALIASES
            from ..matching.jmc2obj import _expand_semantic_candidates
            uv_layer = mesh.uv_layers.active_render or mesh.uv_layers.active
            if uv_layer and poly_idx < len(mesh.polygons):
                poly = mesh.polygons[poly_idx]
                img = find_mineways_atlas_image(slot_mat)
                tex_name, alt_name, _ = decode_mineways_face_uv(poly, uv_layer, image=img)
                if tex_name:
                    mw_cands = []
                    for name in (tex_name, alt_name):
                        if name:
                            clean_n = name.strip().lower()
                            if clean_n in MINEWAYS_BLOCK_NAME_ALIASES:
                                mw_cands.extend(MINEWAYS_BLOCK_NAME_ALIASES[clean_n])
                            mw_cands.append(f"block/{clean_n}")
                            mw_cands.append(clean_n)
                            mw_cands.extend(_expand_semantic_candidates(clean_n))
                    clean_cands = [c for c in mw_cands if not self.is_blacklisted(c)]
                    loc = self.lookup_texture(clean_cands)
                    return (*provenance, loc) if provenance else (DEFAULT_NAMESPACE, clean_cands, loc)

        if provenance:
            loc = self.lookup_texture(provenance[1], namespace=provenance[0])
            return provenance[0], provenance[1], loc

        # 3. Format adapter extraction fallback
        if slot_mat:
            from ..matching import extract_material_texture_keys
            adapter_ns, adapter_candidates = extract_material_texture_keys(slot_mat)
            clean_cands = [c for c in adapter_candidates if not self.is_blacklisted(c)]
            loc = self.lookup_texture(clean_cands, namespace=adapter_ns)
            return adapter_ns, clean_cands, loc

        return DEFAULT_NAMESPACE, [], None

    def resolve_dynamic_face(
        self,
        parsed: Any,
        face_name: str,
        face_index: int,
        baked_face: Optional[Any] = None,
        json_face_info: Optional[dict[str, Any]] = None,
        slot_index: int = 0,
        block_face_chunk_lut: Optional[dict[str, Any]] = None,
        block_face_tint_lut: Optional[dict[str, Any]] = None,
        fallback_params: Optional[dict[str, Any]] = None,
    ) -> ResolvedAtlasAddress:
        """
        Authoritative Dynamic Mesh (Live Sync) addressing patch.

        Connects real-time voxel streaming and mc_baker models to the unified Atlas.
        """
        tex_name: Optional[str] = None
        uv_rot: float = 0.0
        tint_idx: int = -1

        # 1. Highest priority: explicit WebSocket JSON face info
        if json_face_info:
            tex_name = json_face_info.get("tex")
            tint_idx = int(json_face_info.get("tint", -1))
            uv_rot = float(json_face_info.get("rot", json_face_info.get("flow_angle", 0.0)))
        # 2. Second priority: mc_baker BakedFace (handles custom resource pack models)
        elif baked_face:
            tex_name = getattr(baked_face, "texture", None)
            tint_idx = getattr(baked_face, "tint_index", -1)
            is_fluid = getattr(parsed, "name", "") in ("water", "lava") or "water" in getattr(parsed, "name", "")
            uv_rot = getattr(baked_face, "uv_rot", 0.0) if is_fluid else 0.0

        loc = None

        # Try direct lookup of candidate from JSON or mc_baker
        if tex_name:
            loc = self.lookup_texture(tex_name)

        # 3. Third priority: Pre-baked BlockStates table in mapping
        if loc is None and self._block_states:
            state_key = getattr(parsed, "full_state", getattr(parsed, "name", ""))
            state_entry = self._block_states.get(state_key)
            if state_entry and "faces" in state_entry:
                # Map face_name or face_index to Minecraft 6-face convention (+X, -X, +Y, -Y, +Z, -Z)
                dir_to_order = {
                    "east": "+X", "west": "-X", "up": "+Y", "top": "+Y",
                    "down": "-Y", "bottom": "-Y", "south": "+Z", "north": "-Z"
                }
                face_key = dir_to_order.get(face_name.lower())
                if not face_key and 0 <= face_index < len(FACE_ORDER):
                    face_key = FACE_ORDER[face_index]
                if face_key and face_key in state_entry["faces"]:
                    f_data = state_entry["faces"][face_key]
                    if isinstance(f_data, dict):
                        loc = f_data
                        if "uv_rotation" in f_data and uv_rot == 0.0:
                            uv_rot = float(f_data["uv_rotation"])
                        if "tint_index" in f_data and tint_idx < 0:
                            tint_idx = int(f_data["tint_index"])

        # 4. Fallback candidate keys from parsed block
        if loc is None:
            cands = []
            short_name = getattr(parsed, "name", "").split(":", 1)[-1].removeprefix("block/")
            if short_name in BLOCK_TO_TEXTURE_ALIASES:
                cands.extend(BLOCK_TO_TEXTURE_ALIASES[short_name])
            if short_name in ANIMATED_BLOCK_ALIASES:
                cands.extend(ANIMATED_BLOCK_ALIASES[short_name])

            try:
                from ...live_sync.classifier import atlas_lookup_keys
                for k in atlas_lookup_keys(parsed):
                    cands.append(k)
            except Exception:
                pass

            cands.extend([
                getattr(parsed, "name", ""),
                getattr(parsed, "block_id", ""),
                f"minecraft:{short_name}",
                f"minecraft:block/{short_name}",
                short_name,
            ])
            loc = self.lookup_texture(cands)

        p_name = getattr(parsed, "name", "")

        # Fallback to procedural chunk 0 or chunk LUT if entirely missing
        chunk_id = int(loc.get("chunk_id", 0)) if loc else 0
        if not loc and block_face_chunk_lut:
            c_lut = block_face_chunk_lut.get(p_name) or block_face_chunk_lut.get(getattr(parsed, "full_state", ""))
            if c_lut and len(c_lut) > face_index:
                chunk_id = int(c_lut[face_index])

        texture_id = int(loc.get("texture_id", 0)) if loc else 0
        target_chunk = self.get_target_chunk(chunk_id, fallback_params=fallback_params)

        # UV projection closure
        calc_uv = self.get_calc_uv_fn(loc, target_chunk)

        # Animation timing calculation
        is_anim = bool(loc and (loc.get("kind") == "animation" or target_chunk.get("kind") == "animation"))
        if is_anim and loc:
            total_frames = float(loc.get("frame_count", 1))
            frametime = float(loc.get("frametime", 2))
            interpolate = 1.0 if loc.get("interpolate") else 0.0
            anim_timing = (total_frames, frametime, interpolate, 1.0)
            fw = float(loc.get("frame_width") or target_chunk.get("tile_size", 16))
            fh = float(loc.get("frame_height") or target_chunk.get("tile_size", 16))
            anim_frame_size = (fw, fh, 0.0, 0.0)
        else:
            anim_timing = (1.0, 1.0, 0.0, 1.0)
            ts = float(target_chunk.get("tile_size", 16))
            anim_frame_size = (ts, ts, 0.0, 0.0)

        # Biome Tint calculation
        p_short = p_name.split(":", 1)[-1].removeprefix("block/")
        is_hardcoded = bool((loc and loc.get("is_hardcoded")) or (p_short in HARDCODED_TINTS))

        use_tint = False
        if (
            tint_idx >= 0
            or (loc and loc.get("default_tint_weight", 0.0) > 0)
            or is_hardcoded
            or any(w in p_short for w in ("grass", "leaves", "water", "foliage", "vine"))
        ):
            use_tint = True
        elif block_face_tint_lut:
            t_lut = block_face_tint_lut.get(p_name) or block_face_tint_lut.get(getattr(parsed, "full_state", ""))
            if t_lut and len(t_lut) > face_index and t_lut[face_index][2] > 0:
                use_tint = True

        base_weight = float(loc.get("default_base_tint_weight", 1.0)) if loc else 1.0
        overlay_weight = float(loc.get("default_overlay_tint_weight", 1.0)) if loc else 1.0
        tint_weight = 1.0 if use_tint else 0.0
        hardcoded_weight = 1.0 if is_hardcoded else 0.0
        biome_tint_data = (base_weight, overlay_weight, tint_weight, hardcoded_weight)

        if is_hardcoded and loc and loc.get("hardcoded_color"):
            biome_tint_color = tuple(loc["hardcoded_color"])
        elif is_hardcoded and p_short in HARDCODED_TINTS:
            biome_tint_color = HARDCODED_TINTS[p_short]
        elif use_tint and hasattr(parsed, "tint_color"):
            biome_tint_color = parsed.tint_color
        else:
            biome_tint_color = (1.0, 1.0, 1.0, 1.0)

        # Canonical source texture key for mesh face provenance
        source_key = ""
        if loc:
            source_key = loc.get("texture_key") or loc.get("name", "")
        if not source_key and tex_name:
            ns, name = split_texture_key(tex_name)
            source_key = canonical_texture_key(ns, name)
        if not source_key:
            source_key = f"minecraft:block/{p_short}"

        return ResolvedAtlasAddress(
            chunk_id=chunk_id,
            texture_id=texture_id,
            location=loc or {},
            calc_uv_fn=calc_uv,
            source_texture_key=source_key,
            is_animated=is_anim,
            anim_timing=anim_timing,
            anim_frame_size=anim_frame_size,
            biome_tint_data=biome_tint_data,
            biome_tint_color=biome_tint_color,
            uv_rot=uv_rot,
            uv_tiling_transform=(1.0, 1.0, 0.0, 0.0),
        )

    def resolve_baked_face(self, baked_face: Any) -> ResolvedAtlasAddress:
        """
        Bridge method for mc_baker BakedFace objects.
        Resolves arbitrary model face to modern Atlas Chunk, Texture ID, and UV projection.
        """
        tex_name = getattr(baked_face, "texture", "")
        loc = self.lookup_texture(tex_name) if tex_name else None
        chunk_id = int(loc.get("chunk_id", 0)) if loc else 0
        texture_id = int(loc.get("texture_id", 0)) if loc else 0
        target_chunk = self._chunks_by_id.get(chunk_id, {"chunk_id": chunk_id, "tile_size": 16, "width": 512, "height": 512})

        calc_uv = self.get_calc_uv_fn(loc, target_chunk)
        tint_idx = getattr(baked_face, "tint_index", -1)
        uv_rot = getattr(baked_face, "uv_rot", 0.0)

        source_key = loc.get("texture_key", tex_name) if loc else tex_name

        return ResolvedAtlasAddress(
            chunk_id=chunk_id,
            texture_id=texture_id,
            location=loc or {},
            calc_uv_fn=calc_uv,
            source_texture_key=source_key,
            is_animated=bool(loc and loc.get("kind") == "animation"),
            uv_rot=uv_rot,
        )


__all__ = [
    "AtlasAddressResolver",
    "ResolvedAtlasAddress",
    "ANIMATED_BLOCK_ALIASES",
    "ENTITY_BLOCK_ALIASES",
    "HARDCODED_TINTS",
]

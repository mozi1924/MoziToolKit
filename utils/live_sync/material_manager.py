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

from ..mc_baker import StateBaker, BakedModel, BakedFace
from .constants import (
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
from .classifier import (
    ParsedBlock,
    atlas_lookup_keys,
    BlockTypeEnum,
    AIR_BLOCKS,
    FLUID_BLOCKS,
    TRANSPARENT_BLOCKS,
)

logger = logging.getLogger("MoziToolKit.LiveSync.MaterialManager")


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
        self.chunk_to_slot: dict[int, int] = {}
        self._texture_map: dict[str, dict] = {}
        self._chunks_by_id: dict[int, dict] = {}
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
        self._texture_map.clear()
        self._chunks_by_id.clear()

        mapping = self.atlas_params.get("mapping")
        if not isinstance(mapping, dict):
            return

        for chunk in mapping.get("chunks", []):
            if isinstance(chunk, dict) and "chunk_id" in chunk:
                self._chunks_by_id[int(chunk["chunk_id"])] = chunk

        # 1. Index all static/general textures in mapping
        raw_textures = mapping.get("textures", {})
        if isinstance(raw_textures, dict):
            for name, location in raw_textures.items():
                if not isinstance(location, dict):
                    continue
                tex_key = location.get("texture_key", name)
                ns, tex_name = _split_texture_key(tex_key)
                canon = _canonical_texture_key(ns, tex_name)
                self._texture_map[canon] = location
                self._texture_map[tex_key] = location
                self._texture_map[name] = location

                leg_ns, leg_tex = _split_texture_key(name)
                self._texture_map.setdefault(_canonical_texture_key(leg_ns, leg_tex), location)

                # Short basename fallback (e.g. 'stone' -> 'block/stone')
                short_name = tex_name.rsplit("/", 1)[-1] if "/" in tex_name else tex_name
                self._texture_map.setdefault(short_name, location)
                self._texture_map.setdefault(f"minecraft:{short_name}", location)
                self._texture_map.setdefault(f"minecraft:block/{short_name}", location)

        # 2. Priority index: Animations in mapping (overwrites any static fallback for animated textures)
        animations = mapping.get("animations", [])
        if isinstance(animations, list):
            for anim in animations:
                if not isinstance(anim, dict):
                    continue
                cid = int(anim.get("chunk_id", 0))
                target_chunk = self._chunks_by_id.get(cid, {})
                anim_loc = {
                    "chunk_id": cid,
                    "texture_id": anim.get("texture_id", 0),
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
                }

                tex_key = anim.get("texture_key") or anim.get("name", "")
                ns, tex_name = _split_texture_key(tex_key)
                canon = _canonical_texture_key(ns, tex_name)

                self._texture_map[canon] = anim_loc
                self._texture_map[tex_key] = anim_loc
                if anim.get("name"):
                    self._texture_map[anim["name"]] = anim_loc

                short_name = tex_name.rsplit("/", 1)[-1] if "/" in tex_name else tex_name
                self._texture_map[short_name] = anim_loc
                self._texture_map[f"minecraft:{short_name}"] = anim_loc
                self._texture_map[f"minecraft:block/{short_name}"] = anim_loc

        # 3. Canonical animated block name aliases (e.g. water, lava, fire, portal, sea_lantern)
        animated_aliases = {
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
        for base_name, alt_list in animated_aliases.items():
            for alt in alt_list:
                if alt in self._texture_map and self._texture_map[alt].get("kind") == "animation":
                    self._texture_map.setdefault(base_name, self._texture_map[alt])
                    self._texture_map.setdefault(f"minecraft:{base_name}", self._texture_map[alt])
                    self._texture_map.setdefault(f"minecraft:block/{base_name}", self._texture_map[alt])
                    break

    def _ensure_chunk_materials_with_hash_validation(self) -> None:
        """
        Validates materials against the prebaked pack hash and loads only default block chunks.
        Non-block chunks (UI, items, entities) are lazily loaded on demand when needed.
        """
        from ..materials.atlas.builder import build_atlas_chunk_materials
        from ..materials.pack.pack_stack import get_configured_pack_stack
        from ..materials.pack.resource_pack import get_cache_dir

        pack_stack = None
        target_pack_hash = ""
        try:
            pack_stack = get_configured_pack_stack()
            target_pack_hash = getattr(pack_stack, "stack_hash", "") or getattr(pack_stack, "cache_key", "") or getattr(pack_stack, "pack_hash", "")
        except Exception:
            pack_stack = None

        atlas_dir: Optional[Path] = None
        cache_root = get_cache_dir()
        if target_pack_hash:
            for cand in (cache_root / target_pack_hash / "full_scene", cache_root / target_pack_hash):
                if cand.exists() and (cand / "atlas_mapping.json").exists():
                    atlas_dir = cand
                    break

            # If pack stack is configured but cache not yet compiled, auto-compile on the fly
            if not atlas_dir and pack_stack and pack_stack.packs:
                try:
                    from ..materials.atlas.generator import AtlasGenerator
                    target_dir = cache_root / target_pack_hash / "full_scene"
                    gen = AtlasGenerator(fallback_stack=pack_stack)
                    gen.build(target_dir)
                    if (target_dir / "atlas_mapping.json").exists():
                        atlas_dir = target_dir
                except Exception as e:
                    logger.warning(f"Failed to auto-generate atlas cache: {e}")

        self._atlas_dir = atlas_dir
        self._target_pack_hash = target_pack_hash

        # Determine mapping data
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

        # Filter default chunk IDs: only load pure block chunks (static and animated block strips)
        # Non-block categories (items, gui, particles, paintings, entities) are loaded on-demand.
        default_chunk_ids = [
            int(c.get("chunk_id", i)) for i, c in enumerate(chunks)
            if c.get("category", "blocks") == "blocks"
        ] if chunks else [0, 1]
        if not default_chunk_ids and chunks:
            default_chunk_ids = [int(chunks[0].get("chunk_id", 0))]

        self.chunk_materials.clear()

        # Check existing materials in bpy.data.materials matching chunk_id and target_pack_hash
        for mat in bpy.data.materials:
            cid = mat.get(PROP_ATLAS_CHUNK_ID, mat.get("mtk:atlas_chunk_id", None))
            if cid is not None and int(cid) in default_chunk_ids:
                mat_hash = mat.get(PROP_PACK_HASH, mat.get("mtk:pack_hash", mat.get("mtk_pack_hash", "")))
                if not target_pack_hash or mat_hash == target_pack_hash:
                    self.chunk_materials[int(cid)] = mat

        # Check if any required default chunk material is missing
        missing_chunks = [cid for cid in default_chunk_ids if cid not in self.chunk_materials]
        if missing_chunks and atlas_dir:
            try:
                rebuilt_mats = build_atlas_chunk_materials(
                    atlas_dir=atlas_dir,
                    pack_hash=target_pack_hash,
                    pack_textures=True,
                    uv_attribute=None,  # Use native Blender UVMap
                    chunk_ids=missing_chunks,
                )
                for r_cid, r_mat in rebuilt_mats.items():
                    self.chunk_materials[r_cid] = r_mat
            except Exception as e:
                logger.warning(f"Failed to build precompiled atlas chunk materials: {e}")

        # Collect or create fallback for missing default chunks
        for cid in default_chunk_ids:
            if cid not in self.chunk_materials:
                # Create standard principled shader fallback material
                mat_name = f"MC_Atlas_Chunk_{cid}"
                mat = bpy.data.materials.new(name=mat_name)
                mat.use_nodes = True
                nodes = mat.node_tree.nodes
                links = mat.node_tree.links
                nodes.clear()
                out_node = nodes.new("ShaderNodeOutputMaterial")
                out_node.location = (400, 0)
                bsdf = nodes.new("ShaderNodeBsdfPrincipled")
                bsdf.location = (0, 0)
                links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])
                mat[PROP_ATLAS_CHUNK_ID] = cid
                if target_pack_hash:
                    mat[PROP_PACK_HASH] = target_pack_hash
                self.chunk_materials[cid] = mat

        # Setup object material slots
        if self.world_obj:
            self._sync_object_material_slots()

    def ensure_chunk_loaded(self, chunk_id: int) -> int:
        """Dynamically load and bind a material chunk on demand if not already loaded in the scene."""
        if chunk_id in self.chunk_materials:
            return self.chunk_to_slot.get(chunk_id, 0)

        # 1. Try finding existing valid material in bpy.data.materials
        found_mat = None
        for mat in bpy.data.materials:
            cid = mat.get(PROP_ATLAS_CHUNK_ID, mat.get("mtk:atlas_chunk_id", None))
            if cid is not None and int(cid) == chunk_id:
                mat_hash = mat.get(PROP_PACK_HASH, mat.get("mtk:pack_hash", mat.get("mtk_pack_hash", "")))
                if not self._target_pack_hash or mat_hash == self._target_pack_hash:
                    found_mat = mat
                    break

        if found_mat:
            self.chunk_materials[chunk_id] = found_mat
        elif self._atlas_dir:
            try:
                from ..materials.atlas.builder import build_atlas_chunk_materials
                rebuilt_mats = build_atlas_chunk_materials(
                    atlas_dir=self._atlas_dir,
                    pack_hash=self._target_pack_hash,
                    pack_textures=True,
                    uv_attribute=None,
                    chunk_ids=[chunk_id],
                )
                for r_cid, r_mat in rebuilt_mats.items():
                    self.chunk_materials[r_cid] = r_mat
            except Exception as e:
                logger.warning(f"Failed to on-demand build chunk {chunk_id}: {e}")

        if chunk_id not in self.chunk_materials:
            mat_name = f"MC_Atlas_Chunk_{chunk_id}"
            mat = bpy.data.materials.new(name=mat_name)
            mat.use_nodes = True
            nodes = mat.node_tree.nodes
            links = mat.node_tree.links
            nodes.clear()
            out_node = nodes.new("ShaderNodeOutputMaterial")
            out_node.location = (400, 0)
            bsdf = nodes.new("ShaderNodeBsdfPrincipled")
            bsdf.location = (0, 0)
            links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])
            mat[PROP_ATLAS_CHUNK_ID] = chunk_id
            if self._target_pack_hash:
                mat[PROP_PACK_HASH] = self._target_pack_hash
            self.chunk_materials[chunk_id] = mat

        if self.world_obj:
            self._sync_object_material_slots()
        else:
            self._update_chunk_to_slot_map()

        return self.chunk_to_slot.get(chunk_id, 0)

    def _sync_object_material_slots(self) -> None:
        """Assign chunk materials directly into object material slots."""
        if not self.world_obj:
            return

        sorted_chunks = sorted(self.chunk_materials.items(), key=lambda item: item[0])
        max_chunk_id = max(self.chunk_materials.keys()) if self.chunk_materials else 0

        # Ensure object mesh has enough material slots
        while len(self.world_obj.data.materials) <= max_chunk_id:
            self.world_obj.data.materials.append(None)

        for cid, mat in sorted_chunks:
            if cid < len(self.world_obj.data.materials):
                self.world_obj.data.materials[cid] = mat

        self._update_chunk_to_slot_map()

    def _update_chunk_to_slot_map(self) -> None:
        """Map chunk IDs to actual material slot indices on world_obj."""
        self.chunk_to_slot.clear()
        if self.world_obj:
            for slot_idx, slot in enumerate(self.world_obj.material_slots):
                if not slot.material:
                    continue
                mat = slot.material
                cid = mat.get("mtk:atlas_chunk_id", mat.get("mtk_atlas_chunk_id", None))
                if cid is not None:
                    self.chunk_to_slot[int(cid)] = slot_idx
                else:
                    self.chunk_to_slot.setdefault(slot_idx, slot_idx)

        for cid in self.chunk_materials.keys():
            self.chunk_to_slot.setdefault(cid, cid)

        for cid in range(16):
            self.chunk_to_slot.setdefault(cid, cid)

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
        """
        tex_name: Optional[str] = None
        uv_rot: float = 0.0
        tint_idx: int = -1

        # 1. First priority: explicit JSON face payload from Live Sync WebSocket
        if json_face_info:
            tex_name = json_face_info.get("tex")
            tint_idx = int(json_face_info.get("tint", -1))
            if parsed.name in FLUID_BLOCKS or parsed.block_type == BlockTypeEnum.FLUID or "water" in parsed.name or "lava" in parsed.name:
                uv_rot = float(json_face_info.get("rot", json_face_info.get("flow_angle", 0.0)))
            else:
                uv_rot = 0.0
        # 2. Second priority: StateBaker baked face result
        elif baked_face:
            tex_name = baked_face.texture
            tint_idx = baked_face.tint_index
            # For solid / baked blocks, UV rotation is already baked directly into vertex/loop UVs.
            # Only fluids use shader-level UV rotation.
            if parsed.name in FLUID_BLOCKS or parsed.block_type == BlockTypeEnum.FLUID or "water" in parsed.name or "lava" in parsed.name:
                uv_rot = baked_face.uv_rot
            else:
                uv_rot = 0.0

        loc = None

        # Try texture_map lookup
        if tex_name:
            ns, name = _split_texture_key(tex_name)
            canon = _canonical_texture_key(ns, name)
            loc = (
                self._texture_map.get(canon)
                or self._texture_map.get(tex_name)
                or self._texture_map.get(name)
                or self._texture_map.get(name.rsplit("/", 1)[-1])
            )

        # Check if parsed block matches an animated block with animation candidate keys
        if loc is None or loc.get("kind") != "animation":
            short_name = parsed.name.split(":", 1)[-1].removeprefix("block/")
            try:
                from ..materials.constants import BLOCK_TO_TEXTURE_ALIASES
                if short_name in BLOCK_TO_TEXTURE_ALIASES:
                    for alt in BLOCK_TO_TEXTURE_ALIASES[short_name]:
                        for cand in (alt, f"minecraft:{alt}", f"minecraft:block/{alt}"):
                            if cand in self._texture_map and self._texture_map[cand].get("kind") == "animation":
                                loc = self._texture_map[cand]
                                break
                        if loc and loc.get("kind") == "animation":
                            break
            except Exception:
                pass

        if loc is None:
            short_name = parsed.name.split(":", 1)[-1].removeprefix("block/")
            candidate_keys = []
            try:
                for k in atlas_lookup_keys(parsed):
                    candidate_keys.append(k)
                    candidate_keys.append(f"minecraft:{k}")
                    candidate_keys.append(f"minecraft:block/{k}")
            except Exception:
                pass

            candidate_keys.extend([
                parsed.name,
                parsed.block_id,
                f"minecraft:{short_name}",
                f"minecraft:block/{short_name}",
                short_name,
            ])
            try:
                from ..materials.constants import BLOCK_TO_TEXTURE_ALIASES
                if short_name in BLOCK_TO_TEXTURE_ALIASES:
                    for alt in BLOCK_TO_TEXTURE_ALIASES[short_name]:
                        candidate_keys.extend((alt, f"minecraft:{alt}", f"minecraft:block/{alt}"))
            except Exception:
                pass

            for k in candidate_keys:
                if k in self._texture_map:
                    loc = self._texture_map[k]
                    break

        chunk_id = int(loc.get("chunk_id", 0)) if loc else 0
        if not loc and self.atlas_params.get("block_face_chunk_lut"):
            c_lut = self.atlas_params["block_face_chunk_lut"].get(parsed.name) or self.atlas_params["block_face_chunk_lut"].get(parsed.full_state)
            if c_lut and len(c_lut) > face_index:
                chunk_id = int(c_lut[face_index])

        target_chunk = self._chunks_by_id.get(chunk_id)
        if not target_chunk:
            # Fallback chunk metadata with atlas_params
            target_chunk = {
                "chunk_id": chunk_id,
                "width": float(self.atlas_params.get("width", DEFAULT_ATLAS_WIDTH)),
                "height": float(self.atlas_params.get("height", DEFAULT_ATLAS_HEIGHT)),
                "tile_size": float(self.atlas_params.get("tile_size", DEFAULT_TILE_SIZE)),
                "tiles_per_row": int(self.atlas_params.get("tiles_per_row", DEFAULT_TILES_PER_ROW)),
            }

        # Accurate UV Projection Closure supporting HD Packs and arbitrary Chunk dimensions
        captured_loc = loc
        captured_chunk = target_chunk

        def calc_uv(u: float, v: float) -> tuple[float, float]:
            return _remap_local_to_target_uv(
                u, v,
                target_location=captured_loc,
                target_chunk=captured_chunk,
            )

        # 1. Animation attributes calculation
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

        # 2. UV Tiling Transform
        uv_tiling_transform = (1.0, 1.0, 0.0, 0.0)

        # 3. Biome Tint calculation
        from .classifier import BIOME_TINT_GRASS, BIOME_TINT_FOLIAGE, BIOME_TINT_WATER, HARDCODED_TINTS
        is_hardcoded = bool((loc and loc.get("is_hardcoded")) or (parsed.name in HARDCODED_TINTS))
        if (
            tint_idx >= 0
            or (loc and loc.get("default_tint_weight", 0.0) > 0)
            or (parsed.name in BIOME_TINT_GRASS or parsed.name in BIOME_TINT_FOLIAGE or parsed.name in BIOME_TINT_WATER or "water" in parsed.name)
            or is_hardcoded
        ):
            use_tint = True
        elif self.atlas_params.get("block_face_tint_lut"):
            t_lut = self.atlas_params["block_face_tint_lut"].get(parsed.name) or self.atlas_params["block_face_tint_lut"].get(parsed.full_state)
            use_tint = bool(t_lut and len(t_lut) > face_index and t_lut[face_index][2] > 0)
        else:
            use_tint = False

        base_weight = float(loc.get("default_base_tint_weight", 1.0)) if loc else 1.0
        overlay_weight = float(loc.get("default_overlay_tint_weight", 1.0)) if loc else 1.0
        tint_weight = 1.0 if use_tint else 0.0
        hardcoded_weight = 1.0 if is_hardcoded else 0.0
        biome_tint_data = (base_weight, overlay_weight, tint_weight, hardcoded_weight)

        if is_hardcoded and loc and loc.get("hardcoded_color"):
            biome_tint_color = tuple(loc["hardcoded_color"])
        elif parsed.name in HARDCODED_TINTS:
            biome_tint_color = HARDCODED_TINTS[parsed.name]
        elif use_tint:
            biome_tint_color = parsed.tint_color
        else:
            biome_tint_color = (1.0, 1.0, 1.0, 1.0)

        slot_index = self.get_slot_for_chunk(chunk_id)

        return ResolvedFaceTexture(
            chunk_id=chunk_id,
            slot_index=slot_index,
            uv_rot=uv_rot,
            use_tint=use_tint,
            tint_color=biome_tint_color,
            calc_uv_fn=calc_uv,
            anim_timing=anim_timing,
            anim_frame_size=anim_frame_size,
            uv_tiling_transform=uv_tiling_transform,
            biome_tint_data=biome_tint_data,
            biome_tint_color=biome_tint_color,
        )

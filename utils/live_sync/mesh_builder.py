"""
Direct Mesh Builder for MoziToolKit Live Sync.
Constructs native Blender Polygon Meshes directly from VoxelStorage.
Features:
- Sub-millisecond neighbor-aware 6-face culling (Opaque & Translucent).
- 100% Canonical UV face assembly & rotation for directional blocks via StateBaker.
- Incremental 16x16x16 section-based chunk mesh synchronization.
- Native loop UV mapping directly into Atlas Chunks (no Geometry Nodes attributes).
- Direct Face Material Indexing corresponding to pre-baked Atlas Material slots.
- Native Color Attributes for Biome and State Tinting.
- Support for complex multipart/non-cube models (Stairs, Slabs, Fences, Doors, etc.).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, Set
import bpy
import bmesh
from mathutils import Vector

from .storage import VoxelStorage
from .classifier import (
    parse_and_classify,
    BlockTypeEnum,
    ParsedBlock,
    AIR_BLOCKS,
    TRANSPARENT_BLOCKS,
    FLUID_BLOCKS,
)
from .constants import (
    DEFAULT_WORLD_OBJECT_NAME,
    DEFAULT_WORLD_MESH_NAME,
    DEFAULT_ATLAS_WIDTH,
    DEFAULT_ATLAS_HEIGHT,
    DEFAULT_TILE_SIZE,
    DEFAULT_TILES_PER_ROW,
    DEFAULT_ANIM_ATLAS_WIDTH,
    DEFAULT_ANIM_ATLAS_HEIGHT,
    DEFAULT_ANIM_FRAME_WIDTH,
    DEFAULT_ANIM_FRAME_HEIGHT,
    DIR_TO_INDEX,
    MC_DIR_OFFSETS,
    FACES,
    MTK_BLOCK_X,
    MTK_BLOCK_Y,
    MTK_BLOCK_Z,
    MTK_FACE_DIR,
    MTK_UV_ROTATION,
    MTK_ANIM_TIMING,
    MTK_ANIM_FRAME_SIZE,
    MTK_UV_TILING_TRANSFORM,
    MTK_BIOME_TINT_DATA,
    MTK_BIOME_TINT_COLOR,
    MTK_ATLAS_CHUNK_ID,
    MTK_SOURCE_TEXTURE_KEY,
    UV_MAP,
)
from ..mc_baker import (
    StateBaker,
    BakedModel,
    BakedFace,
    get_shared_state_baker,
    refresh_shared_baker_sources,
)
from .material_manager import LiveSyncMaterialManager, ResolvedFaceTexture
from .fluid_mesher import generate_fluid_mesh_faces, is_fluid_block
from ..culling import (
    get_shared_face_culler,
    BlockCullMeta,
    FaceCuller,
)

logger = logging.getLogger("MoziToolKit.MeshBuilder")


# Standard Unit Cube Quads in Minecraft local coordinates [0..1]
CUBE_FACE_MC_VERTICES: dict[str, tuple[tuple[float, float, float], ...]] = {
    "east": ((1.0, 1.0, 1.0), (1.0, 0.0, 1.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)),
    "west": ((0.0, 1.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 1.0)),
    "up": ((0.0, 1.0, 0.0), (0.0, 1.0, 1.0), (1.0, 1.0, 1.0), (1.0, 1.0, 0.0)),
    "top": ((0.0, 1.0, 0.0), (0.0, 1.0, 1.0), (1.0, 1.0, 1.0), (1.0, 1.0, 0.0)),
    "down": ((0.0, 0.0, 1.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0)),
    "bottom": ((0.0, 0.0, 1.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0)),
    "south": ((0.0, 1.0, 1.0), (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0)),
    "north": ((1.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
}

# Standard Default Face UVs in Minecraft texture space [0..1] (v=0 is top, v=1 is bottom)
CUBE_FACE_CANONICAL_UVS: dict[str, tuple[tuple[float, float], ...]] = {
    "east": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
    "west": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
    "up": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
    "top": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
    "down": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
    "bottom": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
    "south": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
    "north": ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
}


def _mc_local_to_blender(lx: float, ly: float, lz: float) -> tuple[float, float, float]:
    """Convert Minecraft local offset [0..1] relative to block center to Blender space."""
    return (
        lx - 0.5,
        -(lz - 0.5),  # MC North (-Z) is Blender +Y, MC South (+Z) is Blender -Y
        ly - 0.5,     # MC Up (+Y) is Blender +Z
    )


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
            # Cube classification follows the actual baked geometry: a block whose
            # model occupies the full 1x1x1 cell is treated as a cube even when the
            # classifier labels it multipart (e.g. stairs/slabs in simplified packs
            # where they bake as full cubes), so neighbors correctly cull touching
            # faces. Conversely a CUBE-labeled block with partial geometry (e.g.
            # farmland, cactus) is not treated as a cube, preserving visible faces.
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
_GLOBAL_MAT_MANAGER: Optional[LiveSyncMaterialManager] = None
_GLOBAL_MAT_MANAGER_SIG: Optional[tuple] = None


def get_shared_material_manager(
    world_obj: Optional[bpy.types.Object],
    atlas_params: Optional[dict[str, Any]],
) -> LiveSyncMaterialManager:
    """Retrieve or reuse shared LiveSyncMaterialManager instance to avoid re-indexing."""
    global _GLOBAL_MAT_MANAGER, _GLOBAL_MAT_MANAGER_SIG
    obj_ptr = world_obj.as_pointer() if world_obj and hasattr(world_obj, "as_pointer") else id(world_obj)
    mapping_obj = atlas_params.get("mapping") if atlas_params else None
    mapping_id = id(mapping_obj) if mapping_obj else 0
    pack_hash = atlas_params.get("pack_hash", "") if atlas_params else ""
    current_sig = (obj_ptr, mapping_id, pack_hash)

    is_valid = True
    if _GLOBAL_MAT_MANAGER is not None:
        for mat in _GLOBAL_MAT_MANAGER.chunk_materials.values():
            try:
                _ = mat.name
            except (ReferenceError, Exception):
                is_valid = False
                break

    if not is_valid or _GLOBAL_MAT_MANAGER is None or _GLOBAL_MAT_MANAGER_SIG != current_sig:
        _GLOBAL_MAT_MANAGER_SIG = current_sig
        _GLOBAL_MAT_MANAGER = LiveSyncMaterialManager(world_obj=world_obj, atlas_params=atlas_params)

    return _GLOBAL_MAT_MANAGER


def _sync_section_material_slots(
    section_obj: bpy.types.Object,
    mat_manager: LiveSyncMaterialManager,
) -> bool:
    """Mirror the manager's compact slot layout onto one Direct-Mesh section.

    ``ResolvedFaceTexture.slot_index`` is a Blender material-slot index, not
    an atlas ``chunk_id``.  Chunk IDs may be sparse (for example, a banner
    chunk can be 7), so assigning a material to ``materials[chunk_id]`` both
    creates empty slots and makes faces point at unrelated block materials.
    Returns True if material slots were changed, False otherwise.
    """
    return mat_manager.sync_material_slots(section_obj)


def _rebind_mesh_material_indices(
    mesh: bpy.types.Mesh,
    mat_manager: LiveSyncMaterialManager,
) -> None:
    """Repair/render-bind faces from their persistent chunk identity.

    Older live-sync meshes do not have the chunk attribute, so their
    ``mtk_source_texture_key`` is used once to migrate them.  The material
    index itself is never used as an atlas identifier.
    """
    chunk_attr = mesh.attributes.get(MTK_ATLAS_CHUNK_ID)
    created_chunk_attr = chunk_attr is None
    if not chunk_attr:
        chunk_attr = mesh.attributes.new(MTK_ATLAS_CHUNK_ID, "INT", "FACE")
    source_attr = mesh.attributes.get(MTK_SOURCE_TEXTURE_KEY)

    for poly in mesh.polygons:
        chunk_id = int(chunk_attr.data[poly.index].value)
        if (created_chunk_attr or chunk_id not in mat_manager.chunk_materials) and source_attr:
            raw_key = source_attr.data[poly.index].value
            source_key = raw_key.decode("utf-8", "replace") if isinstance(raw_key, bytes) else str(raw_key or "")
            location = mat_manager.resolver.lookup_texture(source_key) if source_key else None
            if location:
                chunk_id = int(location.get("chunk_id", 0))
                chunk_attr.data[poly.index].value = chunk_id
        if chunk_id in mat_manager.chunk_materials:
            poly.material_index = mat_manager.get_slot_for_chunk(chunk_id)


def get_cached_state_meta(
    state_str: str,
    mat_manager: LiveSyncMaterialManager,
    baker: StateBaker,
) -> CachedStateMeta:
    """Retrieve or compute CachedStateMeta using the global cache."""
    meta = _GLOBAL_STATE_META_CACHE.get(state_str)
    if meta is None:
        meta = CachedStateMeta(state_str, mat_manager, baker)
        _GLOBAL_STATE_META_CACHE[state_str] = meta
    return meta


from .hot_states import HOT_PREWARM_STATES

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

_idle_prewarm_timer_registered: bool = False
_idle_prewarm_pending: list[str] = []


def _idle_prewarm_tick() -> Optional[float]:
    """Background idle timer that warms remaining cold blockstates rapidly during idle frames."""
    global _idle_prewarm_timer_registered, _idle_prewarm_pending
    if not _idle_prewarm_timer_registered or not _idle_prewarm_pending:
        _idle_prewarm_timer_registered = False
        return None

    if _GLOBAL_MAT_MANAGER is None:
        _idle_prewarm_timer_registered = False
        return None

    baker = get_shared_state_baker()
    batch_size = 50
    batch = _idle_prewarm_pending[:batch_size]
    _idle_prewarm_pending = _idle_prewarm_pending[batch_size:]

    for state_str in batch:
        if state_str not in _GLOBAL_STATE_META_CACHE:
            try:
                meta = CachedStateMeta(state_str, _GLOBAL_MAT_MANAGER, baker)
                _GLOBAL_STATE_META_CACHE[state_str] = meta
            except Exception:
                pass

    if _idle_prewarm_pending:
        return 0.02  # Schedule next batch in 20ms
    else:
        _idle_prewarm_timer_registered = False
        logger.info(f"Live Sync: Completed full background pre-warming ({len(_GLOBAL_STATE_META_CACHE)} total states).")
        return None


def preload_sync_world_data(
    palette: Optional[list[str]] = None,
    world_obj: Optional[bpy.types.Object] = None,
    atlas_params: Optional[dict[str, Any]] = None,
) -> int:
    """
    Pre-load and pre-warm all blockstate models, elements, face textures,
    atlas UV mappings, and materials into RAM upon initial world synchronization.
    Eliminates cold-start calculation overhead on subsequent live sync updates.
    """
    global _idle_prewarm_timer_registered, _idle_prewarm_pending
    refresh_shared_baker_sources()
    baker = get_shared_state_baker()
    mat_manager = get_shared_material_manager(world_obj=world_obj, atlas_params=atlas_params)

    # L1: High-Priority Hot BlockStates (Doors, Stairs, Slabs, Torches, Beds, Redstone, Crops, Workstations)
    states_to_warm = set(COMMON_PREWARM_STATES)
    states_to_warm.update(HOT_PREWARM_STATES)

    # L2: Snapshot Palette from current selection
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
                logger.debug(f"Prewarm skipped for '{state_str}': {e}")

    logger.info(f"Live Sync: L1 Pre-warmed {len(_GLOBAL_STATE_META_CACHE)} hot blockstates in memory ({warmed_count} newly loaded).")

    # L3: Queue remaining cold models from baked pack cache for smooth background idle warming
    if baker and baker._bake_cache:
        remaining = [s for s in baker._bake_cache.keys() if s not in _GLOBAL_STATE_META_CACHE]
        if remaining:
            _idle_prewarm_pending = remaining
            if not _idle_prewarm_timer_registered and hasattr(bpy, "app") and hasattr(bpy.app, "timers"):
                try:
                    _idle_prewarm_timer_registered = True
                    bpy.app.timers.register(_idle_prewarm_tick, first_interval=0.01)
                except Exception:
                    _idle_prewarm_timer_registered = False

    return len(_GLOBAL_STATE_META_CACHE)


def clear_mesh_builder_caches() -> None:
    """Clear all global state metadata and material manager caches."""
    global _GLOBAL_MAT_MANAGER, _GLOBAL_MAT_MANAGER_SIG
    _GLOBAL_STATE_META_CACHE.clear()
    _GLOBAL_MAT_MANAGER = None
    _GLOBAL_MAT_MANAGER_SIG = None


class WorldMeshBuildResult(NamedTuple):
    world_obj: Optional[bpy.types.Object]
    vertex_count: int
    face_count: int
    cubes_count: int
    props_count: int
    fluids_count: int


def _get_or_create_bmesh_layers(bm: bmesh.types.BMesh) -> dict[str, Any]:
    """Ensure all required BMesh loop and face attribute layers exist."""
    return {
        "uv": bm.loops.layers.uv.get(UV_MAP) or bm.loops.layers.uv.new(UV_MAP),
        "color": bm.loops.layers.color.get("Color") or bm.loops.layers.color.new("Color"),
        "rot": bm.faces.layers.float.get(MTK_UV_ROTATION) or bm.faces.layers.float.new(MTK_UV_ROTATION),
        "timing": bm.faces.layers.float_color.get(MTK_ANIM_TIMING) or bm.faces.layers.float_color.new(MTK_ANIM_TIMING),
        "frame_size": bm.faces.layers.float_color.get(MTK_ANIM_FRAME_SIZE) or bm.faces.layers.float_color.new(MTK_ANIM_FRAME_SIZE),
        "tiling": bm.faces.layers.float_color.get(MTK_UV_TILING_TRANSFORM) or bm.faces.layers.float_color.new(MTK_UV_TILING_TRANSFORM),
        "tint_data": bm.faces.layers.float_color.get(MTK_BIOME_TINT_DATA) or bm.faces.layers.float_color.new(MTK_BIOME_TINT_DATA),
        "tint_color": bm.faces.layers.float_color.get(MTK_BIOME_TINT_COLOR) or bm.faces.layers.float_color.new(MTK_BIOME_TINT_COLOR),
        "block_x": bm.faces.layers.int.get(MTK_BLOCK_X) or bm.faces.layers.int.new(MTK_BLOCK_X),
        "block_y": bm.faces.layers.int.get(MTK_BLOCK_Y) or bm.faces.layers.int.new(MTK_BLOCK_Y),
        "block_z": bm.faces.layers.int.get(MTK_BLOCK_Z) or bm.faces.layers.int.new(MTK_BLOCK_Z),
        "face_dir": bm.faces.layers.int.get(MTK_FACE_DIR) or bm.faces.layers.int.new(MTK_FACE_DIR),
        "atlas_chunk": bm.faces.layers.int.get(MTK_ATLAS_CHUNK_ID) or bm.faces.layers.int.new(MTK_ATLAS_CHUNK_ID),
        "source_key": bm.faces.layers.string.get(MTK_SOURCE_TEXTURE_KEY) or bm.faces.layers.string.new(MTK_SOURCE_TEXTURE_KEY),
    }


def _emit_bmesh_face(
    bm: bmesh.types.BMesh,
    verts_coords: Sequence[tuple[float, float, float]],
    f_res: ResolvedFaceTexture,
    layers: dict[str, Any],
    block_pos: tuple[int, int, int],
    face_dir_idx: int,
    loop_uvs_mc: Sequence[tuple[float, float]],
    uv_rot: float = 0.0,
    use_tint: bool = False,
    model_uv_scale: tuple[float, float] = (1.0, 1.0),
) -> bool:
    """Helper to emit a single polygon face into BMesh with all shader attributes and UVs."""
    face_bm_verts = [bm.verts.new(v) for v in verts_coords]
    try:
        bm_face = bm.faces.new(face_bm_verts)
    except ValueError:
        return False

    bm_face.material_index = f_res.slot_index
    bm_face[layers["atlas_chunk"]] = f_res.chunk_id
    bm_face[layers["rot"]] = uv_rot
    bm_face[layers["timing"]] = f_res.anim_timing
    bm_face[layers["frame_size"]] = f_res.anim_frame_size
    bm_face[layers["tiling"]] = f_res.uv_tiling_transform
    bm_face[layers["tint_data"]] = f_res.biome_tint_data
    bm_face[layers["tint_color"]] = f_res.biome_tint_color
    bm_face[layers["block_x"]] = block_pos[0]
    bm_face[layers["block_y"]] = block_pos[1]
    bm_face[layers["block_z"]] = block_pos[2]
    bm_face[layers["face_dir"]] = face_dir_idx
    if layers.get("source_key") and f_res.source_texture_key:
        bm_face[layers["source_key"]] = f_res.source_texture_key.encode("utf-8")

    uv_layer = layers["uv"]
    color_layer = layers["color"]
    sx, sy = model_uv_scale

    for loop_idx, loop in enumerate(bm_face.loops):
        if loop_idx < len(loop_uvs_mc):
            u_mc, v_mc = loop_uvs_mc[loop_idx]
        else:
            u_mc, v_mc = (0.0, 0.0)
        u_scaled = float(u_mc) * sx
        v_scaled = float(v_mc) * sy
        loop[uv_layer].uv = Vector(f_res.calc_uv_fn(u_scaled, 1.0 - v_scaled))
        loop[color_layer] = f_res.biome_tint_color if use_tint else (1.0, 1.0, 1.0, 1.0)

    return True


def _generate_single_block_faces(
    bm: bmesh.types.BMesh,
    x: int, y: int, z: int,
    state_str: str,
    block_map: dict[tuple[int, int, int], str],
    state_cache: dict[str, CachedStateMeta],
    layers: dict[str, Any],
    origin_centered: bool,
    min_x: int, min_y: int, min_z: int,
    half_x: float, half_z: float,
    mat_manager: Optional[LiveSyncMaterialManager] = None,
    baker: Optional[StateBaker] = None,
) -> tuple[int, int, int]:
    """
    Generates faces for a single block at (x, y, z) into BMesh with full 6-face neighbor culling.
    Returns (is_cube, is_prop, is_fluid).
    """
    meta = state_cache.get(state_str)
    if not meta and state_str:
        if state_str in _GLOBAL_STATE_META_CACHE:
            meta = _GLOBAL_STATE_META_CACHE[state_str]
        elif mat_manager is not None and baker is not None:
            meta = get_cached_state_meta(state_str, mat_manager, baker)
        if meta:
            state_cache[state_str] = meta

    if not meta or meta.is_air:
        return (0, 0, 0)

    if origin_centered:
        bx = (x - min_x) - half_x
        by = -((z - min_z) - half_z)
        bz = (y - min_y) + 0.5
    else:
        bx = float(x)
        by = -float(z)
        bz = float(y)

    def _get_neighbor_meta(pos: tuple[int, int, int]) -> Optional[CachedStateMeta]:
        n_state = block_map.get(pos)
        if not n_state:
            return None
        nm = state_cache.get(n_state)
        if not nm:
            if n_state in _GLOBAL_STATE_META_CACHE:
                nm = _GLOBAL_STATE_META_CACHE[n_state]
            elif mat_manager is not None and baker is not None:
                nm = get_cached_state_meta(n_state, mat_manager, baker)
            if nm:
                state_cache[n_state] = nm
        return nm

    is_cube_cnt = 0
    is_prop_cnt = 0
    is_fluid_cnt = 0

    face_culler = get_shared_face_culler()

    if meta.is_fluid:
        eff_mat_mgr = mat_manager or _GLOBAL_MAT_MANAGER or get_shared_material_manager(world_obj=None, atlas_params=None)
        fluid_faces = generate_fluid_mesh_faces(
            bm=bm,
            x=x, y=y, z=z,
            state_str=state_str,
            block_map=block_map,
            layers=layers,
            origin_centered=origin_centered,
            min_x=min_x, min_y=min_y, min_z=min_z,
            half_x=half_x, half_z=half_z,
            mat_manager=eff_mat_mgr,
        )
        is_fluid_cnt = 1 if fluid_faces > 0 else 0

    elif meta.baked_model and meta.baked_model.elements:
        if meta.is_cube:
            is_cube_cnt = 1
        else:
            is_prop_cnt = 1

        for elem in meta.baked_model.elements:
            for f_dir, bf in elem.faces.items():
                if not bf.vertices or len(bf.vertices) < 3:
                    continue

                cull_dir = bf.cullface or (f_dir if meta.is_cube else None)
                if cull_dir and cull_dir in MC_DIR_OFFSETS:
                    dx, dy, dz = MC_DIR_OFFSETS[cull_dir]
                    n_pos = (x + dx, y + dy, z + dz)
                    n_meta = _get_neighbor_meta(n_pos)
                    if not face_culler.should_render_face(
                        state_meta=meta.cull_meta,
                        neighbor_meta=n_meta.cull_meta if n_meta else None,
                        direction=cull_dir,
                        block_pos=(x, y, z),
                        neighbor_pos=n_pos,
                    ):
                        continue

                f_res = meta.get_face_res(bf, f_dir)
                bl_coords = [_mc_local_to_blender(lx, ly, lz) for lx, ly, lz in bf.vertices]
                world_coords = [(bx + vx, by + vy, bz + vz) for vx, vy, vz in bl_coords]

                _emit_bmesh_face(
                    bm=bm,
                    verts_coords=world_coords,
                    f_res=f_res,
                    layers=layers,
                    block_pos=(x, y, z),
                    face_dir_idx=DIR_TO_INDEX.get(f_dir, -1),
                    loop_uvs_mc=bf.uvs,
                    uv_rot=0.0,
                    use_tint=(bf.tint_index >= 0 or f_res.use_tint),
                    model_uv_scale=f_res.model_uv_scale,
                )

    else:
        is_cube_cnt = 1
        for f_name in ("east", "west", "up", "down", "south", "north"):
            dx, dy, dz = MC_DIR_OFFSETS[f_name]
            neighbor_pos = (x + dx, y + dy, z + dz)
            n_meta = _get_neighbor_meta(neighbor_pos)
            if not face_culler.should_render_face(
                state_meta=meta.cull_meta,
                neighbor_meta=n_meta.cull_meta if n_meta else None,
                direction=f_name,
                block_pos=(x, y, z),
                neighbor_pos=neighbor_pos,
            ):
                continue

            f_res = meta.faces_info.get(f_name, meta.faces_info.get("east"))
            mc_verts = CUBE_FACE_MC_VERTICES[f_name]
            canonical_uvs = CUBE_FACE_CANONICAL_UVS[f_name]
            bl_coords = [_mc_local_to_blender(lx, ly, lz) for lx, ly, lz in mc_verts]
            world_coords = [(bx + vx, by + vy, bz + vz) for vx, vy, vz in bl_coords]


            _emit_bmesh_face(
                bm=bm,
                verts_coords=world_coords,
                f_res=f_res,
                layers=layers,
                block_pos=(x, y, z),
                face_dir_idx=DIR_TO_INDEX.get(f_name, -1),
                loop_uvs_mc=canonical_uvs,
                uv_rot=0.0,
                use_tint=f_res.use_tint,
            )

    # If block is waterlogged (e.g. waterlogged stairs, slab, fence, chest, kelp, seagrass):
    if meta.parsed.is_waterlogged and not meta.is_fluid:
        eff_mat_mgr = mat_manager or _GLOBAL_MAT_MANAGER or get_shared_material_manager(world_obj=None, atlas_params=None)
        fluid_faces = generate_fluid_mesh_faces(
            bm=bm,
            x=x, y=y, z=z,
            state_str="minecraft:water[level=0]",
            block_map=block_map,
            layers=layers,
            origin_centered=origin_centered,
            min_x=min_x, min_y=min_y, min_z=min_z,
            half_x=half_x, half_z=half_z,
            mat_manager=eff_mat_mgr,
        )
        if fluid_faces > 0:
            is_fluid_cnt = 1

    return (is_cube_cnt, is_prop_cnt, is_fluid_cnt)


def _generate_voxel_geometry(
    bm: bmesh.types.BMesh,
    voxel_items: list[tuple[tuple[int, int, int], str]],
    block_map: dict[tuple[int, int, int], str],
    state_cache: dict[str, CachedStateMeta],
    uv_layer: Any = None,
    color_layer: Any = None,
    origin_centered: bool = True,
    min_x: int = 0, min_y: int = 0, min_z: int = 0,
    half_x: float = 0.0, half_z: float = 0.0,
    mat_manager: Optional[LiveSyncMaterialManager] = None,
    baker: Optional[StateBaker] = None,
) -> tuple[int, int, int]:
    """
    Constructs BMesh geometry for a collection of voxels with 6-face culling,
    exact MC Baker BakedFace vertex transformations, and native Atlas UV loop projection.
    Dynamically writes named face attributes for shaders and block convention.
    Returns (cubes_count, props_count, fluids_count).
    """
    layers = _get_or_create_bmesh_layers(bm)
    cubes_count = 0
    props_count = 0
    fluids_count = 0

    for (x, y, z), state_str in voxel_items:
        c, p, f = _generate_single_block_faces(
            bm=bm,
            x=x, y=y, z=z,
            state_str=state_str,
            block_map=block_map,
            state_cache=state_cache,
            layers=layers,
            origin_centered=origin_centered,
            min_x=min_x, min_y=min_y, min_z=min_z,
            half_x=half_x, half_z=half_z,
            mat_manager=mat_manager,
            baker=baker,
        )
        cubes_count += c
        props_count += p
        fluids_count += f

    return cubes_count, props_count, fluids_count


def update_blocks_in_mesh(
    mesh: bpy.types.Mesh,
    blocks_to_update: set[tuple[int, int, int]],
    storage: VoxelStorage,
    state_cache: dict[str, CachedStateMeta],
    origin_centered: bool = True,
    min_x: int = 0, min_y: int = 0, min_z: int = 0,
    half_x: float = 0.0, half_z: float = 0.0,
    mat_manager: Optional[LiveSyncMaterialManager] = None,
    baker: Optional[StateBaker] = None,
) -> None:
    """
    Incrementally edits target blocks within an existing Mesh via BMesh.
    Deletes old faces of affected blocks, cleans up orphan vertices,
    and inserts newly visible faces without regenerating the rest of the mesh.
    """
    bm = bmesh.new()
    bm.from_mesh(mesh)
    layers = _get_or_create_bmesh_layers(bm)

    block_x_layer = layers["block_x"]
    block_y_layer = layers["block_y"]
    block_z_layer = layers["block_z"]

    # 1. Delete all existing faces belonging to any block in blocks_to_update
    faces_to_delete = [
        f for f in bm.faces
        if (f[block_x_layer], f[block_y_layer], f[block_z_layer]) in blocks_to_update
    ]
    if faces_to_delete:
        bmesh.ops.delete(bm, geom=faces_to_delete, context='FACES')
        orphan_verts = [v for v in bm.verts if not v.link_faces]
        if orphan_verts:
            bmesh.ops.delete(bm, geom=orphan_verts, context='VERTS')

    # 2. Generate visible faces for non-air blocks in blocks_to_update
    for (x, y, z) in blocks_to_update:
        state_str = storage.get_block(x, y, z)
        if state_str:
            _generate_single_block_faces(
                bm=bm,
                x=x, y=y, z=z,
                state_str=state_str,
                block_map=storage.block_map,
                state_cache=state_cache,
                layers=layers,
                origin_centered=origin_centered,
                min_x=min_x, min_y=min_y, min_z=min_z,
                half_x=half_x, half_z=half_z,
                mat_manager=mat_manager,
                baker=baker,
            )

    # 3. Clean up any leftover orphan vertices
    orphan_verts = [v for v in bm.verts if not v.link_faces]
    if orphan_verts:
        bmesh.ops.delete(bm, geom=orphan_verts, context='VERTS')

    mesh.clear_geometry()
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


def build_world_mesh(
    context: bpy.types.Context,
    storage: VoxelStorage,
    atlas_params: Optional[dict[str, Any]] = None,
    filter_air: bool = True,
    origin_centered: bool = True,
    weld_vertices: bool = True,
) -> WorldMeshBuildResult:
    """
    Constructs the full native Blender polygon mesh directly on the world object.
    Maintains 100% backward compatibility for single-mesh queries and unit tests.
    """
    if storage.size_x == 0 or storage.size_y == 0 or storage.size_z == 0:
        return WorldMeshBuildResult(None, 0, 0, 0, 0, 0)

    block_map = storage.block_map
    if not block_map:
        return WorldMeshBuildResult(None, 0, 0, 0, 0, 0)

    refresh_shared_baker_sources()
    baker = get_shared_state_baker()

    # 1. Coordinate transformation parameters
    min_x, min_y, min_z = storage.min_x, storage.min_y, storage.min_z
    size_x, size_y, size_z = storage.size_x, storage.size_y, storage.size_z
    half_x = size_x / 2.0 - 0.5
    half_z = size_z / 2.0 - 0.5

    # 2. Target Mesh Object
    obj_name = DEFAULT_WORLD_OBJECT_NAME
    mesh_name = DEFAULT_WORLD_MESH_NAME

    if obj_name in bpy.data.objects:
        obj = bpy.data.objects[obj_name]
        mesh = obj.data
    else:
        mesh = bpy.data.meshes.new(mesh_name)
        obj = bpy.data.objects.new(obj_name, mesh)
        obj.location = (0.0, 0.0, 0.0)
        context.collection.objects.link(obj)

    # 3. Material Manager
    mat_manager = LiveSyncMaterialManager(world_obj=obj, atlas_params=atlas_params)

    # 4. Precompute unique block states
    unique_states = set(block_map.values())
    state_cache: dict[str, CachedStateMeta] = {
        s: get_cached_state_meta(s, mat_manager, baker) for s in unique_states
    }

    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    color_layer = bm.loops.layers.color.new("Color")

    cubes_count, props_count, fluids_count = _generate_voxel_geometry(
        bm=bm,
        voxel_items=list(block_map.items()),
        block_map=block_map,
        state_cache=state_cache,
        uv_layer=uv_layer,
        color_layer=color_layer,
        origin_centered=origin_centered,
        min_x=min_x, min_y=min_y, min_z=min_z,
        half_x=half_x, half_z=half_z,
        mat_manager=mat_manager,
        baker=baker,
    )

    # 5. Optional in-engine vertex welding for optimal topology
    if weld_vertices and len(bm.verts) > 0:
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)

    # 6. Push BMesh data back to Blender Mesh
    mesh.clear_geometry()
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    vertex_count = len(mesh.vertices)
    face_count = len(mesh.polygons)

    return WorldMeshBuildResult(
        world_obj=obj,
        vertex_count=vertex_count,
        face_count=face_count,
        cubes_count=cubes_count,
        props_count=props_count,
        fluids_count=fluids_count,
    )


def sync_world_mesh(
    context: bpy.types.Context,
    storage: VoxelStorage,
    atlas_params: Optional[dict[str, Any]] = None,
    force_full_rebuild: bool = False,
    origin_centered: bool = True,
    weld_vertices: bool = True,
) -> WorldMeshBuildResult:
    """
    High-performance incremental section-based World Mesh synchronizer.
    Maintains 16x16x16 child section objects (Yefira_Section_<x>_<y>_<z>) under Yefira_World.
    Only regenerates dirty sections and boundary neighbors, delivering sub-millisecond real-time sync.
    """
    if storage.size_x == 0 or storage.size_y == 0 or storage.size_z == 0:
        return WorldMeshBuildResult(None, 0, 0, 0, 0, 0)

    block_map = storage.block_map
    if not block_map:
        return WorldMeshBuildResult(None, 0, 0, 0, 0, 0)

    refresh_shared_baker_sources()
    baker = get_shared_state_baker()

    min_x, min_y, min_z = storage.min_x, storage.min_y, storage.min_z
    size_x, size_y, size_z = storage.size_x, storage.size_y, storage.size_z
    half_x = size_x / 2.0 - 0.5
    half_z = size_z / 2.0 - 0.5

    # 1. Acquire root container object
    root_name = DEFAULT_WORLD_OBJECT_NAME
    if root_name in bpy.data.objects:
        root_obj = bpy.data.objects[root_name]
    else:
        # Create empty or mesh container
        mesh = bpy.data.meshes.new(DEFAULT_WORLD_MESH_NAME)
        root_obj = bpy.data.objects.new(root_name, mesh)
        root_obj.location = (0.0, 0.0, 0.0)
        context.collection.objects.link(root_obj)

    # 2. Material Manager for chunk materials
    mat_manager = LiveSyncMaterialManager(world_obj=root_obj, atlas_params=atlas_params)

    # 3. Precompute unique block states
    unique_states = set(block_map.values())
    state_cache: dict[str, CachedStateMeta] = {
        s: get_cached_state_meta(s, mat_manager, baker) for s in unique_states
    }

    # 4. Determine sections to update
    all_sections = storage.get_all_sections()
    if force_full_rebuild or not root_obj.children:
        target_sections = all_sections
    else:
        target_sections = storage.get_dirty_sections().intersection(all_sections)

    # Prune any section objects whose sections no longer exist or contain only air
    for child in list(root_obj.children):
        if child.name.startswith("Yefira_Section_"):
            try:
                parts = child.name.split("_")[2:]
                coords = (int(parts[0]), int(parts[1]), int(parts[2]))
                if coords not in all_sections:
                    child_mesh = child.data
                    bpy.data.objects.remove(child, do_unlink=True)
                    if child_mesh:
                        bpy.data.meshes.remove(child_mesh, do_unlink=True)
            except Exception:
                pass

    # 5. Build/Update target sections
    for (sx, sy, sz) in target_sections:
        sec_blocks = storage.get_section_blocks(sx, sy, sz)
        sec_obj_name = f"Yefira_Section_{sx}_{sy}_{sz}"
        sec_mesh_name = f"Mesh_{sec_obj_name}"

        # If section is empty or only air, remove
        if not sec_blocks or all(state_cache.get(s) and state_cache[s].is_air for s in sec_blocks.values()):
            sec_obj = bpy.data.objects.get(sec_obj_name)
            if sec_obj:
                sec_mesh = sec_obj.data
                bpy.data.objects.remove(sec_obj, do_unlink=True)
                if sec_mesh:
                    bpy.data.meshes.remove(sec_mesh, do_unlink=True)
            continue

        if sec_obj_name in bpy.data.objects:
            sec_obj = bpy.data.objects[sec_obj_name]
            sec_mesh = sec_obj.data
        else:
            sec_mesh = bpy.data.meshes.new(sec_mesh_name)
            sec_obj = bpy.data.objects.new(sec_obj_name, sec_mesh)
            sec_obj.location = (0.0, 0.0, 0.0)
            sec_obj.parent = root_obj
            context.collection.objects.link(sec_obj)

        # Keep section slot indices identical to the root material manager.
        _sync_section_material_slots(sec_obj, mat_manager)

        # Construct section BMesh
        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new("UVMap")
        color_layer = bm.loops.layers.color.new("Color")

        _generate_voxel_geometry(
            bm=bm,
            voxel_items=list(sec_blocks.items()),
            block_map=block_map,
            state_cache=state_cache,
            uv_layer=uv_layer,
            color_layer=color_layer,
            origin_centered=origin_centered,
            min_x=min_x, min_y=min_y, min_z=min_z,
            half_x=half_x, half_z=half_z,
            mat_manager=mat_manager,
            baker=baker,
        )

        if weld_vertices and len(bm.verts) > 0:
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)

        sec_mesh.clear_geometry()
        bm.to_mesh(sec_mesh)
        bm.free()

        # Face resolution may have loaded an additional chunk while building.
        _sync_section_material_slots(sec_obj, mat_manager)
        _rebind_mesh_material_indices(sec_mesh, mat_manager)

        sec_mesh.update()

    # Clear storage dirty set
    storage.clear_dirty_sections()

    # 6. Aggregate world metrics
    total_verts = 0
    total_faces = 0
    total_cubes = 0
    total_props = 0
    total_fluids = 0

    # Count from section child objects
    for child in root_obj.children:
        if child.data and isinstance(child.data, bpy.types.Mesh):
            total_verts += len(child.data.vertices)
            total_faces += len(child.data.polygons)

    for state_str, count in storage.get_state_counts().items():
        if count <= 0:
            continue
        m = state_cache.get(state_str)
        if not m or m.is_air:
            continue
        if m.parsed.is_waterlogged:
            total_fluids += count
        if m.is_fluid:
            if not m.parsed.is_waterlogged:
                total_fluids += count
        elif m.is_cube:
            total_cubes += count
        else:
            total_props += count

    return WorldMeshBuildResult(
        world_obj=root_obj,
        vertex_count=total_verts,
        face_count=total_faces,
        cubes_count=total_cubes,
        props_count=total_props,
        fluids_count=total_fluids,
    )


def apply_block_delta_to_world(
    context: bpy.types.Context,
    storage: VoxelStorage,
    changes: list[tuple[int, int, int, str]],
    atlas_params: Optional[dict[str, Any]] = None,
    origin_centered: bool = True,
) -> WorldMeshBuildResult:
    """
    Ultra-high-performance block-level incremental mesh modifier.
    Only updates the modified blocks and their 6 direct neighbors in the corresponding section mesh(es)
    (or root world mesh in single-mesh mode).
    Delivers sub-millisecond real-time sync when placing/breaking blocks in Minecraft.
    """
    if not changes or storage.size_x == 0 or storage.size_y == 0 or storage.size_z == 0:
        return WorldMeshBuildResult(None, 0, 0, 0, 0, 0)

    baker = get_shared_state_baker()

    min_x, min_y, min_z = storage.min_x, storage.min_y, storage.min_z
    size_x, size_y, size_z = storage.size_x, storage.size_y, storage.size_z
    half_x = size_x / 2.0 - 0.5
    half_z = size_z / 2.0 - 0.5

    # 1. Acquire root container object
    root_name = DEFAULT_WORLD_OBJECT_NAME
    if root_name in bpy.data.objects:
        root_obj = bpy.data.objects[root_name]
    else:
        mesh = bpy.data.meshes.new(DEFAULT_WORLD_MESH_NAME)
        root_obj = bpy.data.objects.new(root_name, mesh)
        root_obj.location = (0.0, 0.0, 0.0)
        context.collection.objects.link(root_obj)

    # 2. Material Manager for chunk materials (cached singleton)
    mat_manager = get_shared_material_manager(world_obj=root_obj, atlas_params=atlas_params)

    # 3. Find all blocks to update: changed blocks + neighbors (including 3x3 diagonal window for fluids)
    blocks_to_update: set[tuple[int, int, int]] = set()
    for abs_x, abs_y, abs_z, _state in changes:
        blocks_to_update.add((abs_x, abs_y, abs_z))
        is_fluid_change = is_fluid_block(_state) or is_fluid_block(storage.get_block(abs_x, abs_y, abs_z))
        if is_fluid_change:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        nx, ny, nz = abs_x + dx, abs_y + dy, abs_z + dz
                        if storage.contains(nx, ny, nz):
                            blocks_to_update.add((nx, ny, nz))
        else:
            for dx, dy, dz in MC_DIR_OFFSETS.values():
                nx, ny, nz = abs_x + dx, abs_y + dy, abs_z + dz
                if storage.contains(nx, ny, nz):
                    blocks_to_update.add((nx, ny, nz))

    # Pre-populate global cache for any new unique states in blocks_to_update
    for (x, y, z) in blocks_to_update:
        s = storage.get_block(x, y, z)
        if s and s not in _GLOBAL_STATE_META_CACHE:
            _GLOBAL_STATE_META_CACHE[s] = CachedStateMeta(s, mat_manager, baker)

    # 4. Check whether we are using section-based hierarchy or single-mesh mode
    has_section_children = any(c.name.startswith("Yefira_Section_") for c in root_obj.children)

    if not has_section_children and not root_obj.children and root_obj.data and len(root_obj.data.polygons) > 0:
        # Single World Mesh Mode
        update_blocks_in_mesh(
            mesh=root_obj.data,
            blocks_to_update=blocks_to_update,
            storage=storage,
            state_cache=_GLOBAL_STATE_META_CACHE,
            origin_centered=origin_centered,
            min_x=min_x, min_y=min_y, min_z=min_z,
            half_x=half_x, half_z=half_z,
            mat_manager=mat_manager,
            baker=baker,
        )
    else:
        # Section-based Hierarchy Mode
        sec_grouped: dict[tuple[int, int, int], set[tuple[int, int, int]]] = {}
        for (bx, by, bz) in blocks_to_update:
            sec_coord = (bx >> 4, by >> 4, bz >> 4)
            sec_grouped.setdefault(sec_coord, set()).add((bx, by, bz))

        for (sx, sy, sz), sec_blocks in sec_grouped.items():
            sec_obj_name = f"Yefira_Section_{sx}_{sy}_{sz}"
            sec_mesh_name = f"Mesh_{sec_obj_name}"

            sec_all_blocks = storage.get_section_blocks(sx, sy, sz)
            has_solid_blocks = bool(sec_all_blocks and any(
                (_GLOBAL_STATE_META_CACHE.get(s) and not _GLOBAL_STATE_META_CACHE[s].is_air)
                or (storage.get_block(px, py, pz) and not storage.get_block(px, py, pz).startswith("minecraft:air"))
                for (px, py, pz), s in sec_all_blocks.items()
            ))

            sec_obj = bpy.data.objects.get(sec_obj_name)
            if not sec_obj:
                if not has_solid_blocks:
                    continue
                sec_mesh = bpy.data.meshes.new(sec_mesh_name)
                sec_obj = bpy.data.objects.new(sec_obj_name, sec_mesh)
                sec_obj.location = (0.0, 0.0, 0.0)
                sec_obj.parent = root_obj
                context.collection.objects.link(sec_obj)

            # Keep section slot indices identical to the root material manager.
            _sync_section_material_slots(sec_obj, mat_manager)

            update_blocks_in_mesh(
                mesh=sec_obj.data,
                blocks_to_update=sec_blocks,
                storage=storage,
                state_cache=_GLOBAL_STATE_META_CACHE,
                origin_centered=origin_centered,
                min_x=min_x, min_y=min_y, min_z=min_z,
                half_x=half_x, half_z=half_z,
                mat_manager=mat_manager,
                baker=baker,
            )

            # Capture chunks loaded while resolving changed faces.
            slots_changed = _sync_section_material_slots(sec_obj, mat_manager)
            if slots_changed:
                _rebind_mesh_material_indices(sec_obj.data, mat_manager)

            # If section became empty, clean it up
            if len(sec_obj.data.polygons) == 0 and not has_solid_blocks:
                sec_mesh = sec_obj.data
                bpy.data.objects.remove(sec_obj, do_unlink=True)
                if sec_mesh:
                    bpy.data.meshes.remove(sec_mesh, do_unlink=True)

    # 5. Clear storage dirty set
    storage.clear_dirty_sections()

    # 6. Aggregate world metrics (fast path without scanning whole storage)
    total_verts = 0
    total_faces = 0
    total_cubes = 0
    total_props = 0
    total_fluids = 0

    if has_section_children or root_obj.children:
        for child in root_obj.children:
            if child.data and isinstance(child.data, bpy.types.Mesh):
                total_verts += len(child.data.vertices)
                total_faces += len(child.data.polygons)
    elif root_obj.data and isinstance(root_obj.data, bpy.types.Mesh):
        total_verts = len(root_obj.data.vertices)
        total_faces = len(root_obj.data.polygons)

    for state_str, count in storage.get_state_counts().items():
        if count <= 0:
            continue
        m = _GLOBAL_STATE_META_CACHE.get(state_str)
        if not m and state_str:
            m = get_cached_state_meta(state_str, mat_manager, baker)
        if not m or m.is_air:
            continue
        if m.parsed.is_waterlogged:
            total_fluids += count
        if m.is_fluid:
            if not m.parsed.is_waterlogged:
                total_fluids += count
        elif m.is_cube:
            total_cubes += count
        else:
            total_props += count

    return WorldMeshBuildResult(
        world_obj=root_obj,
        vertex_count=total_verts,
        face_count=total_faces,
        cubes_count=total_cubes,
        props_count=total_props,
        fluids_count=total_fluids,
    )

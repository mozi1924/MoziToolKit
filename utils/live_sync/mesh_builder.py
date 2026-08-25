"""
Direct Mesh Builder for MoziToolKit Live Sync.
Constructs native Blender Polygon Meshes directly from VoxelStorage.
Features:
- Sub-millisecond neighbor-aware 6-face culling (Opaque & Translucent).
- Native loop UV mapping directly into Atlas Chunks (no Geometry Nodes attributes).
- Direct Face Material Indexing corresponding to pre-baked Atlas Material slots.
- Native Color Attributes for Biome and State Tinting.
- Support for complex multipart/non-cube models via StateBaker.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, Set
import bpy
import bmesh
from mathutils import Vector
import numpy as np

from .storage import VoxelStorage
from .classifier import (
    parse_and_classify,
    BlockTypeEnum,
    ParsedBlock,
    AIR_BLOCKS,
    TRANSPARENT_BLOCKS,
    FLUID_BLOCKS,
    atlas_lookup_keys,
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
    FACES,
)
from ..mc_baker import (
    StateBaker,
    BakedModel,
    BakedFace,
    get_shared_state_baker,
    refresh_shared_baker_sources,
)

def atlas_uv_from_local(
    u: float,
    v: float,
    *,
    tile_column: int,
    tile_row: int,
    tile_size: float,
    atlas_width: float,
    atlas_height: float,
) -> tuple[float, float]:
    return (
        (tile_column + u) * tile_size / atlas_width,
        1.0 - (tile_row + 1.0 - v) * tile_size / atlas_height,
    )

def atlas_uv_from_rect(
    u: float,
    v: float,
    *,
    pixel_x: float,
    pixel_y: float,
    rect_width: float,
    rect_height: float,
    atlas_width: float,
    atlas_height: float,
) -> tuple[float, float]:
    return (
        (pixel_x + u * rect_width) / atlas_width,
        1.0 - (pixel_y + (1.0 - v) * rect_height) / atlas_height,
    )

from .material_manager import LiveSyncMaterialManager, ResolvedFaceTexture

logger = logging.getLogger("MoziToolKit.MeshBuilder")

# Direction vectors in Minecraft space (East=+X, West=-X, Up=+Y, Down=-Y, South=+Z, North=-Z)
MC_DIR_OFFSETS = {
    "east": (1, 0, 0),
    "west": (-1, 0, 0),
    "up": (0, 1, 0),
    "top": (0, 1, 0),
    "down": (0, -1, 0),
    "bottom": (0, -1, 0),
    "south": (0, 0, 1),
    "north": (0, 0, -1),
}

# Standard Unit Cube Quads in Minecraft local coordinates [0..1]
# Ordered counter-clockwise for outward-pointing normals
CUBE_FACE_MC_VERTICES = {
    "east": ((1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (1.0, 1.0, 1.0), (1.0, 0.0, 1.0)),
    "west": ((0.0, 0.0, 1.0), (0.0, 1.0, 1.0), (0.0, 1.0, 0.0), (0.0, 0.0, 0.0)),
    "up": ((0.0, 1.0, 1.0), (1.0, 1.0, 1.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)),
    "top": ((0.0, 1.0, 1.0), (1.0, 1.0, 1.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)),
    "down": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 0.0, 1.0)),
    "bottom": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 0.0, 1.0)),
    "south": ((1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0), (0.0, 0.0, 1.0)),
    "north": ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0), (1.0, 0.0, 0.0)),
}

# Standard Face Default UVs corresponding to the quad vertices above
CUBE_FACE_DEFAULT_UVS = {
    "east": ((1.0, 1.0), (1.0, 0.0), (0.0, 0.0), (0.0, 1.0)),
    "west": ((1.0, 1.0), (1.0, 0.0), (0.0, 0.0), (0.0, 1.0)),
    "up": ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)),
    "top": ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)),
    "down": ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)),
    "bottom": ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)),
    "south": ((1.0, 1.0), (1.0, 0.0), (0.0, 0.0), (0.0, 1.0)),
    "north": ((1.0, 1.0), (1.0, 0.0), (0.0, 0.0), (0.0, 1.0)),
}


def _mc_local_to_blender(lx: float, ly: float, lz: float) -> tuple[float, float, float]:
    """Convert Minecraft local offset [0..1] relative to block center to Blender space."""
    return (
        lx - 0.5,
        -(lz - 0.5),  # MC North (-Z) is Blender +Y
        ly - 0.5,     # MC Up (+Y) is Blender +Z
    )


def _rotate_uv(u: float, v: float, angle_deg: float) -> tuple[float, float]:
    """Rotate local UV coordinate clockwise by 0, 90, 180, or 270 degrees."""
    if angle_deg == 90.0:
        return (v, 1.0 - u)
    elif angle_deg == 180.0:
        return (1.0 - u, 1.0 - v)
    elif angle_deg == 270.0:
        return (1.0 - v, u)
    return (u, v)


class CachedStateMeta:
    """Precomputed metadata for a unique block state."""
    __slots__ = (
        'state_str', 'parsed', 'is_cube', 'is_opaque', 'is_air',
        'is_fluid', 'is_transparent', 'baked_model', 'faces_info'
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
            self.is_opaque = baked.is_opaque and not self.is_transparent
        else:
            self.is_cube = self.parsed.block_type == BlockTypeEnum.CUBE
            self.is_opaque = (self.parsed.is_opaque != 0) and not self.is_transparent

        # Resolve per-face texture addressing via MaterialManager
        self.faces_info: dict[str, ResolvedFaceTexture] = {}
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
                # Also set aliases for top/up and bottom/down
                if f_name == "top":
                    self.faces_info["up"] = resolved
                elif f_name == "bottom":
                    self.faces_info["down"] = resolved


def _calculate_atlas_uv(u: float, v: float, face_info: dict[str, Any]) -> tuple[float, float]:
    """Calculate final Atlas global UV from local normalized (u, v) and resolved face metadata."""
    loc = face_info.get("loc")
    if loc and loc.get("kind") == "animation":
        px = float(loc.get("pixel_x", 0))
        py = float(loc.get("pixel_y", 0))
        fw = float(loc.get("frame_width", 16))
        fh = float(loc.get("frame_height", 16))
        return atlas_uv_from_rect(
            u, v,
            pixel_x=px,
            pixel_y=py,
            rect_width=fw,
            rect_height=fh,
            atlas_width=face_info["anim_atlas_width"],
            atlas_height=face_info["anim_atlas_height"],
        )
    elif loc:
        col = int(loc.get("tile_column", 0))
        row = int(loc.get("tile_row", 0))
        return atlas_uv_from_local(
            u, v,
            tile_column=col,
            tile_row=row,
            tile_size=face_info["tile_size"],
            atlas_width=face_info["atlas_width"],
            atlas_height=face_info["atlas_height"],
        )
    else:
        # Fallback identity 0..1
        return (u, v)


def _rotate_uv(u: float, v: float, angle_deg: float) -> tuple[float, float]:
    """Rotate local UV coordinate clockwise by 0, 90, 180, or 270 degrees."""
    if angle_deg == 90.0:
        return (v, 1.0 - u)
    elif angle_deg == 180.0:
        return (1.0 - u, 1.0 - v)
    elif angle_deg == 270.0:
        return (1.0 - v, u)
    return (u, v)


class WorldMeshBuildResult(NamedTuple):
    world_obj: Optional[bpy.types.Object]
    vertex_count: int
    face_count: int
    cubes_count: int
    props_count: int
    fluids_count: int


def build_world_mesh(
    context: bpy.types.Context,
    storage: VoxelStorage,
    atlas_params: Optional[dict[str, Any]] = None,
    filter_air: bool = True,
    origin_centered: bool = True,
    weld_vertices: bool = True,
) -> WorldMeshBuildResult:
    """
    Constructs the full native Blender polygon mesh with native UVMap, Material Slots,
    and Biome Tinting directly from VoxelStorage.
    If weld_vertices is True, merges duplicate co-located vertices in-engine for optimal geometry topology.
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

    # 2. Create or acquire target Mesh Object
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

    # 3. Dynamic Material Manager: auto-loads precompiled chunk materials and sets slots
    mat_manager = LiveSyncMaterialManager(world_obj=obj, atlas_params=atlas_params)

    # 4. Precompute metadata for unique block states in the storage
    unique_states = set(block_map.values())
    state_cache: dict[str, CachedStateMeta] = {
        s: CachedStateMeta(s, mat_manager, baker) for s in unique_states
    }

    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    color_layer = bm.loops.layers.color.new("Color")

    cubes_count = 0
    props_count = 0
    fluids_count = 0

    # 5. Iterate through voxels and generate geometry with face culling
    for (x, y, z), state_str in block_map.items():
        meta = state_cache.get(state_str)
        if not meta or meta.is_air:
            continue

        if origin_centered:
            bx = (x - min_x) - half_x
            by = -((z - min_z) - half_z)
            bz = (y - min_y) + 0.5
        else:
            bx = float(x)
            by = -float(z)
            bz = float(y)

        if meta.is_fluid:
            fluids_count += 1
            # Fluid top surface & visible faces
            for f_name in FACES:
                dx, dy, dz = MC_DIR_OFFSETS[f_name]
                neighbor_pos = (x + dx, y + dy, z + dz)
                neighbor_state = block_map.get(neighbor_pos)
                if neighbor_state is not None:
                    n_meta = state_cache.get(neighbor_state)
                    # Cull if neighbor is opaque cube or same fluid
                    if n_meta and (n_meta.is_opaque or n_meta.is_fluid):
                        continue

                f_res: ResolvedFaceTexture = meta.faces_info[f_name]
                mc_verts = CUBE_FACE_MC_VERTICES[f_name]
                default_uvs = CUBE_FACE_DEFAULT_UVS[f_name]

                face_bm_verts = []
                for (lx, ly, lz) in mc_verts:
                    vx, vy, vz = _mc_local_to_blender(lx, ly, lz)
                    face_bm_verts.append(bm.verts.new((bx + vx, by + vy, bz + vz)))

                try:
                    bm_face = bm.faces.new(face_bm_verts)
                except ValueError:
                    continue

                bm_face.material_index = f_res.slot_index

                for loop_idx, loop in enumerate(bm_face.loops):
                    u_raw, v_raw = default_uvs[loop_idx]
                    loop[uv_layer].uv = Vector(f_res.calc_uv_fn(u_raw, v_raw))
                    loop[color_layer] = f_res.tint_color

        elif meta.is_cube:
            cubes_count += 1
            # Standard Cube 6-face culling & assembly
            for f_name in FACES:
                dx, dy, dz = MC_DIR_OFFSETS[f_name]
                neighbor_pos = (x + dx, y + dy, z + dz)
                neighbor_state = block_map.get(neighbor_pos)

                if neighbor_state is not None:
                    n_meta = state_cache.get(neighbor_state)
                    # Cull if neighbor is a full opaque cube
                    if n_meta and n_meta.is_cube and n_meta.is_opaque:
                        continue

                f_res: ResolvedFaceTexture = meta.faces_info[f_name]
                mc_verts = CUBE_FACE_MC_VERTICES[f_name]
                default_uvs = CUBE_FACE_DEFAULT_UVS[f_name]

                # Construct 4 vertices for this face
                face_bm_verts = []
                for (lx, ly, lz) in mc_verts:
                    vx, vy, vz = _mc_local_to_blender(lx, ly, lz)
                    face_bm_verts.append(bm.verts.new((bx + vx, by + vy, bz + vz)))

                try:
                    bm_face = bm.faces.new(face_bm_verts)
                except ValueError:
                    continue

                bm_face.material_index = f_res.slot_index

                # Assign loop UV and loop Color
                for loop_idx, loop in enumerate(bm_face.loops):
                    u_raw, v_raw = default_uvs[loop_idx]
                    u_rot, v_rot = _rotate_uv(u_raw, v_raw, f_res.uv_rot)
                    loop[uv_layer].uv = Vector(f_res.calc_uv_fn(u_rot, v_rot))
                    loop[color_layer] = f_res.tint_color if f_res.use_tint else (1.0, 1.0, 1.0, 1.0)

        elif meta.baked_model and meta.baked_model.elements:
            props_count += 1
            # Complex multipart / custom JSON model
            for elem in meta.baked_model.elements:
                for f_dir, bf in elem.faces.items():
                    if not bf.vertices or len(bf.vertices) < 4:
                        continue

                    # Direction neighbor check for outer full culling
                    if bf.cullface and bf.cullface in MC_DIR_OFFSETS:
                        dx, dy, dz = MC_DIR_OFFSETS[bf.cullface]
                        n_pos = (x + dx, y + dy, z + dz)
                        n_state = block_map.get(n_pos)
                        if n_state is not None:
                            n_meta = state_cache.get(n_state)
                            if n_meta and n_meta.is_cube and n_meta.is_opaque:
                                continue

                    f_res: ResolvedFaceTexture = meta.faces_info.get(bf.direction, meta.faces_info["east"])

                    face_bm_verts = []
                    for (lx, ly, lz) in bf.vertices:
                        vx, vy, vz = _mc_local_to_blender(lx, ly, lz)
                        face_bm_verts.append(bm.verts.new((bx + vx, by + vy, bz + vz)))

                    try:
                        bm_face = bm.faces.new(face_bm_verts)
                    except ValueError:
                        continue

                    bm_face.material_index = f_res.slot_index

                    for loop_idx, loop in enumerate(bm_face.loops):
                        if loop_idx < len(bf.uvs):
                            u_raw, v_raw = bf.uvs[loop_idx]
                        else:
                            u_raw, v_raw = (0.0, 0.0)
                        u_rot, v_rot = _rotate_uv(u_raw, 1.0 - v_raw, bf.uv_rot)
                        loop[uv_layer].uv = Vector(f_res.calc_uv_fn(u_rot, v_rot))
                        loop[color_layer] = meta.parsed.tint_color if (bf.tint_index >= 0 or f_res.use_tint) else (1.0, 1.0, 1.0, 1.0)

    # 6. Optional in-engine vertex welding for optimal topology
    if weld_vertices and len(bm.verts) > 0:
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)

    # 7. Push BMesh data back to Blender Mesh
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

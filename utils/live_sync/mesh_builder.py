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


class CachedStateMeta:
    """Precomputed metadata for a unique block state."""
    __slots__ = (
        'state_str', 'parsed', 'is_cube', 'is_opaque', 'is_air',
        'is_fluid', 'is_transparent', 'baked_model', 'faces_info'
    )

    def __init__(self, state_str: str, atlas_params: dict[str, Any], baker: StateBaker):
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

        # Precompute face mapping info (skip for air)
        self.faces_info = self._resolve_faces_info(atlas_params) if not self.is_air else {}

    def _resolve_faces_info(self, atlas_params: dict[str, Any]) -> dict[str, dict[str, Any]]:
        info = {}
        json_faces = None
        if self.state_str and self.state_str.startswith("{") and self.state_str.endswith("}"):
            try:
                import json
                j_obj = json.loads(self.state_str)
                if isinstance(j_obj, dict) and isinstance(j_obj.get("faces"), dict):
                    json_faces = j_obj["faces"]
            except Exception:
                json_faces = None

        mapping_tex = atlas_params.get("mapping", {}).get("textures", {}) if isinstance(atlas_params.get("mapping"), dict) else {}
        if not mapping_tex and "atlas_mapping_textures" in atlas_params:
            mapping_tex = atlas_params["atlas_mapping_textures"]

        tile_size = float(atlas_params.get("tile_size", DEFAULT_TILE_SIZE))
        atlas_w = float(atlas_params.get("width", DEFAULT_ATLAS_WIDTH))
        atlas_h = float(atlas_params.get("height", DEFAULT_ATLAS_HEIGHT))
        tiles_per_row = int(atlas_params.get("tiles_per_row", DEFAULT_TILES_PER_ROW))

        anim_w = float(atlas_params.get("anim_atlas_width", atlas_params.get("chunk_1_width", DEFAULT_ANIM_ATLAS_WIDTH)))
        anim_h = float(atlas_params.get("anim_atlas_height", atlas_params.get("chunk_1_height", DEFAULT_ANIM_ATLAS_HEIGHT)))

        block_face_lut = atlas_params.get("block_face_lut", {})
        block_face_chunk_lut = atlas_params.get("block_face_chunk_lut", {})
        block_face_tint_lut = atlas_params.get("block_face_tint_lut", {})

        for f_idx, f_name in enumerate(FACES):
            tex_name = None
            uv_rot = 0.0
            tint_idx = -1
            if json_faces and f_name in json_faces:
                f_item = json_faces[f_name]
                tex_name = f_item.get("tex")
                uv_rot = float(f_item.get("rot", 0.0))
                tint_idx = int(f_item.get("tint", -1))
            elif self.baked_model and len(self.baked_model.faces) > f_idx:
                bf = self.baked_model.faces[f_idx]
                tex_name = bf.texture
                uv_rot = bf.uv_rot
                tint_idx = bf.tint_index

            loc = None
            if tex_name and mapping_tex:
                short_tex = tex_name.split(":", 1)[-1].removeprefix("block/")
                loc = (
                    mapping_tex.get(tex_name)
                    or mapping_tex.get(f"minecraft:{short_tex}")
                    or mapping_tex.get(f"minecraft:block/{short_tex}")
                    or mapping_tex.get(short_tex)
                )
            if loc is None and mapping_tex and self.parsed.name in mapping_tex:
                loc = mapping_tex.get(self.parsed.name)

            chunk_id = 0
            if loc:
                chunk_id = int(loc.get("chunk_id", 0))
            elif block_face_chunk_lut:
                c_lut = block_face_chunk_lut.get(self.parsed.name) or block_face_chunk_lut.get(self.parsed.full_state)
                if c_lut and len(c_lut) > f_idx:
                    chunk_id = int(c_lut[f_idx])

            # Tint weight / data
            tint_color = self.parsed.tint_color
            if tint_idx >= 0 or (loc and loc.get("default_tint_weight", 0.0) > 0):
                use_tint = True
            elif block_face_tint_lut:
                t_lut = block_face_tint_lut.get(self.parsed.name) or block_face_tint_lut.get(self.parsed.full_state)
                use_tint = bool(t_lut and len(t_lut) > f_idx and t_lut[f_idx][2] > 0)
            else:
                use_tint = False

            info[f_name] = {
                "loc": loc,
                "chunk_id": chunk_id,
                "uv_rot": uv_rot,
                "use_tint": use_tint,
                "tint_color": tint_color,
                "tile_size": tile_size,
                "atlas_width": atlas_w,
                "atlas_height": atlas_h,
                "tiles_per_row": tiles_per_row,
                "anim_atlas_width": anim_w,
                "anim_atlas_height": anim_h,
            }
        return info


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
) -> WorldMeshBuildResult:
    """
    Constructs the full native Blender polygon mesh with native UVMap, Material Slots,
    and Biome Tinting directly from VoxelStorage.
    """
    if storage.size_x == 0 or storage.size_y == 0 or storage.size_z == 0:
        return WorldMeshBuildResult(None, 0, 0, 0, 0, 0)

    block_map = storage.block_map
    if not block_map:
        return WorldMeshBuildResult(None, 0, 0, 0, 0, 0)

    refresh_shared_baker_sources()
    baker = get_shared_state_baker()
    params = atlas_params or {}

    # 1. Precompute metadata for unique block states in the storage
    unique_states = set(block_map.values())
    state_cache: dict[str, CachedStateMeta] = {
        s: CachedStateMeta(s, params, baker) for s in unique_states
    }

    # 2. Coordinate transformation parameters
    min_x, min_y, min_z = storage.min_x, storage.min_y, storage.min_z
    size_x, size_y, size_z = storage.size_x, storage.size_y, storage.size_z
    half_x = size_x / 2.0 - 0.5
    half_z = size_z / 2.0 - 0.5

    # 3. Create or acquire target Mesh Object
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

    # 4. Setup material slots on target object for all chunks
    try:
        from ..materials.yefira import (
            find_bound_atlas_material,
            get_or_create_atlas_material,
            setup_material_slots_for_object,
        )
        bound_mat = find_bound_atlas_material(obj) or get_or_create_atlas_material()
        chunk_mapping = params.get("mapping")
        setup_material_slots_for_object(obj, bound_mat, chunk_mapping)
    except Exception:
        pass

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

        center = (bx, by, bz)

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

                f_info = meta.faces_info[f_name]
                mc_verts = CUBE_FACE_MC_VERTICES[f_name]
                default_uvs = CUBE_FACE_DEFAULT_UVS[f_name]
                chunk_id = f_info.get("chunk_id", 0)
                tint_color = f_info.get("tint_color", (1.0, 1.0, 1.0, 1.0))

                face_bm_verts = []
                for (lx, ly, lz) in mc_verts:
                    vx, vy, vz = _mc_local_to_blender(lx, ly, lz)
                    face_bm_verts.append(bm.verts.new((bx + vx, by + vy, bz + vz)))

                try:
                    bm_face = bm.faces.new(face_bm_verts)
                except ValueError:
                    continue

                bm_face.material_index = chunk_id

                for loop_idx, loop in enumerate(bm_face.loops):
                    u_raw, v_raw = default_uvs[loop_idx]
                    u_atlas, v_atlas = _calculate_atlas_uv(u_raw, v_raw, f_info)
                    loop[uv_layer].uv = Vector((u_atlas, v_atlas))
                    loop[color_layer] = tint_color

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

                f_info = meta.faces_info[f_name]
                mc_verts = CUBE_FACE_MC_VERTICES[f_name]
                default_uvs = CUBE_FACE_DEFAULT_UVS[f_name]
                uv_rot = f_info.get("uv_rot", 0.0)
                chunk_id = f_info.get("chunk_id", 0)
                tint_color = f_info.get("tint_color", (1.0, 1.0, 1.0, 1.0))
                use_tint = f_info.get("use_tint", False)
                final_color = tint_color if use_tint else (1.0, 1.0, 1.0, 1.0)

                # Construct 4 vertices for this face
                face_bm_verts = []
                for (lx, ly, lz) in mc_verts:
                    vx, vy, vz = _mc_local_to_blender(lx, ly, lz)
                    face_bm_verts.append(bm.verts.new((bx + vx, by + vy, bz + vz)))

                try:
                    bm_face = bm.faces.new(face_bm_verts)
                except ValueError:
                    continue

                bm_face.material_index = chunk_id

                # Assign loop UV and loop Color
                for loop_idx, loop in enumerate(bm_face.loops):
                    u_raw, v_raw = default_uvs[loop_idx]
                    u_rot, v_rot = _rotate_uv(u_raw, v_raw, uv_rot)
                    u_atlas, v_atlas = _calculate_atlas_uv(u_rot, v_rot, f_info)
                    loop[uv_layer].uv = Vector((u_atlas, v_atlas))
                    loop[color_layer] = final_color

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

                    f_info = meta.faces_info.get(bf.direction, meta.faces_info["east"])
                    chunk_id = f_info.get("chunk_id", 0)
                    use_tint = bf.tint_index >= 0 or f_info.get("use_tint", False)
                    final_color = meta.parsed.tint_color if use_tint else (1.0, 1.0, 1.0, 1.0)

                    face_bm_verts = []
                    for (lx, ly, lz) in bf.vertices:
                        vx, vy, vz = _mc_local_to_blender(lx, ly, lz)
                        face_bm_verts.append(bm.verts.new((bx + vx, by + vy, bz + vz)))

                    try:
                        bm_face = bm.faces.new(face_bm_verts)
                    except ValueError:
                        continue

                    bm_face.material_index = chunk_id

                    for loop_idx, loop in enumerate(bm_face.loops):
                        if loop_idx < len(bf.uvs):
                            u_raw, v_raw = bf.uvs[loop_idx]
                        else:
                            u_raw, v_raw = (0.0, 0.0)
                        u_rot, v_rot = _rotate_uv(u_raw, 1.0 - v_raw, bf.uv_rot)
                        u_atlas, v_atlas = _calculate_atlas_uv(u_rot, v_rot, f_info)
                        loop[uv_layer].uv = Vector((u_atlas, v_atlas))
                        loop[color_layer] = final_color

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

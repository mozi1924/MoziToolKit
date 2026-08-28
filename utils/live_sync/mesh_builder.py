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

from .storage import VoxelStorage
from .constants import (
    DEFAULT_WORLD_OBJECT_NAME,
    DEFAULT_WORLD_MESH_NAME,
    MC_DIR_OFFSETS,
)
from ..mc_baker import (
    get_shared_state_baker,
    refresh_shared_baker_sources,
)
from .material_manager import LiveSyncMaterialManager
from .fluid_mesher import is_fluid_block
from .material_binding import (
    get_shared_material_manager,
    sync_section_material_slots,
    rebind_mesh_material_indices,
)
from .mesh_cache import (
    CachedStateMeta,
    get_cached_state_meta,
    preload_sync_world_data,
    clear_mesh_builder_caches,
    _GLOBAL_STATE_META_CACHE,
    COMMON_PREWARM_STATES,
    _idle_prewarm_tick,
)
from .geometry_builder import (
    CUBE_FACE_MC_VERTICES,
    CUBE_FACE_CANONICAL_UVS,
    _mc_local_to_blender,
    _get_or_create_bmesh_layers,
    _emit_bmesh_face,
    generate_single_block_faces,
    generate_voxel_geometry,
)

logger = logging.getLogger("MoziToolKit.MeshBuilder")

# Re-exports for backward compatibility
_sync_section_material_slots = sync_section_material_slots
_rebind_mesh_material_indices = rebind_mesh_material_indices
_generate_single_block_faces = generate_single_block_faces
_generate_voxel_geometry = generate_voxel_geometry


class WorldMeshBuildResult(NamedTuple):
    world_obj: Optional[bpy.types.Object]
    vertex_count: int
    face_count: int
    cubes_count: int
    props_count: int
    fluids_count: int


def update_blocks_in_mesh(
    mesh: bpy.types.Mesh,
    blocks_to_update: set[tuple[int, int, int]],
    storage: VoxelStorage,
    state_cache: dict[str, CachedStateMeta],
    origin_centered: bool = True,
    min_x: int = 0, min_y: int = 0, min_z: int = 0,
    half_x: float = 0.0, half_z: float = 0.0,
    mat_manager: Optional[LiveSyncMaterialManager] = None,
    baker: Optional[Any] = None,
) -> None:
    """
    Incrementally edits target blocks within an existing Mesh via BMesh.
    Deletes old faces of affected blocks, cleans up orphan vertices,
    and inserts newly visible faces without regenerating the rest of the mesh.
    """
    bm = bmesh.new()
    try:
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
                generate_single_block_faces(
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
    finally:
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

    # 3. Material Manager (cached singleton)
    mat_manager = get_shared_material_manager(world_obj=obj, atlas_params=atlas_params)

    # 4. Precompute unique block states
    unique_states = set(block_map.values())
    state_cache: dict[str, CachedStateMeta] = {
        s: get_cached_state_meta(s, mat_manager, baker) for s in unique_states
    }

    bm = bmesh.new()
    try:
        uv_layer = bm.loops.layers.uv.new("UVMap")
        color_layer = bm.loops.layers.color.new("Color")

        cubes_count, props_count, fluids_count = generate_voxel_geometry(
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
    finally:
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
        mesh = bpy.data.meshes.new(DEFAULT_WORLD_MESH_NAME)
        root_obj = bpy.data.objects.new(root_name, mesh)
        root_obj.location = (0.0, 0.0, 0.0)
        context.collection.objects.link(root_obj)

    # 2. Material Manager for chunk materials (cached singleton)
    mat_manager = get_shared_material_manager(world_obj=root_obj, atlas_params=atlas_params)

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
        sync_section_material_slots(sec_obj, mat_manager)

        # Construct section BMesh
        bm = bmesh.new()
        try:
            uv_layer = bm.loops.layers.uv.new("UVMap")
            color_layer = bm.loops.layers.color.new("Color")

            generate_voxel_geometry(
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
        finally:
            bm.free()

        # Face resolution may have loaded an additional chunk while building.
        sync_section_material_slots(sec_obj, mat_manager)
        rebind_mesh_material_indices(sec_mesh, mat_manager)

        sec_mesh.update()

    # Clear storage dirty set
    storage.clear_dirty_sections()

    # 6. Aggregate world metrics
    total_verts = 0
    total_faces = 0
    total_cubes = 0
    total_props = 0
    total_fluids = 0

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
    previous_states: Optional[dict[tuple[int, int, int], str]] = None,
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
    previous_states = previous_states or {}
    for abs_x, abs_y, abs_z, _state in changes:
        blocks_to_update.add((abs_x, abs_y, abs_z))
        # The current storage value is already the new state.  Consult the
        # pre-delta state as well, otherwise water -> air is treated as an
        # ordinary block removal and leaves neighboring sloped faces behind.
        is_fluid_change = (
            is_fluid_block(_state)
            or is_fluid_block(previous_states.get((abs_x, abs_y, abs_z)))
            or is_fluid_block(storage.get_block(abs_x, abs_y, abs_z))
        )
        if not is_fluid_change:
            for dx, dy, dz in MC_DIR_OFFSETS.values():
                if is_fluid_block(storage.get_block(abs_x + dx, abs_y + dy, abs_z + dz)):
                    is_fluid_change = True
                    break

        if is_fluid_change:
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for dy in range(-2, 3):
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
        slots_changed = sync_section_material_slots(root_obj, mat_manager)
        if slots_changed:
            rebind_mesh_material_indices(root_obj.data, mat_manager)
    else:
        # Section-based Hierarchy Mode
        sec_grouped: dict[tuple[int, int, int], set[tuple[int, int, int]]] = {}
        for (bx, by, bz) in blocks_to_update:
            sec_coord = (bx >> 4, by >> 4, bz >> 4)
            sec_grouped.setdefault(sec_coord, set()).add((bx, by, bz))

        any_slots_changed = False
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
            sync_section_material_slots(sec_obj, mat_manager)

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
            slots_changed = sync_section_material_slots(sec_obj, mat_manager)
            if slots_changed:
                rebind_mesh_material_indices(sec_obj.data, mat_manager)
                any_slots_changed = True

            # If section became empty, clean it up
            if len(sec_obj.data.polygons) == 0 and not has_solid_blocks:
                sec_mesh = sec_obj.data
                bpy.data.objects.remove(sec_obj, do_unlink=True)
                if sec_mesh:
                    bpy.data.meshes.remove(sec_mesh, do_unlink=True)

        if any_slots_changed:
            for child in root_obj.children:
                if child.name.startswith("Yefira_Section_") and child.data:
                    sync_section_material_slots(child, mat_manager)
                    rebind_mesh_material_indices(child.data, mat_manager)

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

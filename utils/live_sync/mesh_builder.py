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
    Supports both Object Mode and active Edit Mode seamlessly.
    """
    is_edit = getattr(mesh, "is_editmode", False)
    if is_edit:
        bm = bmesh.from_edit_mesh(mesh)
    else:
        bm = bmesh.new()
        bm.from_mesh(mesh)

    try:
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
                    voxel_storage=storage,
                )

        # 3. Clean up any leftover orphan vertices
        orphan_verts = [v for v in bm.verts if not v.link_faces]
        if orphan_verts:
            bmesh.ops.delete(bm, geom=orphan_verts, context='VERTS')

        if is_edit:
            bmesh.update_edit_mesh(mesh, loop_triangles=True, destructive=True)
        else:
            mesh.clear_geometry()
            bm.to_mesh(mesh)
            mesh.update()
    finally:
        if not is_edit:
            bm.free()


# Helper functions for root container and section object naming


def get_section_object_name(root_prefix: str, sx: int, sy: int, sz: int) -> str:
    """Return canonical object name for a 16x16x16 section chunk under root object."""
    return f"{root_prefix}_Section_{sx}_{sy}_{sz}"


def get_section_mesh_name(root_prefix: str, sx: int, sy: int, sz: int) -> str:
    """Return canonical mesh name for a 16x16x16 section chunk under root object."""
    return f"Mesh_{root_prefix}_Section_{sx}_{sy}_{sz}"


def is_yefira_root_object(obj: Optional[bpy.types.Object]) -> bool:
    """Identify whether a Blender object is a root Yefira live sync world container."""
    if not obj:
        return False
    if obj.get("mtk:is_yefira_world"):
        if not obj.parent or not obj.parent.get("mtk:is_yefira_world"):
            return True
    if obj.name == DEFAULT_WORLD_OBJECT_NAME or obj.name.startswith("Yefira_World"):
        return True
    if obj.type == 'EMPTY' and any(c.get("mtk:section_pos") is not None or "_Section_" in c.name for c in obj.children):
        return True
    return False


def is_yefira_child_section(obj: Optional[bpy.types.Object]) -> bool:
    """Identify whether a Blender object is a child section mesh chunk of a Yefira world."""
    if not obj or obj.type != 'MESH':
        return False
    if obj.get("mtk:section_pos") is not None:
        return True
    if "_Section_" in obj.name or obj.name.startswith("Yefira_Section_"):
        return True
    return False


def is_yefira_object(obj: Optional[bpy.types.Object]) -> bool:
    """Identify whether a Blender object is either a root container or child section of Yefira."""
    if not obj:
        return False
    if obj.get("mtk:is_yefira_world") or obj.get("mtk:section_pos") is not None:
        return True
    if is_yefira_root_object(obj) or is_yefira_child_section(obj):
        return True
    if obj.parent and is_yefira_root_object(obj.parent):
        return True
    return False


def resolve_world_root_object(obj: Optional[bpy.types.Object]) -> Optional[bpy.types.Object]:
    """Given any object (root empty, child section mesh, or descendant), resolve to the topmost Yefira World root container."""
    if not obj:
        return None
    # 1. If object has a parent, climb up to find the root container
    curr = obj
    while curr.parent:
        if is_yefira_root_object(curr.parent):
            return curr.parent
        curr = curr.parent
    if is_yefira_root_object(curr):
        return curr
    # 2. If the object itself is a child section mesh without a linked parent yet
    if is_yefira_child_section(obj):
        prefix = obj.name.split("_Section_")[0]
        root_match = bpy.data.objects.get(prefix)
        if root_match and is_yefira_root_object(root_match):
            return root_match
    # 3. If the object is an Empty or tagged as world
    if is_yefira_root_object(obj):
        return obj
    return None


def get_or_create_world_root(
    context: Optional[bpy.types.Context] = None,
    root_name: Optional[str] = None,
    target_obj: Optional[bpy.types.Object] = None,
) -> bpy.types.Object:
    """
    Acquire or instantiate the root Empty container for Yefira Live Sync world geometry.
    Always resolves child section meshes to their parent world container.
    """
    if target_obj and getattr(target_obj, "name", None) in bpy.data.objects:
        resolved = resolve_world_root_object(target_obj)
        if resolved:
            return resolved
        if is_yefira_root_object(target_obj):
            return target_obj

    if root_name and root_name in bpy.data.objects:
        obj = bpy.data.objects[root_name]
        resolved = resolve_world_root_object(obj)
        if resolved:
            return resolved
        if is_yefira_root_object(obj):
            return obj

    ctx = context or (bpy.context if hasattr(bpy, "context") else None)
    active_obj = getattr(ctx, "active_object", None) if ctx else None
    if active_obj:
        resolved = resolve_world_root_object(active_obj)
        if resolved:
            return resolved

    target_name = root_name or DEFAULT_WORLD_OBJECT_NAME
    if target_name in bpy.data.objects:
        obj = bpy.data.objects[target_name]
        resolved = resolve_world_root_object(obj)
        if resolved:
            return resolved

    # Find any existing object tagged as Yefira world (prefer empty roots)
    for obj in bpy.data.objects:
        if is_yefira_root_object(obj):
            return obj

    # Create new Empty object container (no dummy mesh)
    root_obj = bpy.data.objects.new(target_name, None)
    root_obj.empty_display_type = 'PLAIN_AXES'
    root_obj.empty_display_size = 1.0
    root_obj["mtk:is_yefira_world"] = True
    root_obj["mtk:sync_manifest"] = "{}"
    root_obj["mtk:last_name"] = root_obj.name
    root_obj.location = (0.0, 0.0, 0.0)

    col = getattr(ctx, "collection", None) if ctx else None
    if col is None and hasattr(bpy.context, "scene") and hasattr(bpy.context.scene, "collection"):
        col = bpy.context.scene.collection
    if col:
        col.objects.link(root_obj)

    return root_obj


def find_root_section_children(root_obj: bpy.types.Object) -> dict[tuple[int, int, int], bpy.types.Object]:
    """Find and map all child section objects of root_obj by their section coordinates."""
    sections: dict[tuple[int, int, int], bpy.types.Object] = {}
    if not root_obj:
        return sections
    for child in root_obj.children:
        pos = child.get("mtk:section_pos")
        if pos is not None and len(pos) == 3:
            sections[(int(pos[0]), int(pos[1]), int(pos[2]))] = child
        elif "_Section_" in child.name:
            try:
                parts = child.name.split("_Section_")[-1].split("_")
                coords = (int(parts[0]), int(parts[1]), int(parts[2]))
                sections[coords] = child
                child["mtk:section_pos"] = list(coords)
            except Exception:
                pass
    return sections


def sync_child_section_names(root_obj: bpy.types.Object) -> None:
    """Propagate root object name prefix to all child section objects and meshes when root is renamed."""
    if not root_obj:
        return
    root_prefix = root_obj.name
    root_obj["mtk:last_name"] = root_prefix
    for child in list(root_obj.children):
        pos = child.get("mtk:section_pos")
        if pos is not None and len(pos) == 3:
            sx, sy, sz = int(pos[0]), int(pos[1]), int(pos[2])
        elif "_Section_" in child.name:
            try:
                parts = child.name.split("_Section_")[-1].split("_")
                sx, sy, sz = int(parts[0]), int(parts[1]), int(parts[2])
                child["mtk:section_pos"] = [sx, sy, sz]
            except Exception:
                continue
        else:
            continue

        target_obj_name = get_section_object_name(root_prefix, sx, sy, sz)
        target_mesh_name = get_section_mesh_name(root_prefix, sx, sy, sz)
        if child.name != target_obj_name:
            child.name = target_obj_name
        if child.data and child.data.name != target_mesh_name:
            child.data.name = target_mesh_name


def _safe_remove_section_object(obj: Optional[bpy.types.Object], mesh: Optional[bpy.types.Mesh] = None) -> None:
    """Safely remove a section object and its mesh datablock, handling Edit Mode if active."""
    if not obj:
        return
    try:
        if getattr(obj, "mode", None) == 'EDIT':
            if hasattr(bpy.context, "view_layer") and getattr(bpy.context.view_layer.objects, "active", None) == obj:
                try:
                    bpy.ops.object.mode_set(mode='OBJECT')
                except Exception:
                    pass
        if obj.name in bpy.data.objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        if mesh and getattr(mesh, "name", None) in bpy.data.meshes:
            bpy.data.meshes.remove(mesh, do_unlink=True)
    except Exception as e:
        logger.debug(f"Safe remove section object error: {e}")


def _get_mesh_vertex_and_face_count(mesh: Optional[bpy.types.Mesh]) -> tuple[int, int]:
    """Return (vertex_count, face_count) correctly in either Object Mode or active Edit Mode."""
    if not mesh:
        return 0, 0
    if getattr(mesh, "is_editmode", False):
        try:
            bm = bmesh.from_edit_mesh(mesh)
            return len(bm.verts), len(bm.faces)
        except Exception:
            pass
    return len(mesh.vertices), len(mesh.polygons)


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
    Supports both Object Mode and Edit Mode seamlessly.
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

    is_edit = getattr(mesh, "is_editmode", False)
    if is_edit:
        bm = bmesh.from_edit_mesh(mesh)
        bm.clear()
    else:
        bm = bmesh.new()

    try:
        uv_layer = bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap")
        color_layer = bm.loops.layers.color.get("Color") or bm.loops.layers.color.new("Color")

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
            voxel_storage=storage,
        )

        # 5. Optional in-engine vertex welding for optimal topology
        if weld_vertices and len(bm.verts) > 0:
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)

        # 6. Push BMesh data back to Blender Mesh
        if is_edit:
            bmesh.update_edit_mesh(mesh, loop_triangles=True, destructive=True)
        else:
            mesh.clear_geometry()
            bm.to_mesh(mesh)
            mesh.update()
    finally:
        if not is_edit:
            bm.free()

    vertex_count = len(mesh.vertices) if not is_edit else len(bm.verts)
    face_count = len(mesh.polygons) if not is_edit else len(bm.faces)

    return WorldMeshBuildResult(
        world_obj=obj,
        vertex_count=vertex_count,
        face_count=face_count,
        cubes_count=cubes_count,
        props_count=props_count,
        fluids_count=fluids_count,
    )


def build_single_section_mesh(
    context: bpy.types.Context,
    storage: VoxelStorage,
    sx: int, sy: int, sz: int,
    root_obj: bpy.types.Object,
    mat_manager: Optional[LiveSyncMaterialManager] = None,
    baker: Optional[Any] = None,
    state_cache: Optional[dict[str, CachedStateMeta]] = None,
    existing_sections: Optional[dict[tuple[int, int, int], bpy.types.Object]] = None,
    origin_centered: bool = True,
    weld_vertices: bool = True,
) -> Optional[bpy.types.Object]:
    """
    Constructs or updates the 3D polygon mesh for a single 16x16x16 chunk section.
    Efficiently mounts under root_obj, syncs material slots, and writes geometry.
    """
    baker = baker or get_shared_state_baker()
    mat_manager = mat_manager or get_shared_material_manager(world_obj=root_obj, atlas_params=None)
    root_prefix = root_obj.name
    min_x, min_y, min_z = storage.min_x, storage.min_y, storage.min_z
    size_x, size_y, size_z = storage.size_x, storage.size_y, storage.size_z
    half_x = size_x / 2.0 - 0.5
    half_z = size_z / 2.0 - 0.5

    sec_blocks = storage.get_section_blocks(sx, sy, sz)
    sec_obj_name = get_section_object_name(root_prefix, sx, sy, sz)
    sec_mesh_name = get_section_mesh_name(root_prefix, sx, sy, sz)

    if existing_sections is None:
        existing_sections = find_root_section_children(root_obj)

    # If section is empty or only air, remove object if exists
    if not sec_blocks:
        storage._known_empty_sections.add((sx, sy, sz))
        sec_obj = existing_sections.get((sx, sy, sz)) or bpy.data.objects.get(sec_obj_name)
        if sec_obj:
            _safe_remove_section_object(sec_obj, sec_obj.data)
            existing_sections.pop((sx, sy, sz), None)
        return None

    if state_cache is None:
        state_cache = {}

    for s in sec_blocks.values():
        if s not in state_cache:
            state_cache[s] = get_cached_state_meta(s, mat_manager, baker)

    if all(state_cache.get(s) and state_cache[s].is_air for s in sec_blocks.values()):
        storage._known_empty_sections.add((sx, sy, sz))
        sec_obj = existing_sections.get((sx, sy, sz)) or bpy.data.objects.get(sec_obj_name)
        if sec_obj:
            _safe_remove_section_object(sec_obj, sec_obj.data)
            existing_sections.pop((sx, sy, sz), None)
        return None

    if (sx, sy, sz) in existing_sections:
        sec_obj = existing_sections[(sx, sy, sz)]
        sec_mesh = sec_obj.data
    elif sec_obj_name in bpy.data.objects:
        sec_obj = bpy.data.objects[sec_obj_name]
        sec_mesh = sec_obj.data
        existing_sections[(sx, sy, sz)] = sec_obj
    else:
        sec_mesh = bpy.data.meshes.new(sec_mesh_name)
        sec_obj = bpy.data.objects.new(sec_obj_name, sec_mesh)
        sec_obj.location = (0.0, 0.0, 0.0)
        sec_obj.parent = root_obj
        col = getattr(context, "collection", None) if context else None
        if col is None and hasattr(bpy, "context") and hasattr(bpy.context, "scene") and hasattr(bpy.context.scene, "collection"):
            col = bpy.context.scene.collection
        if col:
            col.objects.link(sec_obj)
        existing_sections[(sx, sy, sz)] = sec_obj

    sec_obj["mtk:section_crc"] = str(storage.section_crc_map.get((sx, sy, sz), 0))
    sec_obj["mtk:section_pos"] = [sx, sy, sz]

    # Keep section slot indices identical to the root material manager.
    sync_section_material_slots(sec_obj, mat_manager)

    # Construct section BMesh (handles active Edit Mode or Object Mode)
    is_edit = getattr(sec_mesh, "is_editmode", False)
    if is_edit:
        bm = bmesh.from_edit_mesh(sec_mesh)
        bm.clear()
    else:
        bm = bmesh.new()

    try:
        uv_layer = bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap")
        color_layer = bm.loops.layers.color.get("Color") or bm.loops.layers.color.new("Color")

        generate_voxel_geometry(
            bm=bm,
            voxel_items=list(sec_blocks.items()),
            block_map=storage.block_map,
            state_cache=state_cache,
            uv_layer=uv_layer,
            color_layer=color_layer,
            origin_centered=origin_centered,
            min_x=min_x, min_y=min_y, min_z=min_z,
            half_x=half_x, half_z=half_z,
            mat_manager=mat_manager,
            baker=baker,
            voxel_storage=storage,
        )

        if weld_vertices and len(bm.verts) > 0:
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)

        if is_edit:
            bmesh.update_edit_mesh(sec_mesh, loop_triangles=True, destructive=True)
        else:
            sec_mesh.clear_geometry()
            bm.to_mesh(sec_mesh)
            sec_mesh.update()
    finally:
        if not is_edit:
            bm.free()

    # If after culling this section has 0 polygons, track in _known_empty_sections
    poly_count = len(sec_mesh.polygons) if not is_edit else len(bm.faces)
    if poly_count == 0:
        storage._known_empty_sections.add((sx, sy, sz))
    else:
        storage._known_empty_sections.discard((sx, sy, sz))

    slots_changed = sync_section_material_slots(sec_obj, mat_manager)
    if slots_changed:
        rebind_mesh_material_indices(sec_mesh, mat_manager)

    if not is_edit:
        sec_mesh.update()

    return sec_obj


def sync_world_mesh(
    context: bpy.types.Context,
    storage: VoxelStorage,
    atlas_params: Optional[dict[str, Any]] = None,
    force_full_rebuild: bool = False,
    origin_centered: bool = True,
    weld_vertices: bool = True,
    target_obj: Optional[bpy.types.Object] = None,
    root_name: Optional[str] = None,
) -> WorldMeshBuildResult:
    """
    High-performance incremental section-based World Mesh synchronizer.
    Maintains 16x16x16 child section objects ({root_name}_Section_<x>_<y>_<z>) under Yefira World Empty root.
    Only regenerates dirty sections and boundary neighbors, delivering sub-millisecond real-time sync.
    Supports both Object Mode and active Edit Mode seamlessly.
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

    # 1. Acquire root Empty container object
    root_obj = get_or_create_world_root(context, root_name=root_name, target_obj=target_obj)
    sync_child_section_names(root_obj)
    root_prefix = root_obj.name

    # 2. Material Manager for chunk materials (cached singleton)
    mat_manager = get_shared_material_manager(world_obj=root_obj, atlas_params=atlas_params)

    # 3. Precompute unique block states
    unique_states = set(storage.get_unique_states())
    state_cache: dict[str, CachedStateMeta] = {
        s: get_cached_state_meta(s, mat_manager, baker) for s in unique_states
    }

    # 4. Map existing child section objects
    existing_sections = find_root_section_children(root_obj)
    all_sections = storage.get_all_sections()
    if force_full_rebuild or not existing_sections:
        target_sections = all_sections
    else:
        target_sections = storage.get_dirty_sections().intersection(all_sections)

    # Prune any section objects whose sections no longer exist or contain only air
    for coords, child in list(existing_sections.items()):
        if coords not in all_sections:
            _safe_remove_section_object(child, child.data)
            existing_sections.pop(coords, None)

    # 5. Build/Update target sections
    for (sx, sy, sz) in target_sections:
        build_single_section_mesh(
            context=context,
            storage=storage,
            sx=sx, sy=sy, sz=sz,
            root_obj=root_obj,
            mat_manager=mat_manager,
            baker=baker,
            state_cache=state_cache,
            existing_sections=existing_sections,
            origin_centered=origin_centered,
            weld_vertices=weld_vertices,
        )

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
            v_cnt, f_cnt = _get_mesh_vertex_and_face_count(child.data)
            total_verts += v_cnt
            total_faces += f_cnt

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
    target_obj: Optional[bpy.types.Object] = None,
    root_name: Optional[str] = None,
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

    # 1. Acquire root Empty container object
    root_obj = get_or_create_world_root(context, root_name=root_name, target_obj=target_obj)
    sync_child_section_names(root_obj)
    root_prefix = root_obj.name

    # 2. Material Manager for chunk materials (cached singleton)
    mat_manager = get_shared_material_manager(world_obj=root_obj, atlas_params=atlas_params)

    # 3. Find all blocks to update: changed blocks + neighbors (including 3x3 diagonal window for fluids)
    blocks_to_update: set[tuple[int, int, int]] = set()
    previous_states = previous_states or {}
    for abs_x, abs_y, abs_z, _state in changes:
        blocks_to_update.add((abs_x, abs_y, abs_z))
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
    existing_sections = find_root_section_children(root_obj)
    has_section_children = bool(existing_sections)

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
            sec_obj_name = get_section_object_name(root_prefix, sx, sy, sz)
            sec_mesh_name = get_section_mesh_name(root_prefix, sx, sy, sz)

            sec_all_blocks = storage.get_section_blocks(sx, sy, sz)
            has_solid_blocks = bool(sec_all_blocks and any(
                (_GLOBAL_STATE_META_CACHE.get(s) and not _GLOBAL_STATE_META_CACHE[s].is_air)
                or (storage.get_block(px, py, pz) and not storage.get_block(px, py, pz).startswith("minecraft:air"))
                for (px, py, pz), s in sec_all_blocks.items()
            ))

            sec_obj = existing_sections.get((sx, sy, sz)) or bpy.data.objects.get(sec_obj_name)
            if not sec_obj:
                if not has_solid_blocks:
                    continue
                sec_mesh = bpy.data.meshes.new(sec_mesh_name)
                sec_obj = bpy.data.objects.new(sec_obj_name, sec_mesh)
                sec_obj.location = (0.0, 0.0, 0.0)
                sec_obj.parent = root_obj
                context.collection.objects.link(sec_obj)
                existing_sections[(sx, sy, sz)] = sec_obj

            sec_obj["mtk:section_pos"] = [sx, sy, sz]

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
            v_cnt, f_cnt = _get_mesh_vertex_and_face_count(sec_obj.data)
            if f_cnt == 0 and not has_solid_blocks:
                _safe_remove_section_object(sec_obj, sec_obj.data)
                existing_sections.pop((sx, sy, sz), None)

        if any_slots_changed:
            for child in root_obj.children:
                if (child.get("mtk:section_pos") is not None or "_Section_" in child.name) and child.data:
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
                v_cnt, f_cnt = _get_mesh_vertex_and_face_count(child.data)
                total_verts += v_cnt
                total_faces += f_cnt
    elif root_obj.data and isinstance(root_obj.data, bpy.types.Mesh):
        v_cnt, f_cnt = _get_mesh_vertex_and_face_count(root_obj.data)
        total_verts = v_cnt
        total_faces = f_cnt

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

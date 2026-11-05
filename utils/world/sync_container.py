"""
Live Sync Container and Hierarchy Management in Blender.

Authoritative utility module for identifying, creating, resolving, and synchronizing
the Unified World Empty Container and Section Mesh for Yefira Live Sync.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional, Tuple

import bpy

from ...bridge.mesh import inject_mesh_data
from ...bridge.world import resolve_dynamic_entity_atlases
from ..materials.builder.world_binding import ensure_world_materials
from ..point_cloud.hierarchy import ensure_voxel_child_cloud
from ..mesh.ownership import ORIGIN_SYNC_WORLD, stamp_geometry_origin
from .assembler import (
    VoxelWorldAssemblyRequest,
    assemble_voxel_world,
    safe_get_custom_prop,
    safe_set_custom_prop,
)

logger = logging.getLogger("MoziToolKit.World.SyncContainer")

DEFAULT_WORLD_OBJECT_NAME = "Yefira_World"

_safe_get_custom_prop = safe_get_custom_prop
_safe_set_custom_prop = safe_set_custom_prop


def _stamp_world_mesh_origin(mesh_obj: Any) -> None:
    """Mark a Live Sync world mesh as MTK-generated (not an external import)."""
    stamp_geometry_origin(mesh_obj, ORIGIN_SYNC_WORLD, overwrite=True)


def is_yefira_root_object(obj: Optional[Any]) -> bool:
    """Identify whether a Blender object is a root Yefira live sync Empty container."""
    if not obj:
        return False
    obj_type = getattr(obj, "type", "")
    if obj_type == "EMPTY":
        c_type = safe_get_custom_prop(obj, "mtk:container_type")
        if c_type and c_type != "SYNC":
            return False
        if safe_get_custom_prop(obj, "mtk:is_yefira_world"):
            return True
        if safe_get_custom_prop(obj, "mtk:is_container") and c_type == "SYNC":
            return True
        obj_name = getattr(obj, "name", "")
        if obj_name == DEFAULT_WORLD_OBJECT_NAME or obj_name.startswith("Yefira_World"):
            return True
        for c in getattr(obj, "children", []):
            if safe_get_custom_prop(c, "mtk:is_yefira_mesh"):
                return True
    return False


def is_yefira_child_object(obj: Optional[Any]) -> bool:
    """Identify whether a Blender object is a child section or point cloud of a Yefira container."""
    if not obj:
        return False
    if (
        safe_get_custom_prop(obj, "mtk:is_yefira_mesh")
        or safe_get_custom_prop(obj, "mtk:is_section_mesh")
        or safe_get_custom_prop(obj, "mtk_is_voxel_cloud")
        or safe_get_custom_prop(obj, "mtk:is_voxel_cloud")
    ):
        return True
    parent = getattr(obj, "parent", None)
    if parent and is_yefira_root_object(parent):
        return True
    return False


def is_yefira_world_object(obj: Optional[Any]) -> bool:
    """Checks if an object is tagged as or belongs to the Yefira Live Sync world container."""
    if not obj:
        return False
    return (
        is_yefira_root_object(obj)
        or is_yefira_child_object(obj)
        or bool(safe_get_custom_prop(obj, "mtk:is_yefira_world"))
        or getattr(obj, "name", "") == DEFAULT_WORLD_OBJECT_NAME
    )


def resolve_world_root_object(obj: Optional[Any]) -> Optional[Any]:
    """
    Given any object (root empty, child mesh, or point cloud), resolves up the hierarchy
    to the topmost Yefira World Empty root container.
    """
    if not obj:
        return None

    # 1. Climb up parent chain looking for an Empty root container
    curr = obj
    depth = 0
    while curr is not None and depth < 256:
        if is_yefira_root_object(curr):
            return curr
        curr = getattr(curr, "parent", None)
        depth += 1

    # 2. If object is a child mesh named <Root>_Mesh, try to find root by name
    obj_name = getattr(obj, "name", "")
    if obj_name.endswith("_Mesh"):
        root_name = obj_name[:-5]
        if hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
            candidate = bpy.data.objects.get(root_name) if hasattr(bpy.data.objects, "get") else None
            if candidate and is_yefira_root_object(candidate):
                return candidate

    # 3. Fallback: if object itself is tagged as world container
    if is_yefira_root_object(obj):
        return obj
    if bool(safe_get_custom_prop(obj, "mtk:is_yefira_world")):
        return obj

    return None


find_root_container = resolve_world_root_object


def find_world_mesh_child(root_container: Optional[Any]) -> Optional[Any]:
    """Finds the primary world mesh child under the given root container."""
    if not root_container:
        return None
    for child in getattr(root_container, "children", []):
        if getattr(child, "type", "") == "MESH" and (
            safe_get_custom_prop(child, "mtk:is_yefira_mesh")
            or not (
                safe_get_custom_prop(child, "mtk_is_voxel_cloud")
                or safe_get_custom_prop(child, "mtk:is_voxel_cloud")
            )
        ):
            return child
    return None


def find_voxel_cloud_child(root_container: Optional[Any]) -> Optional[Any]:
    """Finds the companion point cloud child under the given root container."""
    if not root_container:
        return None
    for child in getattr(root_container, "children", []):
        if (
            safe_get_custom_prop(child, "mtk_is_voxel_cloud")
            or safe_get_custom_prop(child, "mtk:is_voxel_cloud")
            or getattr(child, "name", "").endswith("_VoxelCloud")
        ):
            return child
    return None


def get_or_create_world_container(
    context: Optional[Any] = None,
    target_name: str = DEFAULT_WORLD_OBJECT_NAME,
) -> Any:
    """Acquires or creates the root Empty container for Yefira Live Sync."""
    ctx = context or getattr(bpy, "context", None)

    active = getattr(ctx, "active_object", None) if ctx else None
    resolved = resolve_world_root_object(active)
    if resolved and getattr(resolved, "type", "") == "EMPTY":
        return resolved

    if hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
        if target_name in bpy.data.objects:
            obj = bpy.data.objects[target_name]
            if getattr(obj, "type", "") == "EMPTY":
                safe_set_custom_prop(obj, "mtk:is_yefira_world", True)
                safe_set_custom_prop(obj, "mtk:is_container", True)
                return obj

        if target_name == DEFAULT_WORLD_OBJECT_NAME:
            objs = bpy.data.objects.values() if hasattr(bpy.data.objects, "values") else bpy.data.objects
            for obj in objs:
                if isinstance(obj, str):
                    obj = bpy.data.objects.get(obj) if hasattr(bpy.data.objects, "get") else None
                if obj and is_yefira_root_object(obj):
                    return obj

    root_obj = bpy.data.objects.new(target_name, None)
    if hasattr(root_obj, "empty_display_type"):
        root_obj.empty_display_type = "PLAIN_AXES"
    if hasattr(root_obj, "empty_display_size"):
        root_obj.empty_display_size = 1.0
    safe_set_custom_prop(root_obj, "mtk:is_yefira_world", True)
    safe_set_custom_prop(root_obj, "mtk:is_container", True)
    safe_set_custom_prop(root_obj, "mtk:container_type", "SYNC")
    safe_set_custom_prop(root_obj, "mtk:container_id", uuid.uuid4().hex)
    safe_set_custom_prop(root_obj, "mtk:last_name", getattr(root_obj, "name", target_name))
    if hasattr(root_obj, "location"):
        root_obj.location = (0.0, 0.0, 0.0)

    col = getattr(ctx, "collection", None) if ctx else None
    if col is None and hasattr(bpy.context, "scene") and hasattr(bpy.context.scene, "collection"):
        col = bpy.context.scene.collection
    if col and hasattr(col, "objects") and hasattr(col.objects, "link"):
        try:
            col.objects.link(root_obj)
        except Exception:
            pass

    logger.info("Created root Empty world container: %s", getattr(root_obj, "name", target_name))
    return root_obj


def get_or_create_world_mesh_object(
    context: Optional[Any] = None,
    target_name: str = DEFAULT_WORLD_OBJECT_NAME,
    root_container: Optional[Any] = None,
) -> Any:
    """Acquires or creates the single unified mesh object representing the synchronized world."""
    ctx = context or getattr(bpy, "context", None)

    active = getattr(ctx, "active_object", None) if ctx else None
    if active and active.type == "MESH" and is_yefira_world_object(active):
        _stamp_world_mesh_origin(active)
        return active

    if root_container is None:
        root_container = get_or_create_world_container(context, target_name)

    if getattr(root_container, "type", "") == "MESH":
        safe_set_custom_prop(root_container, "mtk:is_yefira_world", True)
        safe_set_custom_prop(root_container, "mtk:is_yefira_mesh", True)
        _stamp_world_mesh_origin(root_container)
        return root_container

    existing_mesh = find_world_mesh_child(root_container)
    if existing_mesh:
        _stamp_world_mesh_origin(existing_mesh)
        return existing_mesh

    root_name = getattr(root_container, "name", target_name)
    mesh_child_name = f"{root_name}_Mesh"
    if hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
        if mesh_child_name in bpy.data.objects and getattr(bpy.data.objects[mesh_child_name], "type", "") == "MESH":
            mesh_obj = bpy.data.objects[mesh_child_name]
            safe_set_custom_prop(mesh_obj, "mtk:is_yefira_world", True)
            safe_set_custom_prop(mesh_obj, "mtk:is_yefira_mesh", True)
            if getattr(mesh_obj, "parent", None) != root_container and hasattr(mesh_obj, "parent"):
                mesh_obj.parent = root_container
            _stamp_world_mesh_origin(mesh_obj)
            return mesh_obj

    mesh = bpy.data.meshes.new(mesh_child_name)
    world_obj = bpy.data.objects.new(mesh_child_name, mesh)
    safe_set_custom_prop(world_obj, "mtk:is_yefira_world", True)
    safe_set_custom_prop(world_obj, "mtk:is_yefira_mesh", True)
    if hasattr(world_obj, "parent"):
        world_obj.parent = root_container
    if hasattr(world_obj, "location"):
        world_obj.location = (0.0, 0.0, 0.0)

    target_coll = root_container.users_collection[0] if getattr(root_container, "users_collection", None) else None
    if target_coll is None:
        col = getattr(ctx, "collection", None) if ctx else None
        if col is None and hasattr(bpy.context, "scene") and hasattr(bpy.context.scene, "collection"):
            col = bpy.context.scene.collection
        target_coll = col
    if target_coll and hasattr(target_coll, "objects") and hasattr(target_coll.objects, "link"):
        try:
            target_coll.objects.link(world_obj)
        except Exception:
            pass

    _stamp_world_mesh_origin(world_obj)
    logger.info("Created child world mesh object: %s under container: %s", getattr(world_obj, "name", mesh_child_name), root_name)
    return world_obj


def sync_container_child_names(root_obj: Any) -> None:
    """When root_obj is renamed, synchronize child mesh and point cloud names."""
    if not root_obj:
        return
    prefix = getattr(root_obj, "name", "")
    safe_set_custom_prop(root_obj, "mtk:last_name", prefix)
    for child in getattr(root_obj, "children", []):
        if safe_get_custom_prop(child, "mtk:is_yefira_mesh") or (
            getattr(child, "type", "") == "MESH"
            and not (
                safe_get_custom_prop(child, "mtk_is_voxel_cloud")
                or safe_get_custom_prop(child, "mtk:is_voxel_cloud")
            )
        ):
            target_name = f"{prefix}_Mesh"
            if child.name != target_name:
                child.name = target_name
            if child.data and child.data.name != f"Mesh_{prefix}":
                child.data.name = f"Mesh_{prefix}"
        elif (
            safe_get_custom_prop(child, "mtk_is_voxel_cloud")
            or safe_get_custom_prop(child, "mtk:is_voxel_cloud")
            or getattr(child, "name", "").endswith("_VoxelCloud")
        ):
            target_name = f"{prefix}_VoxelCloud"
            if child.name != target_name:
                child.name = target_name


def update_world_mesh(
    world_obj: Any,
    mesh_data: Any,
    skip_string_attributes: bool = False,
    storage: Optional[Any] = None,
    sync_point_cloud: bool = False,
    atlas: Optional[Any] = None,
    session: Optional[Any] = None,
    dynamic_entity_atlases: Optional[Any] = None,
) -> Tuple[int, int]:
    """Injects processed geometry buffer into world mesh and syncs companion point cloud."""
    if not world_obj or getattr(world_obj, "type", "") != "MESH":
        return 0, 0

    root_container = resolve_world_root_object(world_obj)
    container_id = safe_get_custom_prop(root_container, "mtk:container_id") if root_container else None

    if dynamic_entity_atlases is None:
        dynamic_entity_atlases = resolve_dynamic_entity_atlases(mesh_data, session)

    def mat_binder(m_obj: Any) -> Any:
        used_chunk_ids = mesh_data.used_materials() if hasattr(mesh_data, "used_materials") else None
        ensure_world_materials(
            m_obj,
            atlas=atlas,
            used_chunk_ids=used_chunk_ids,
            dynamic_entity_atlases=dynamic_entity_atlases,
        )

    req = VoxelWorldAssemblyRequest(
        container_type="SYNC",
        root_name=getattr(root_container, "name", getattr(world_obj, "name", DEFAULT_WORLD_OBJECT_NAME)),
        mesh_data=mesh_data,
        storage=storage,
        container_id=container_id,
        atlas=atlas,
        dynamic_entity_atlases=dynamic_entity_atlases,
        origin_centered=True,
        reuse_existing=True,
        target_root=root_container,
        target_mesh=world_obj,
        geometry_origin=ORIGIN_SYNC_WORLD,
        skip_string_attributes=skip_string_attributes,
        custom_injector=inject_mesh_data,
        custom_material_binder=mat_binder,
        custom_cloud_ensurer=ensure_voxel_child_cloud,
        clean_unused_material_slots=False,
        sync_point_cloud=sync_point_cloud,
    )

    res = assemble_voxel_world(req)

    from ..materials.biome.updater import mark_world_biome
    if mark_world_biome is not None and storage is not None:
        aliases = []
        if root_container is not None and root_container is not world_obj:
            aliases.append(getattr(root_container, "name", ""))
            aliases.append(safe_get_custom_prop(root_container, "mtk:container_id", ""))
            mark_world_biome(root_container, storage)
        mark_world_biome(world_obj, storage, aliases=aliases)

    try:
        from ...bridge.diagnostics import append_stage_to_last_profile
        used_chunk_ids = mesh_data.used_materials() if hasattr(mesh_data, "used_materials") else None
        append_stage_to_last_profile("blender_mesh_injection", res.get("inject_ms", 0.0), getattr(mesh_data, "vertex_count", None))
        append_stage_to_last_profile("blender_material_binding", res.get("materials_ms", 0.0), len(used_chunk_ids) if used_chunk_ids else None)
    except Exception:
        pass

    mesh = getattr(world_obj, "data", None)
    v_count = len(mesh.vertices) if mesh and hasattr(mesh, "vertices") else 0
    f_count = len(mesh.polygons) if mesh and hasattr(mesh, "polygons") else 0
    return v_count, f_count

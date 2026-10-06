"""
Hierarchical management for the Unified World Empty Container and Section Mesh in Blender.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional, Tuple
import bpy

try:
    from ...bridge.mesh import inject_mesh_data
    from ...bridge.world import ensure_world_materials
    from ...bridge.point_cloud import ensure_voxel_child_cloud
except (ImportError, ValueError):
    from bridge.mesh import inject_mesh_data
    from bridge.world import ensure_world_materials
    from bridge.point_cloud import ensure_voxel_child_cloud

logger = logging.getLogger("MoziToolKit.Sync.Hierarchy")

DEFAULT_WORLD_OBJECT_NAME = "Yefira_World"


def _safe_set_custom_prop(obj: Any, key: str, val: Any) -> None:
    if obj is None:
        return
    try:
        obj[key] = val
    except (TypeError, AttributeError, KeyError):
        try:
            setattr(obj, key, val)
        except Exception:
            pass


def _safe_get_custom_prop(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    try:
        if hasattr(obj, "get"):
            return obj.get(key, default)
        return getattr(obj, key, default)
    except Exception:
        return default


def is_yefira_root_object(obj: Optional[bpy.types.Object]) -> bool:
    """Identify whether a Blender object is a root Yefira live sync Empty container."""
    if not obj:
        return False
    obj_type = getattr(obj, "type", "")
    if obj_type == 'EMPTY':
        if _safe_get_custom_prop(obj, "mtk:is_yefira_world") or _safe_get_custom_prop(obj, "mtk:is_container"):
            return True
        obj_name = getattr(obj, "name", "")
        if obj_name == DEFAULT_WORLD_OBJECT_NAME or obj_name.startswith("Yefira_World"):
            return True
        for c in getattr(obj, "children", []):
            if _safe_get_custom_prop(c, "mtk:is_yefira_mesh") or _safe_get_custom_prop(c, "mtk_is_voxel_cloud"):
                return True
    return False


def is_yefira_child_object(obj: Optional[bpy.types.Object]) -> bool:
    """Identify whether a Blender object is a child section or point cloud of a Yefira container."""
    if not obj:
        return False
    if _safe_get_custom_prop(obj, "mtk:is_yefira_mesh") or _safe_get_custom_prop(obj, "mtk_is_voxel_cloud"):
        return True
    parent = getattr(obj, "parent", None)
    if parent and is_yefira_root_object(parent):
        return True
    return False


def is_yefira_world_object(obj: Optional[bpy.types.Object]) -> bool:
    """Checks if an object is tagged as or belongs to the Yefira Live Sync world container."""
    if not obj:
        return False
    return is_yefira_root_object(obj) or is_yefira_child_object(obj) or bool(_safe_get_custom_prop(obj, "mtk:is_yefira_world")) or getattr(obj, "name", "") == DEFAULT_WORLD_OBJECT_NAME


def resolve_world_root_object(obj: Optional[bpy.types.Object]) -> Optional[bpy.types.Object]:
    """
    Given any object (root empty, child mesh, or point cloud), resolves up the hierarchy
    to the topmost Yefira World Empty root container.
    """
    if not obj:
        return None

    # 1. Climb up parent chain looking for an Empty root container
    curr = obj
    while curr:
        if is_yefira_root_object(curr):
            return curr
        curr = getattr(curr, "parent", None)

    # 2. If object is a child mesh named <Root>_Mesh, try to find root by name
    obj_name = getattr(obj, "name", "")
    if obj_name.endswith("_Mesh"):
        root_name = obj_name[:-5]
        if hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
            candidate = bpy.data.objects.get(root_name) if hasattr(bpy.data.objects, "get") else None
            if candidate and is_yefira_root_object(candidate):
                return candidate

    # 3. Fallback: if object itself is tagged as world container (even if Mesh in legacy mode)
    if is_yefira_root_object(obj):
        return obj
    if bool(_safe_get_custom_prop(obj, "mtk:is_yefira_world")):
        return obj

    return None


find_root_container = resolve_world_root_object


def find_world_mesh_child(root_container: Optional[bpy.types.Object]) -> Optional[bpy.types.Object]:
    """Finds the primary world mesh child under the given root container."""
    if not root_container:
        return None
    for child in getattr(root_container, "children", []):
        if getattr(child, "type", "") == "MESH" and (_safe_get_custom_prop(child, "mtk:is_yefira_mesh") or not _safe_get_custom_prop(child, "mtk_is_voxel_cloud")):
            return child
    return None


def find_voxel_cloud_child(root_container: Optional[bpy.types.Object]) -> Optional[bpy.types.Object]:
    """Finds the companion point cloud child under the given root container."""
    if not root_container:
        return None
    for child in getattr(root_container, "children", []):
        if _safe_get_custom_prop(child, "mtk_is_voxel_cloud") or getattr(child, "name", "").endswith("_VoxelCloud"):
            return child
    return None


def get_or_create_world_container(
    context: Optional[bpy.types.Context] = None,
    target_name: str = DEFAULT_WORLD_OBJECT_NAME,
) -> bpy.types.Object:
    """
    Acquires or creates the root Empty container for Yefira Live Sync.
    """
    ctx = context or getattr(bpy, "context", None)

    # 1. Check active object if it is or belongs to a valid Yefira root container
    active = getattr(ctx, "active_object", None) if ctx else None
    resolved = resolve_world_root_object(active)
    if resolved and getattr(resolved, "type", "") == 'EMPTY':
        return resolved

    # 2. Check by exact name in bpy.data.objects
    if hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
        if target_name in bpy.data.objects:
            obj = bpy.data.objects[target_name]
            if getattr(obj, "type", "") == 'EMPTY':
                _safe_set_custom_prop(obj, "mtk:is_yefira_world", True)
                _safe_set_custom_prop(obj, "mtk:is_container", True)
                return obj

        # 3. Check any existing Empty tagged with mtk:is_yefira_world
        objs = bpy.data.objects.values() if hasattr(bpy.data.objects, "values") else bpy.data.objects
        for obj in objs:
            if isinstance(obj, str):
                obj = bpy.data.objects.get(obj) if hasattr(bpy.data.objects, "get") else None
            if obj and is_yefira_root_object(obj):
                return obj

    # 4. Create new Empty root container
    root_obj = bpy.data.objects.new(target_name, None)
    if hasattr(root_obj, "empty_display_type"):
        root_obj.empty_display_type = 'PLAIN_AXES'
    if hasattr(root_obj, "empty_display_size"):
        root_obj.empty_display_size = 1.0
    _safe_set_custom_prop(root_obj, "mtk:is_yefira_world", True)
    _safe_set_custom_prop(root_obj, "mtk:is_container", True)
    _safe_set_custom_prop(root_obj, "mtk:container_type", "SYNC")
    _safe_set_custom_prop(root_obj, "mtk:container_id", uuid.uuid4().hex)
    _safe_set_custom_prop(root_obj, "mtk:last_name", getattr(root_obj, "name", target_name))
    if hasattr(root_obj, "location"):
        root_obj.location = (0.0, 0.0, 0.0)

    # Link to active collection
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
    context: Optional[bpy.types.Context] = None,
    target_name: str = DEFAULT_WORLD_OBJECT_NAME,
    root_container: Optional[bpy.types.Object] = None,
) -> bpy.types.Object:
    """
    Acquires or creates the single unified mesh object representing the synchronized world.
    Ensures it is nested under an Empty root container as a child.
    """
    ctx = context or getattr(bpy, "context", None)

    # 1. Check active object if it is already a valid mesh
    active = getattr(ctx, "active_object", None) if ctx else None
    if active and active.type == "MESH" and is_yefira_world_object(active):
        return active

    # 2. Acquire or create root container
    if root_container is None:
        root_container = get_or_create_world_container(context, target_name)

    # In legacy or mock environments where root_container is already a Mesh
    if getattr(root_container, "type", "") == "MESH":
        _safe_set_custom_prop(root_container, "mtk:is_yefira_world", True)
        _safe_set_custom_prop(root_container, "mtk:is_yefira_mesh", True)
        return root_container

    # 3. Check if root container already has a child mesh
    existing_mesh = find_world_mesh_child(root_container)
    if existing_mesh:
        return existing_mesh

    # 4. Check if a mesh named <root>_Mesh or target_name already exists
    root_name = getattr(root_container, "name", target_name)
    mesh_child_name = f"{root_name}_Mesh"
    if hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
        if mesh_child_name in bpy.data.objects and getattr(bpy.data.objects[mesh_child_name], "type", "") == "MESH":
            mesh_obj = bpy.data.objects[mesh_child_name]
            _safe_set_custom_prop(mesh_obj, "mtk:is_yefira_world", True)
            _safe_set_custom_prop(mesh_obj, "mtk:is_yefira_mesh", True)
            if getattr(mesh_obj, "parent", None) != root_container and hasattr(mesh_obj, "parent"):
                mesh_obj.parent = root_container
            return mesh_obj

    # 5. Create new child mesh object
    mesh = bpy.data.meshes.new(mesh_child_name)
    world_obj = bpy.data.objects.new(mesh_child_name, mesh)
    _safe_set_custom_prop(world_obj, "mtk:is_yefira_world", True)
    _safe_set_custom_prop(world_obj, "mtk:is_yefira_mesh", True)
    if hasattr(world_obj, "parent"):
        world_obj.parent = root_container
    if hasattr(world_obj, "location"):
        world_obj.location = (0.0, 0.0, 0.0)

    # Link to same collection as root container
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

    logger.info("Created child world mesh object: %s under container: %s", getattr(world_obj, "name", mesh_child_name), root_name)
    return world_obj


def sync_container_child_names(root_obj: bpy.types.Object) -> None:
    """When root_obj is renamed, synchronize child mesh and point cloud names."""
    if not root_obj:
        return
    prefix = root_obj.name
    root_obj["mtk:last_name"] = prefix
    for child in root_obj.children:
        if child.get("mtk:is_yefira_mesh") or (child.type == "MESH" and not child.get("mtk_is_voxel_cloud")):
            target_name = f"{prefix}_Mesh"
            if child.name != target_name:
                child.name = target_name
            if child.data and child.data.name != f"Mesh_{prefix}":
                child.data.name = f"Mesh_{prefix}"
        elif child.get("mtk_is_voxel_cloud") or child.name.endswith("_VoxelCloud"):
            target_name = f"{prefix}_VoxelCloud"
            if child.name != target_name:
                child.name = target_name


def update_world_mesh(
    world_obj: bpy.types.Object,
    mesh_data: Any,
    skip_string_attributes: bool = False,
    storage: Optional[Any] = None,
    sync_point_cloud: bool = False,
) -> Tuple[int, int]:
    """
    Injects processed geometry buffer into the single world mesh object using high-throughput
    zero-copy bridge methods, and optionally synchronizes unculled voxel storage into companion point cloud.
    Returns (vertex_count, face_count).
    """
    if not world_obj or world_obj.type != "MESH":
        return 0, 0

    mesh = world_obj.data
    inject_mesh_data(
        mesh,
        mesh_data,
        update_topology=True,
        update_normals=True,
        skip_string_attributes=skip_string_attributes,
    )

    used_chunk_ids = mesh_data.used_materials() if hasattr(mesh_data, "used_materials") else None
    ensure_world_materials(world_obj, used_chunk_ids=used_chunk_ids)

    # Ensure unculled voxel storage point cloud is attached under root container or world_obj as sibling
    if sync_point_cloud and storage is not None:
        try:
            root_container = resolve_world_root_object(world_obj)
            parent_target = root_container if (root_container and root_container.type == 'EMPTY') else world_obj
            cloud_obj = ensure_voxel_child_cloud(parent_target, storage=storage, origin_centered=True, initial_hidden=True)
            if cloud_obj and parent_target != world_obj:
                world_obj["mtk_voxel_cloud"] = cloud_obj.name
        except Exception as e:
            logger.warning("Failed ensuring voxel child cloud during live sync mesh update: %s", e)

    v_count = len(mesh.vertices)
    f_count = len(mesh.polygons)
    return v_count, f_count


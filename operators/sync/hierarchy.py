"""
Hierarchical management for the Single Unified World Mesh in Blender.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple
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


def is_yefira_world_object(obj: Optional[bpy.types.Object]) -> bool:
    """Checks if an object is tagged as the Yefira Live Sync world container."""
    if not obj:
        return False
    return bool(obj.get("mtk:is_yefira_world")) or obj.name == DEFAULT_WORLD_OBJECT_NAME


def get_or_create_world_mesh_object(
    context: Optional[bpy.types.Context] = None,
    target_name: str = DEFAULT_WORLD_OBJECT_NAME,
) -> bpy.types.Object:
    """
    Acquires or creates the single unified mesh object representing the synchronized world.
    """
    ctx = context or getattr(bpy, "context", None)

    # 1. Check active object if it is a valid Yefira world mesh
    active = getattr(ctx, "active_object", None) if ctx else None
    if active and is_yefira_world_object(active) and active.type == "MESH":
        return active

    # 2. Check by exact name
    if target_name in bpy.data.objects:
        obj = bpy.data.objects[target_name]
        if obj.type == "MESH":
            obj["mtk:is_yefira_world"] = True
            return obj

    # 3. Check any existing object tagged with mtk:is_yefira_world
    for obj in bpy.data.objects:
        if is_yefira_world_object(obj) and obj.type == "MESH":
            return obj

    # 4. Create new unified mesh object
    mesh = bpy.data.meshes.new(target_name)
    world_obj = bpy.data.objects.new(target_name, mesh)
    world_obj["mtk:is_yefira_world"] = True
    world_obj.location = (0.0, 0.0, 0.0)

    # Link to active collection
    col = getattr(ctx, "collection", None) if ctx else None
    if col is None and hasattr(bpy.context, "scene") and hasattr(bpy.context.scene, "collection"):
        col = bpy.context.scene.collection
    if col:
        col.objects.link(world_obj)

    logger.info(f"Created single unified world mesh object: {world_obj.name}")
    return world_obj


def update_world_mesh(
    world_obj: bpy.types.Object,
    mesh_data: Any,
    skip_string_attributes: bool = False,
    storage: Optional[Any] = None,
) -> Tuple[int, int]:
    """
    Injects processed geometry buffer into the single world mesh object using high-throughput
    zero-copy bridge methods, and synchronizes unculled voxel storage into companion point cloud.
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

    # Ensure unculled voxel storage point cloud is attached under world_obj as child
    if storage is not None:
        try:
            ensure_voxel_child_cloud(world_obj, storage=storage, origin_centered=True, initial_hidden=True)
        except Exception as e:
            logger.warning("Failed ensuring voxel child cloud during live sync mesh update: %s", e)

    v_count = len(mesh.vertices)
    f_count = len(mesh.polygons)
    return v_count, f_count

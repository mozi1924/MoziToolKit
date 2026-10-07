"""
Hierarchy and container helper utilities for Minecraft Save containers.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

try:
    import bpy
except ImportError:
    bpy = None


def is_save_root_container(obj: Optional[Any]) -> bool:
    """Checks whether an object is a root Empty container for an imported Minecraft save."""
    if not obj:
        return False
    if getattr(obj, "type", "") != 'EMPTY':
        return False
    if hasattr(obj, "get"):
        c_type = obj.get("mtk:container_type")
        if c_type == "SAVE":
            return True
        if obj.get("mozi_save_uuid") is not None:
            return True
    return False


def is_save_child_object(obj: Optional[Any]) -> bool:
    """Checks whether an object is a child mesh or cloud belonging to a Save container."""
    if not obj:
        return False
    if hasattr(obj, "get") and (obj.get("mtk:is_save_mesh") or obj.get("mozi_save_uuid")):
        return True
    parent = getattr(obj, "parent", None)
    if parent and is_save_root_container(parent):
        return True
    return False


def resolve_save_container(
    obj: Optional[Any],
) -> Tuple[Optional[Any], Optional[Any], Optional[Any]]:
    """
    Resolves (root_container, mesh_child, cloud_child) for any object
    belonging to a Minecraft Save container hierarchy.
    """
    if not obj:
        return None, None, None

    root = None
    if is_save_root_container(obj):
        root = obj
    else:
        parent = getattr(obj, "parent", None)
        if parent and is_save_root_container(parent):
            root = parent

    if root is None:
        # Fallback: check if active object itself is a standalone save mesh
        if hasattr(obj, "get") and obj.get("mozi_save_uuid"):
            return None, obj, None
        return None, None, None

    mesh_child = None
    cloud_child = None

    for ch in getattr(root, "children", []):
        ch_type = getattr(ch, "type", "")
        if ch_type == "MESH":
            is_cloud = False
            if hasattr(ch, "get"):
                is_cloud = bool(ch.get("mtk_is_voxel_cloud"))
            if not is_cloud and getattr(ch, "name", "").endswith("_VoxelCloud"):
                is_cloud = True

            if is_cloud:
                cloud_child = ch
            else:
                if mesh_child is None:
                    mesh_child = ch

    if mesh_child is None and bpy and hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
        cand = bpy.data.objects.get(f"{root.name}_Mesh")
        if cand and getattr(cand, "type", "") == "MESH":
            mesh_child = cand

    if cloud_child is None and bpy and hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
        cand = bpy.data.objects.get(f"{root.name}_VoxelCloud")
        if cand and getattr(cand, "type", "") == "MESH":
            cloud_child = cand

    return root, mesh_child, cloud_child

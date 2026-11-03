"""
MoziToolKit Scene Interchange Hierarchy and Assembly.

Orchestrates Blender scene datablocks, collections, companion point cloud synchronization,
and metadata custom properties for imported .mtkscene interchange packages.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from ...bridge.mesh import inject_mesh_data
from ..mesh.ownership import ORIGIN_SCENE, stamp_geometry_origin
from ..point_cloud.hierarchy import ensure_voxel_child_cloud
from .materials import bind_scene_materials

logger = logging.getLogger("MoziToolKit.Scene.Hierarchy")


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


def get_or_create_scene_collection() -> Optional[Any]:
    """Retrieves or creates the 'MoziToolKit_Scenes' scene collection."""
    if not HAS_BPY or not hasattr(bpy, "context") or not hasattr(bpy.context, "scene"):
        return None

    scene = bpy.context.scene
    coll_name = "MoziToolKit_Scenes"
    for coll in scene.collection.children:
        if coll.name == coll_name:
            return coll

    coll = bpy.data.collections.get(coll_name)
    if coll is None:
        coll = bpy.data.collections.new(coll_name)

    if coll.name not in [c.name for c in scene.collection.children]:
        try:
            scene.collection.children.link(coll)
        except Exception:
            pass
    return coll


def apply_imported_scene_to_blender(
    data: Dict[str, Any],
    scene_name: Optional[str] = None,
    origin_centered: bool = True,
    target_collection: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Assembles Blender objects for an imported .mtkscene package:
    - Root Empty: `[Scene] <name>`
    - Surface Mesh: `[Scene] <name>_Mesh`
    - Companion Point Cloud: `[Scene] <name>_VoxelCloud`
    - Injects mesh geometry, companion point cloud attributes, and binds materials.
    """
    if not HAS_BPY:
        return {}

    mesh_data = data.get("mesh_data")
    point_cloud = data.get("point_cloud")
    reader = data.get("reader")
    meta = data.get("metadata", {})

    s_name = scene_name or "Scene"
    root_name = f"[Scene] {s_name}"
    mesh_child_name = f"{root_name}_Mesh"

    target_coll = target_collection or get_or_create_scene_collection()
    if target_coll is None and hasattr(bpy.context, "scene"):
        target_coll = bpy.context.scene.collection

    # 1. Create or acquire root Empty container
    root_obj = None
    if hasattr(bpy, "data") and hasattr(bpy.data, "objects") and root_name in bpy.data.objects:
        cand = bpy.data.objects[root_name]
        if getattr(cand, "type", "") == "EMPTY":
            root_obj = cand

    if root_obj is None:
        root_obj = bpy.data.objects.new(root_name, None)
        try:
            root_obj.type = "EMPTY"
        except (AttributeError, TypeError):
            pass
        if hasattr(root_obj, "empty_display_type"):
            root_obj.empty_display_type = "CUBE"
        if hasattr(root_obj, "empty_display_size"):
            root_obj.empty_display_size = 1.0
        if target_coll is not None and hasattr(target_coll, "objects") and hasattr(target_coll.objects, "link"):
            try:
                target_coll.objects.link(root_obj)
            except Exception:
                pass

    _safe_set_custom_prop(root_obj, "mtk:is_scene_container", True)

    # 2. Create or acquire child surface mesh object
    mesh_obj = None
    if hasattr(bpy, "data") and hasattr(bpy.data, "objects") and mesh_child_name in bpy.data.objects:
        cand = bpy.data.objects[mesh_child_name]
        if getattr(cand, "type", "") == "MESH":
            mesh_obj = cand

    if mesh_obj is None:
        b_mesh = bpy.data.meshes.new(mesh_child_name)
        mesh_obj = bpy.data.objects.new(mesh_child_name, b_mesh)
        try:
            mesh_obj.type = "MESH"
        except (AttributeError, TypeError):
            pass
        if hasattr(mesh_obj, "parent"):
            mesh_obj.parent = root_obj
        if target_coll is not None and hasattr(target_coll, "objects") and hasattr(target_coll.objects, "link"):
            try:
                target_coll.objects.link(mesh_obj)
            except Exception:
                pass
    else:
        b_mesh = mesh_obj.data
        if hasattr(mesh_obj, "parent") and mesh_obj.parent != root_obj:
            mesh_obj.parent = root_obj

    _safe_set_custom_prop(mesh_obj, "mtk:is_scene_mesh", True)
    stamp_geometry_origin(mesh_obj, ORIGIN_SCENE, overwrite=True)

    # 3. Inject mesh geometry
    if mesh_data is not None:
        inject_mesh_data(
            b_mesh,
            mesh_data,
            update_topology=True,
            update_normals=True,
        )

    # 4. Bind mini-atlas materials
    materials = []
    if reader is not None:
        materials = bind_scene_materials(mesh_obj, reader, scene_name=s_name)

    # 5. Synchronize companion VoxelPointCloud child object
    cloud_obj = None
    if point_cloud is not None:
        cloud_obj = ensure_voxel_child_cloud(
            parent_obj=root_obj,
            cloud_data=point_cloud,
            origin_centered=origin_centered,
            initial_hidden=True,
        )

    if cloud_obj is not None:
        _safe_set_custom_prop(root_obj, "mtk_voxel_cloud", getattr(cloud_obj, "name", ""))
        _safe_set_custom_prop(mesh_obj, "mtk_voxel_cloud", getattr(cloud_obj, "name", ""))
        _safe_set_custom_prop(cloud_obj, "mtk_world_mesh", getattr(mesh_obj, "name", ""))
        stamp_geometry_origin(cloud_obj, ORIGIN_SCENE, overwrite=True)

    # 6. Store metadata custom properties
    scene_uuid = str(uuid.uuid4())
    now_ts = time.time()
    for target in (root_obj, mesh_obj):
        _safe_set_custom_prop(target, "mtk:scene_uuid", scene_uuid)
        _safe_set_custom_prop(target, "mtk:scene_format_version", meta.get("format_version", 1))
        _safe_set_custom_prop(target, "mtk:voxel_count", meta.get("voxel_count", 0))
        _safe_set_custom_prop(target, "mtk:bounds", list(meta.get("bounds", [0, 0, 0, 0, 0, 0])))
        _safe_set_custom_prop(target, "mtk:generator", str(meta.get("generator", "MoziToolKit")))
        _safe_set_custom_prop(target, "mtk:imported_at", now_ts)

    return {
        "root_obj": root_obj,
        "mesh_obj": mesh_obj,
        "cloud_obj": cloud_obj,
        "materials": materials,
        "scene_uuid": scene_uuid,
    }

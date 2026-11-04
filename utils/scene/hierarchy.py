"""
MoziToolKit Scene Interchange Hierarchy and Assembly.

Orchestrates Blender scene datablocks, unified empty container architecture,
companion point cloud synchronization, canonical PBR materials, and metadata
custom properties for imported .mtkscene interchange packages.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Optional

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from ...bridge.mesh import inject_mesh_data
from ...bridge.world import resolve_dynamic_entity_atlases
from ..materials.builder.world_binding import ensure_world_materials
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


def apply_imported_scene_to_blender(
    data: Dict[str, Any],
    scene_name: Optional[str] = None,
    origin_centered: bool = True,
    target_collection: Optional[Any] = None,
    context: Optional[Any] = None,
    prefs=None,
    enable_animated_textures: bool = True,
) -> Dict[str, Any]:
    """
    Assembles Blender objects for an imported .mtkscene package adhering strictly
    to the Unified World Empty Container architecture:
      Container Root: Empty, `[Scene] <name>`, mtk:is_container=True, mtk:container_type="SCENE"
      ├── World Mesh: Mesh, `[Scene] <name>_Mesh`
      └── Companion Point Cloud: Mesh, `[Scene] <name>_VoxelCloud` (hidden by default)
    """
    if not HAS_BPY:
        return {}

    if context is None and hasattr(bpy, "context"):
        context = bpy.context

    mesh_data = data.get("mesh_data")
    point_cloud = data.get("point_cloud")
    storage = data.get("storage")
    reader = data.get("reader")
    atlas = data.get("atlas")
    meta = data.get("metadata", {})

    s_name = scene_name or "Scene"
    root_name = f"[Scene] {s_name}"
    mesh_child_name = f"{root_name}_Mesh"

    target_coll = target_collection or (
        context.collection
        if context and getattr(context, "collection", None)
        else (bpy.context.scene.collection if hasattr(bpy.context, "scene") else None)
    )

    scene_uuid = str(uuid.uuid4())

    # 1. Acquire or create Root Empty Container
    root_obj = None
    if hasattr(bpy, "data") and hasattr(bpy.data, "objects") and root_name in bpy.data.objects:
        cand = bpy.data.objects[root_name]
        if getattr(cand, "type", "") == "EMPTY":
            root_obj = cand

    if root_obj is None:
        root_obj = bpy.data.objects.new(root_name, None)
        if hasattr(root_obj, "empty_display_type"):
            root_obj.empty_display_type = "PLAIN_AXES"
        if hasattr(root_obj, "empty_display_size"):
            root_obj.empty_display_size = 1.0
        if target_coll is not None and hasattr(target_coll, "objects") and hasattr(target_coll.objects, "link"):
            try:
                target_coll.objects.link(root_obj)
            except Exception:
                pass

    _safe_set_custom_prop(root_obj, "mtk:is_container", True)
    _safe_set_custom_prop(root_obj, "mtk:container_type", "SCENE")
    _safe_set_custom_prop(root_obj, "mtk:container_id", scene_uuid)
    _safe_set_custom_prop(root_obj, "mozi_scene_uuid", scene_uuid)
    _safe_set_custom_prop(root_obj, "mtk:last_name", getattr(root_obj, "name", root_name))
    _safe_set_custom_prop(root_obj, "mtk:is_scene_container", True)

    # 2. Acquire or create Child Mesh Object
    mesh_obj = None
    if hasattr(bpy, "data") and hasattr(bpy.data, "objects") and mesh_child_name in bpy.data.objects:
        cand = bpy.data.objects[mesh_child_name]
        if getattr(cand, "type", "") == "MESH":
            mesh_obj = cand

    if mesh_obj is None:
        b_mesh = bpy.data.meshes.new(mesh_child_name)
        mesh_obj = bpy.data.objects.new(mesh_child_name, b_mesh)
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

    # 3. Inject mesh geometry (Dual-Channel Safe-Path / DNA Fast-Path)
    if mesh_data is not None:
        inject_mesh_data(
            b_mesh,
            mesh_data,
            update_topology=True,
            update_normals=True,
        )

    # 4. Bind Mini-Atlas materials via SSOT canonical PBR pipeline
    used_chunk_ids = mesh_data.used_materials() if mesh_data and hasattr(mesh_data, "used_materials") else None
    dynamic_entity_atlases = resolve_dynamic_entity_atlases(mesh_data) if mesh_data else None

    materials = bind_scene_materials(
        mesh_obj,
        reader=reader,
        scene_name=s_name,
        atlas=atlas,
        prefs=prefs,
        used_chunk_ids=used_chunk_ids,
        dynamic_entity_atlases=dynamic_entity_atlases,
    )

    # 5. Extract unculled companion VoxelPointCloud child object
    cloud_obj = ensure_voxel_child_cloud(
        parent_obj=root_obj,
        storage=storage,
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
    now_ts = time.time()
    for target in (root_obj, mesh_obj):
        _safe_set_custom_prop(target, "mozi_scene_uuid", str(scene_uuid))
        _safe_set_custom_prop(target, "mtk:container_id", str(scene_uuid))
        _safe_set_custom_prop(target, "mtk:scene_format_version", meta.get("format_version", 1))
        _safe_set_custom_prop(target, "mtk:voxel_count", meta.get("voxel_count", 0))
        _safe_set_custom_prop(target, "mtk:bounds", list(meta.get("bounds", [0, 0, 0, 0, 0, 0])))
        _safe_set_custom_prop(target, "mtk:generator", str(meta.get("generator", "MoziToolKit")))
        _safe_set_custom_prop(target, "mtk:origin_centered", bool(origin_centered))
        _safe_set_custom_prop(target, "mtk:enable_animated_textures", bool(enable_animated_textures))
        _safe_set_custom_prop(target, "mtk:imported_at", float(now_ts))
        _safe_set_custom_prop(target, "mtk:biome_preset", "WORLD")

    # 7. Register VoxelStorage and colormaps in memory cache for instant WORLD biome restores
    if storage is not None:
        from ..materials.biome.updater import register_object_storage

        if register_object_storage is not None:
            register_object_storage(str(scene_uuid), storage)
            if root_obj and hasattr(root_obj, "name"):
                register_object_storage(root_obj.name, storage)
            if mesh_obj and hasattr(mesh_obj, "name"):
                register_object_storage(mesh_obj.name, storage)

    colormaps = data.get("colormaps")
    if colormaps is not None:
        from ..materials.biome.updater import register_object_colormaps

        if register_object_colormaps is not None:
            register_object_colormaps(str(scene_uuid), colormaps)
            if root_obj and hasattr(root_obj, "name"):
                register_object_colormaps(root_obj.name, colormaps)
            if mesh_obj and hasattr(mesh_obj, "name"):
                register_object_colormaps(mesh_obj.name, colormaps)

    # 8. Prime base tint types for the newly created mesh
    from ..materials.biome.updater import resolve_mesh_base_tint_types

    if resolve_mesh_base_tint_types is not None:
        try:
            resolve_mesh_base_tint_types(b_mesh, mesh_obj)
        except Exception:
            pass

    # 9. Activate root container in viewport
    if context and hasattr(context, "view_layer"):
        try:
            if hasattr(root_obj, "select_set"):
                root_obj.select_set(True)
            if hasattr(context.view_layer, "objects"):
                context.view_layer.objects.active = root_obj
        except (RuntimeError, Exception):
            pass

    return {
        "root_obj": root_obj,
        "mesh_obj": mesh_obj,
        "cloud_obj": cloud_obj,
        "materials": materials,
        "scene_uuid": scene_uuid,
    }

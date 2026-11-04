"""
Unified Voxel World Scene Assembler.

Single Source of Truth (SSOT) orchestrator for assembling Blender scene datablocks,
Empty container hierarchies, dual-channel mesh geometry injection, companion point clouds,
canonical PBR material binding, and dynamic entity slot persistence.
Unifies the assembly pipeline across Live Sync, Save Import, and .mtkscene Interchange.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from ...bridge.mesh import inject_mesh_data
from ...bridge.world import resolve_dynamic_entity_atlases
from ..materials.builder.world_binding import ensure_world_materials
from ..mesh.ownership import stamp_geometry_origin
from ..point_cloud.hierarchy import ensure_voxel_child_cloud
from ..materials.biome import updater as _biome_updater

logger = logging.getLogger("MoziToolKit.World.Assembler")


def safe_set_custom_prop(obj: Any, key: str, val: Any) -> None:
    """Sets a custom property or fallback attribute without raising exceptions."""
    if obj is None:
        return
    try:
        obj[key] = val
    except (TypeError, AttributeError, KeyError):
        try:
            setattr(obj, key, val)
        except Exception:
            pass


def safe_get_custom_prop(obj: Any, key: str, default: Any = None) -> Any:
    """Gets a custom property with fallback attribute check."""
    if obj is None:
        return default
    if hasattr(obj, "get"):
        val = obj.get(key)
        if val is not None:
            return val
    return getattr(obj, key, default)


def persist_dynamic_entity_slots(
    targets: List[Any],
    slot_map: Optional[Dict[str, Tuple[int, int]]],
) -> Optional[str]:
    """Serializes dynamic entity slot allocation and stamps across target Blender objects."""
    if not slot_map:
        return None
    try:
        slots_json = json.dumps(
            {str(k): [int(v[0]), int(v[1])] for k, v in slot_map.items()},
            separators=(",", ":"),
        )
    except Exception:
        return None

    if slots_json:
        for t in targets:
            if t is not None:
                safe_set_custom_prop(t, "mtk:dynamic_entity_slots", slots_json)
    return slots_json


@dataclass
class VoxelWorldAssemblyRequest:
    """Request DTO specifying everything needed to assemble a voxel world in Blender."""

    container_type: str  # "SAVE" | "SCENE" | "SYNC"
    root_name: str
    mesh_data: Any
    storage: Optional[Any] = None
    point_cloud: Optional[Any] = None
    container_id: Optional[str] = None
    atlas: Optional[Any] = None
    dynamic_entity_atlases: Optional[Any] = None
    dynamic_entity_slots: Optional[Dict[str, Tuple[int, int]]] = None
    colormaps: Optional[Any] = None
    origin_centered: bool = True
    reuse_existing: bool = True
    target_root: Optional[Any] = None
    target_mesh: Optional[Any] = None
    target_collection: Optional[Any] = None
    context: Optional[Any] = None
    prefs: Optional[Any] = None
    geometry_origin: Optional[str] = None
    skip_string_attributes: bool = False
    custom_injector: Optional[Callable[..., Any]] = None
    custom_material_binder: Optional[Callable[[Any], Any]] = None
    custom_cloud_ensurer: Optional[Callable[..., Any]] = None
    clean_unused_material_slots: bool = True
    sync_point_cloud: bool = True
    metadata_props: Dict[str, Any] = field(default_factory=dict)


def assemble_voxel_world(req: VoxelWorldAssemblyRequest) -> Dict[str, Any]:
    """
    Core authoritative assembler for Blender voxel worlds:
    1. Resolves/creates Root Empty Container & child Mesh Object
    2. Injects geometry via Dual-Channel Safe-Path/DNA Fast-Path
    3. Binds PBR / Mini-Atlas materials
    4. Synchronizes unculled companion Voxel Point Cloud
    5. Persists dynamic entity slot JSON across objects
    6. Registers in-memory caches (storage, colormaps) and primes tint types
    7. Stamps metadata custom properties and activates in viewport
    """
    if not HAS_BPY or bpy is None:
        return {}

    context = req.context or getattr(bpy, "context", None)
    target_coll = req.target_collection or (
        context.collection
        if context and getattr(context, "collection", None)
        else (getattr(getattr(context, "scene", None), "collection", None) if context else None)
    )

    container_id = req.container_id or uuid.uuid4().hex

    # 1. Acquire or create Root Empty Container
    root_obj = req.target_root
    if root_obj is None and req.reuse_existing and hasattr(bpy, "data") and hasattr(bpy.data, "objects") and req.root_name in bpy.data.objects:
        cand = bpy.data.objects[req.root_name]
        if getattr(cand, "type", "") == "EMPTY":
            root_obj = cand

    if root_obj is None and req.container_type != "SYNC":
        root_obj = bpy.data.objects.new(req.root_name, None)
        if hasattr(root_obj, "empty_display_type"):
            root_obj.empty_display_type = "PLAIN_AXES"
        if hasattr(root_obj, "empty_display_size"):
            root_obj.empty_display_size = 1.0
        if target_coll is not None and hasattr(target_coll, "objects") and hasattr(target_coll.objects, "link"):
            try:
                target_coll.objects.link(root_obj)
            except Exception:
                pass

    if root_obj is not None:
        safe_set_custom_prop(root_obj, "mtk:is_container", True)
        safe_set_custom_prop(root_obj, "mtk:container_type", req.container_type)
        safe_set_custom_prop(root_obj, "mtk:container_id", str(container_id))
        safe_set_custom_prop(root_obj, "mtk:last_name", getattr(root_obj, "name", req.root_name))

        # Backward compatibility properties
        if req.container_type == "SAVE":
            safe_set_custom_prop(root_obj, "mozi_save_uuid", str(container_id))
        elif req.container_type == "SCENE":
            safe_set_custom_prop(root_obj, "mozi_scene_uuid", str(container_id))
            safe_set_custom_prop(root_obj, "mtk:is_scene_container", True)

    actual_root_name = getattr(root_obj, "name", req.root_name) if root_obj else req.root_name

    # 2. Acquire or create Child Mesh Object
    mesh_obj = req.target_mesh
    mesh_child_name = f"{actual_root_name}_Mesh" if req.container_type != "SYNC" else actual_root_name

    if mesh_obj is None:
        if req.reuse_existing and hasattr(bpy, "data") and hasattr(bpy.data, "objects") and mesh_child_name in bpy.data.objects:
            cand = bpy.data.objects[mesh_child_name]
            if getattr(cand, "type", "") == "MESH":
                mesh_obj = cand

        if mesh_obj is None:
            b_mesh = bpy.data.meshes.new(mesh_child_name)
            mesh_obj = bpy.data.objects.new(mesh_child_name, b_mesh)
            if root_obj is not None and hasattr(mesh_obj, "parent"):
                mesh_obj.parent = root_obj
            if target_coll is not None and hasattr(target_coll, "objects") and hasattr(target_coll.objects, "link"):
                try:
                    target_coll.objects.link(mesh_obj)
                except Exception:
                    pass
        else:
            b_mesh = mesh_obj.data
            if root_obj is not None and hasattr(mesh_obj, "parent") and mesh_obj.parent != root_obj:
                mesh_obj.parent = root_obj
    else:
        b_mesh = mesh_obj.data
        if root_obj is not None and hasattr(mesh_obj, "parent") and mesh_obj.parent != root_obj and root_obj != mesh_obj:
            mesh_obj.parent = root_obj

    if req.geometry_origin:
        stamp_geometry_origin(mesh_obj, req.geometry_origin, overwrite=True)

    if req.container_type == "SAVE":
        safe_set_custom_prop(mesh_obj, "mtk:is_save_mesh", True)
    elif req.container_type == "SCENE":
        safe_set_custom_prop(mesh_obj, "mtk:is_scene_mesh", True)

    # 3. Inject mesh geometry (Dual-Channel Safe-Path / DNA Fast-Path)
    t_inject = time.perf_counter()
    injector_fn = req.custom_injector or inject_mesh_data
    if req.mesh_data is not None and b_mesh is not None:
        injector_fn(
            b_mesh,
            req.mesh_data,
            update_topology=True,
            update_normals=True,
            skip_string_attributes=req.skip_string_attributes,
        )
    inject_ms = (time.perf_counter() - t_inject) * 1000.0

    # 4. Material Binding
    t_mat = time.perf_counter()
    materials = None
    if req.custom_material_binder is not None:
        materials = req.custom_material_binder(mesh_obj)
    elif req.mesh_data is not None and mesh_obj is not None:
        used_chunk_ids = req.mesh_data.used_materials() if hasattr(req.mesh_data, "used_materials") else None
        dyn_atlases = req.dynamic_entity_atlases
        if dyn_atlases is None:
            dyn_atlases = resolve_dynamic_entity_atlases(req.mesh_data)
        ensure_world_materials(
            mesh_obj,
            prefs=req.prefs,
            atlas=req.atlas,
            used_chunk_ids=used_chunk_ids,
            dynamic_entity_atlases=dyn_atlases,
            clean_unused_slots=req.clean_unused_material_slots,
        )
    materials_ms = (time.perf_counter() - t_mat) * 1000.0

    # 5. Extract and link Companion Voxel Point Cloud
    t_cloud = time.perf_counter()
    cloud_obj = None
    cloud_ensurer = req.custom_cloud_ensurer or ensure_voxel_child_cloud
    if req.sync_point_cloud and (req.storage is not None or req.point_cloud is not None):
        parent_target = root_obj if (root_obj and getattr(root_obj, "type", "") == "EMPTY") else mesh_obj
        if parent_target is not None:
            try:
                cloud_obj = cloud_ensurer(
                    parent_obj=parent_target,
                    storage=req.storage,
                    cloud_data=req.point_cloud,
                    origin_centered=req.origin_centered,
                    initial_hidden=True,
                )
            except Exception as e:
                logger.warning("Failed ensuring companion voxel child cloud: %s", e)

    if cloud_obj is not None:
        cloud_name = getattr(cloud_obj, "name", "")
        mesh_name = getattr(mesh_obj, "name", "")
        if root_obj is not None:
            safe_set_custom_prop(root_obj, "mtk_voxel_cloud", cloud_name)
        if mesh_obj is not None:
            safe_set_custom_prop(mesh_obj, "mtk_voxel_cloud", cloud_name)
            safe_set_custom_prop(cloud_obj, "mtk_world_mesh", mesh_name)
        if req.geometry_origin:
            stamp_geometry_origin(cloud_obj, req.geometry_origin, overwrite=True)

    cloud_ms = (time.perf_counter() - t_cloud) * 1000.0

    # 6. Dynamic Entity Slot Persistence
    slot_map = req.dynamic_entity_slots
    if slot_map is None and req.mesh_data is not None:
        slot_map = getattr(req.mesh_data, "dynamic_entity_slots", None)
    persist_dynamic_entity_slots([root_obj, mesh_obj, cloud_obj], slot_map)

    # 7. Metadata Custom Properties
    now_ts = time.time()
    targets = [t for t in (root_obj, mesh_obj) if t is not None]
    for target in targets:
        safe_set_custom_prop(target, "mtk:container_id", str(container_id))
        safe_set_custom_prop(target, "mtk:origin_centered", bool(req.origin_centered))
        safe_set_custom_prop(target, "mtk:imported_at", float(now_ts))
        safe_set_custom_prop(target, "mtk:biome_preset", "WORLD")
        for k, v in req.metadata_props.items():
            safe_set_custom_prop(target, k, v)

    # 8. Register in-memory caches and prime tint types
    container_id_str = str(container_id)
    if req.storage is not None:
        reg_fn = getattr(_biome_updater, "register_object_storage", None)
        if reg_fn is not None:
            reg_fn(container_id_str, req.storage)
            if root_obj and hasattr(root_obj, "name"):
                reg_fn(root_obj.name, req.storage)
            if mesh_obj and hasattr(mesh_obj, "name"):
                reg_fn(mesh_obj.name, req.storage)

    if req.colormaps is not None:
        reg_col_fn = getattr(_biome_updater, "register_object_colormaps", None)
        if reg_col_fn is not None:
            reg_col_fn(container_id_str, req.colormaps)
            if root_obj and hasattr(root_obj, "name"):
                reg_col_fn(root_obj.name, req.colormaps)
            if mesh_obj and hasattr(mesh_obj, "name"):
                reg_col_fn(mesh_obj.name, req.colormaps)

    if b_mesh is not None and mesh_obj is not None:
        prime_fn = getattr(_biome_updater, "resolve_mesh_base_tint_types", None)
        if prime_fn is not None:
            try:
                prime_fn(b_mesh, mesh_obj)
            except Exception:
                pass

    # 9. Viewport activation
    active_target = root_obj or mesh_obj
    if active_target is not None and context and hasattr(context, "view_layer"):
        try:
            if hasattr(active_target, "select_set"):
                active_target.select_set(True)
            if hasattr(context.view_layer, "objects"):
                context.view_layer.objects.active = active_target
        except (RuntimeError, Exception):
            pass

    host_ms = inject_ms + materials_ms + cloud_ms

    return {
        "root_obj": root_obj,
        "mesh_obj": mesh_obj,
        "cloud_obj": cloud_obj,
        "container_id": container_id,
        "materials": materials,
        "inject_ms": inject_ms,
        "materials_ms": materials_ms,
        "cloud_ms": cloud_ms,
        "host_ms": host_ms,
    }


__all__ = [
    "safe_set_custom_prop",
    "safe_get_custom_prop",
    "persist_dynamic_entity_slots",
    "VoxelWorldAssemblyRequest",
    "assemble_voxel_world",
]

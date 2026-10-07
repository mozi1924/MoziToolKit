"""
MoziToolKit Minecraft Save Loader Bridge Module.

Encapsulates mtk-save and simdnbt calls for high-performance, on-demand
spatial ingestion of Minecraft Java Edition worlds.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .engine import get_libmtk, has_libmtk, require_libmtk
from .mesh import inject_mesh_data
from .point_cloud import ensure_voxel_child_cloud
from .world import ensure_world_materials, get_world_pipeline_assets

try:
    from ..utils.system.save_registry import get_save_registry
except (ImportError, ValueError):
    try:
        from utils.system.save_registry import get_save_registry
    except (ImportError, ValueError):
        get_save_registry = None


logger = logging.getLogger("MoziToolKit.Bridge.Save")


def inspect_minecraft_save(path: str | Path) -> Dict[str, Any]:
    """
    Inspects a Minecraft save folder or level.dat path, returning world metadata
    and discovered dimensions without loading chunk geometry.
    """
    mtk = require_libmtk("inspect_minecraft_save")
    target_path = str(Path(path).resolve())

    if hasattr(mtk, "inspect_minecraft_save"):
        meta = mtk.inspect_minecraft_save(target_path)
        return {
            "level_name": meta.level_name,
            "version_name": meta.version_name,
            "data_version": meta.data_version,
            "spawn": meta.spawn,
            "time": meta.time,
            "day_time": meta.day_time,
            "hardcore": meta.hardcore,
            "game_type": meta.game_type,
            "dimensions": meta.dimensions,
        }

    return {
        "level_name": "Minecraft World",
        "version_name": "Unknown",
        "data_version": 0,
        "spawn": (0, 64, 0),
        "time": 0,
        "day_time": 0,
        "hardcore": False,
        "game_type": 0,
        "dimensions": ["overworld"],
    }


def load_and_mesh_minecraft_save(
    world_dir: str | Path,
    dimension: str = "overworld",
    min_block: Tuple[int, int, int] = (-64, -64, -64),
    max_block: Tuple[int, int, int] = (64, 320, 64),
    prefs=None,
    model_db: Optional[Any] = None,
    atlas: Optional[Any] = None,
    biome_resolver: Optional[Any] = None,
    enable_ao: bool = True,
    mesh_fluids: bool = True,
    weld_vertices: bool = True,
    origin_centered: bool = True,
    num_threads: Optional[int] = None,
    progress_callback: Optional[Any] = None,
) -> Tuple[Any, Dict[str, Any], Any, float]:
    """
    Directly streams and meshes a bounded 3D selection from an Anvil save.
    Returns (mesh_data, level_meta_dict, storage, elapsed_ms).
    """
    mtk = require_libmtk("load_and_mesh_minecraft_save")
    target_path = str(Path(world_dir).resolve())

    # Auto-resolve pipeline assets if not supplied
    if model_db is None or atlas is None or biome_resolver is None:
        cached_mdb, cached_atlas, cached_resolver = get_world_pipeline_assets(prefs)
        model_db = model_db or cached_mdb
        atlas = atlas or cached_atlas
        biome_resolver = biome_resolver or cached_resolver

    # Thread count resolution
    if num_threads is None and prefs is not None:
        num_threads = getattr(prefs, "thread_count", 0) or None

    config = mtk.MesherConfig(
        enable_ao=enable_ao,
        mesh_fluids=mesh_fluids,
        z_up_coordinates=True,
        origin_centered=origin_centered,
        weld_vertices=weld_vertices,
        num_threads=num_threads,
        atlas=atlas,
        biome_resolver=biome_resolver,
    )

    culler = mtk.FaceCuller() if hasattr(mtk, "FaceCuller") else None

    wrapped_cb = None
    if progress_callback is not None:
        from .progress import wrap_progress_callback
        wrapped_cb = wrap_progress_callback(progress_callback)

    t0 = time.perf_counter()
    try:
        mesh_data, level_meta, storage = mtk.load_and_mesh_minecraft_save(
            world_dir=target_path,
            dimension=dimension,
            min_block=min_block,
            max_block=max_block,
            config=config,
            culler=culler,
            model_db=model_db,
            num_threads=num_threads,
            callback=wrapped_cb,
        )
    except TypeError:
        mesh_data, level_meta, storage = mtk.load_and_mesh_minecraft_save(
            world_dir=target_path,
            dimension=dimension,
            min_block=min_block,
            max_block=max_block,
            config=config,
            culler=culler,
            model_db=model_db,
            num_threads=num_threads,
        )
    t1 = time.perf_counter()
    elapsed_ms = (t1 - t0) * 1000.0

    meta_dict = {
        "level_name": level_meta.level_name,
        "version_name": level_meta.version_name,
        "data_version": level_meta.data_version,
        "spawn": level_meta.spawn,
        "time": level_meta.time,
        "day_time": level_meta.day_time,
        "hardcore": level_meta.hardcore,
        "game_type": level_meta.game_type,
        "dimensions": level_meta.dimensions,
    }

    return mesh_data, meta_dict, storage, elapsed_ms


import uuid


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


def sanitize_save_privacy(obj: Any) -> Optional[str]:
    """
    Checks if the object contains a legacy 'mtk_source_path' property.
    If present, migrates the local path to SaveRegistryManager and scrubs
    the sensitive absolute path to avoid leaking username/paths when sharing .blend files.
    """
    if obj is None:
        return None
    source_path = None
    if hasattr(obj, "get"):
        source_path = obj.get("mtk_source_path")
    elif hasattr(obj, "mtk_source_path"):
        source_path = getattr(obj, "mtk_source_path")

    save_uuid = None
    if hasattr(obj, "get"):
        save_uuid = obj.get("mozi_save_uuid") or obj.get("mtk:container_id")

    if source_path and get_save_registry is not None:
        try:
            reg = get_save_registry()
            dim = obj.get("mtk_dimension", "overworld") if hasattr(obj, "get") else "overworld"
            world_name = obj.get("mtk_world_name", "") if hasattr(obj, "get") else ""
            save_uuid = reg.register_save(
                world_dir=source_path,
                dimension=dim,
                level_name=world_name,
                save_uuid=save_uuid,
            )
        except Exception as e:
            logger.warning(f"Failed migrating legacy mtk_source_path to registry: {e}")

    # Remove the sensitive property completely from blender custom props
    if hasattr(obj, "__delitem__") and hasattr(obj, "__contains__") and "mtk_source_path" in obj:
        try:
            del obj["mtk_source_path"]
        except Exception:
            pass

    return save_uuid


def _resolve_unique_save_container_name(base_name: str, bpy_module: Any) -> str:
    """Finds the next non-colliding container name (e.g. Save_World_overworld, Save_World_overworld_01)."""
    if not hasattr(bpy_module, "data") or not hasattr(bpy_module.data, "objects"):
        return base_name
    objects = bpy_module.data.objects
    if base_name not in objects:
        return base_name
    idx = 1
    while f"{base_name}_{idx:02d}" in objects:
        idx += 1
    return f"{base_name}_{idx:02d}"



def apply_imported_save_to_blender(
    mesh_data: Any,
    meta: Dict[str, Any],
    storage: Any,
    elapsed_ms: float,
    world_dir: str | Path,
    dimension: str = "overworld",
    min_block: Tuple[int, int, int] = (-64, -64, -64),
    max_block: Tuple[int, int, int] = (64, 320, 64),
    context: Optional[Any] = None,
    prefs=None,
    atlas: Optional[Any] = None,
    origin_centered: bool = True,
    reuse_existing: bool = False,
    enable_ao: bool = True,
    mesh_fluids: bool = True,
    weld_vertices: bool = True,
    target_root: Optional[Any] = None,
) -> Tuple[Any, Dict[str, Any]]:
    """
    Main-thread Blender scene injector for pre-meshed Minecraft save geometry.
    Adheres to the Unified World Empty Container architecture:
      Container Root (Empty, mtk:is_container=True, mtk:container_type="SAVE")
      ├── World Mesh (Mesh, <Container>_Mesh)
      └── Point Cloud (Mesh, <Container>_VoxelCloud, hidden by default)
    """
    try:
        import bpy
    except ImportError:
        raise RuntimeError("bpy is not available in headless non-Blender environment.")

    if context is None:
        context = bpy.context

    target_coll = context.collection if context and context.collection else (
        bpy.context.scene.collection if hasattr(bpy.context, "scene") else None
    )

    clean_name = meta["level_name"].replace(" ", "_")
    base_container_name = f"Save_{clean_name}_{dimension}"

    # 1. Acquire or create Root Empty Container
    root_obj = target_root
    if root_obj is None and reuse_existing and hasattr(bpy, "data") and hasattr(bpy.data, "objects") and base_container_name in bpy.data.objects:
        cand = bpy.data.objects[base_container_name]
        if getattr(cand, "type", "") == 'EMPTY':
            root_obj = cand

    save_uuid = None
    if root_obj is not None and hasattr(root_obj, "get"):
        save_uuid = root_obj.get("mozi_save_uuid") or root_obj.get("mtk:container_id")

    if get_save_registry is not None and world_dir:
        try:
            reg = get_save_registry()
            save_uuid = reg.register_save(
                world_dir=world_dir,
                dimension=dimension,
                level_name=meta.get("level_name", ""),
                save_uuid=save_uuid,
            )
        except Exception as e:
            logger.warning(f"Could not register save to local registry: {e}")

    if not save_uuid:
        save_uuid = uuid.uuid4().hex

    if root_obj is None:
        container_name = _resolve_unique_save_container_name(base_container_name, bpy) if not reuse_existing else base_container_name
        root_obj = bpy.data.objects.new(container_name, None)
        if hasattr(root_obj, "empty_display_type"):
            root_obj.empty_display_type = 'PLAIN_AXES'
        if hasattr(root_obj, "empty_display_size"):
            root_obj.empty_display_size = 1.0
        _safe_set_custom_prop(root_obj, "mtk:is_container", True)
        _safe_set_custom_prop(root_obj, "mtk:container_type", "SAVE")
        _safe_set_custom_prop(root_obj, "mtk:container_id", save_uuid)
        _safe_set_custom_prop(root_obj, "mozi_save_uuid", save_uuid)
        _safe_set_custom_prop(root_obj, "mtk:last_name", getattr(root_obj, "name", container_name))
        if target_coll is not None and hasattr(target_coll, "objects") and hasattr(target_coll.objects, "link"):
            try:
                target_coll.objects.link(root_obj)
            except Exception:
                pass

    container_name = getattr(root_obj, "name", base_container_name)

    # 2. Acquire or create Child Mesh Object
    mesh_child_name = f"{container_name}_Mesh"
    mesh_obj = None
    if reuse_existing and hasattr(bpy, "data") and hasattr(bpy.data, "objects") and mesh_child_name in bpy.data.objects:
        cand = bpy.data.objects[mesh_child_name]
        if getattr(cand, "type", "") == "MESH":
            mesh_obj = cand

    if mesh_obj is None:
        b_mesh = bpy.data.meshes.new(mesh_child_name)
        mesh_obj = bpy.data.objects.new(mesh_child_name, b_mesh)
        if hasattr(mesh_obj, "parent"):
            mesh_obj.parent = root_obj
        _safe_set_custom_prop(mesh_obj, "mtk:is_save_mesh", True)
        if target_coll is not None and hasattr(target_coll, "objects") and hasattr(target_coll.objects, "link"):
            try:
                target_coll.objects.link(mesh_obj)
            except Exception:
                pass
    else:
        b_mesh = mesh_obj.data
        if hasattr(mesh_obj, "parent") and mesh_obj.parent != root_obj:
            mesh_obj.parent = root_obj

    # 3. Inject mesh geometry
    inject_mesh_data(
        b_mesh,
        mesh_data,
        update_topology=True,
        update_normals=True,
    )

    # 4. Bind Atlas materials and shaders
    used_chunk_ids = mesh_data.used_materials() if hasattr(mesh_data, "used_materials") else None
    ensure_world_materials(mesh_obj, prefs=prefs, atlas=atlas, used_chunk_ids=used_chunk_ids)

    # 5. Extract unculled VoxelPointCloud and ensure child companion object under root Empty
    cloud_obj = ensure_voxel_child_cloud(
        parent_obj=root_obj,
        storage=storage,
        origin_centered=origin_centered,
        initial_hidden=True,
    )
    cloud_count = len(cloud_obj.data.vertices) if cloud_obj and hasattr(cloud_obj, "data") and hasattr(cloud_obj.data, "vertices") else 0

    if cloud_obj:
        _safe_set_custom_prop(root_obj, "mtk_voxel_cloud", getattr(cloud_obj, "name", ""))
        _safe_set_custom_prop(mesh_obj, "mtk_voxel_cloud", getattr(cloud_obj, "name", ""))
        _safe_set_custom_prop(cloud_obj, "mtk_world_mesh", getattr(mesh_obj, "name", ""))

    # 6. Store metadata in Object Custom Properties on both root container and mesh (Privacy Protected)
    now_ts = time.time()
    for target in (root_obj, mesh_obj):
        _safe_set_custom_prop(target, "mozi_save_uuid", str(save_uuid))
        _safe_set_custom_prop(target, "mtk:container_id", str(save_uuid))
        _safe_set_custom_prop(target, "mtk_world_name", str(meta["level_name"]))
        _safe_set_custom_prop(target, "mtk_mc_version", str(meta["version_name"]))
        _safe_set_custom_prop(target, "mtk_data_version", int(meta["data_version"]))
        _safe_set_custom_prop(target, "mtk_dimension", str(dimension))
        _safe_set_custom_prop(target, "mtk_spawn_point", list(meta["spawn"]))
        _safe_set_custom_prop(target, "mtk_min_coord", list(min_block))
        _safe_set_custom_prop(target, "mtk_max_coord", list(max_block))
        _safe_set_custom_prop(target, "mtk_origin_centered", bool(origin_centered))
        _safe_set_custom_prop(target, "mtk_enable_ao", bool(enable_ao))
        _safe_set_custom_prop(target, "mtk_mesh_fluids", bool(mesh_fluids))
        _safe_set_custom_prop(target, "mtk_weld_vertices", bool(weld_vertices))
        _safe_set_custom_prop(target, "mtk_last_refreshed", float(now_ts))
        sanitize_save_privacy(target)


    # 7. Activate root container in viewport
    if context and hasattr(context, "view_layer"):
        try:
            if hasattr(root_obj, "select_set"):
                root_obj.select_set(True)
            if hasattr(context.view_layer, "objects"):
                context.view_layer.objects.active = root_obj
        except (RuntimeError, Exception):
            pass

    stats = {
        "object_name": getattr(root_obj, "name", base_container_name),
        "container_name": getattr(root_obj, "name", base_container_name),
        "mesh_name": getattr(mesh_obj, "name", mesh_child_name),
        "cloud_name": getattr(cloud_obj, "name", None) if cloud_obj else None,
        "level_name": meta["level_name"],
        "version_name": meta["version_name"],
        "data_version": meta["data_version"],
        "vertex_count": len(b_mesh.vertices) if hasattr(b_mesh, "vertices") else 0,
        "polygon_count": len(b_mesh.polygons) if hasattr(b_mesh, "polygons") else 0,
        "voxel_count": cloud_count,
        "elapsed_ms": round(elapsed_ms, 2),
        "save_uuid": save_uuid,
    }

    return root_obj, stats


def import_save_to_blender(
    world_dir: str | Path,
    dimension: str = "overworld",
    min_block: Tuple[int, int, int] = (-64, -64, -64),
    max_block: Tuple[int, int, int] = (64, 320, 64),
    context: Optional[Any] = None,
    prefs=None,
    model_db: Optional[Any] = None,
    atlas: Optional[Any] = None,
    biome_resolver: Optional[Any] = None,
    enable_ao: bool = True,
    mesh_fluids: bool = True,
    weld_vertices: bool = True,
    origin_centered: bool = True,
    reuse_existing: bool = False,
    progress_callback: Optional[Any] = None,
) -> Tuple[Any, Dict[str, Any]]:
    """
    Full synchronous end-to-end Minecraft save importer for Blender.
    """
    mesh_data, meta, storage, elapsed_ms = load_and_mesh_minecraft_save(
        world_dir=world_dir,
        dimension=dimension,
        min_block=min_block,
        max_block=max_block,
        prefs=prefs,
        model_db=model_db,
        atlas=atlas,
        biome_resolver=biome_resolver,
        enable_ao=enable_ao,
        mesh_fluids=mesh_fluids,
        weld_vertices=weld_vertices,
        origin_centered=origin_centered,
        progress_callback=progress_callback,
    )

    return apply_imported_save_to_blender(
        mesh_data=mesh_data,
        meta=meta,
        storage=storage,
        elapsed_ms=elapsed_ms,
        world_dir=world_dir,
        dimension=dimension,
        min_block=min_block,
        max_block=max_block,
        context=context,
        prefs=prefs,
        atlas=atlas,
        origin_centered=origin_centered,
        reuse_existing=reuse_existing,
        enable_ao=enable_ao,
        mesh_fluids=mesh_fluids,
        weld_vertices=weld_vertices,
    )

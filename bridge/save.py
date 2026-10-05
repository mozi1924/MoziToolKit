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
) -> Tuple[Any, Dict[str, Any]]:
    """
    Main-thread Blender scene injector for pre-meshed Minecraft save geometry.
    Fast (tens of milliseconds), zero-copy vertex/loop injection and material binding.
    """
    try:
        import bpy
    except ImportError:
        raise RuntimeError("bpy is not available in headless non-Blender environment.")

    if context is None:
        context = bpy.context

    clean_name = meta["level_name"].replace(" ", "_")
    obj_name = f"MC_{clean_name}_{dimension}"

    # 1. Acquire or create Blender object
    obj = None
    if reuse_existing and obj_name in bpy.data.objects:
        cand = bpy.data.objects[obj_name]
        if cand.type == "MESH":
            obj = cand

    if obj is None:
        b_mesh = bpy.data.meshes.new(obj_name)
        obj = bpy.data.objects.new(obj_name, b_mesh)
        target_coll = context.collection if context and context.collection else bpy.context.scene.collection
        target_coll.objects.link(obj)
    else:
        b_mesh = obj.data

    # 2. Inject mesh geometry
    inject_mesh_data(
        b_mesh,
        mesh_data,
        update_topology=True,
        update_normals=True,
    )

    # 3. Bind Atlas materials and shaders
    used_chunk_ids = mesh_data.used_materials() if hasattr(mesh_data, "used_materials") else None
    ensure_world_materials(obj, prefs=prefs, atlas=atlas, used_chunk_ids=used_chunk_ids)

    # 4. Extract unculled VoxelPointCloud and ensure child companion object
    cloud_obj = ensure_voxel_child_cloud(
        parent_obj=obj,
        storage=storage,
        origin_centered=origin_centered,
        initial_hidden=True,
    )
    cloud_count = len(cloud_obj.data.vertices) if cloud_obj and cloud_obj.data else 0

    # 5. Store metadata in Object Custom Properties
    obj["mtk_world_name"] = str(meta["level_name"])
    obj["mtk_mc_version"] = str(meta["version_name"])
    obj["mtk_data_version"] = int(meta["data_version"])
    obj["mtk_dimension"] = str(dimension)
    obj["mtk_spawn_point"] = list(meta["spawn"])
    obj["mtk_min_coord"] = list(min_block)
    obj["mtk_max_coord"] = list(max_block)
    obj["mtk_source_path"] = str(Path(world_dir).resolve())

    # 6. Activate in viewport
    if context and hasattr(context, "view_layer"):
        obj.select_set(True)
        context.view_layer.objects.active = obj

    stats = {
        "object_name": obj.name,
        "level_name": meta["level_name"],
        "version_name": meta["version_name"],
        "data_version": meta["data_version"],
        "vertex_count": len(b_mesh.vertices),
        "polygon_count": len(b_mesh.polygons),
        "voxel_count": cloud_count,
        "elapsed_ms": round(elapsed_ms, 2),
    }

    return obj, stats


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
    )

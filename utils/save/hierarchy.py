"""Save-imported Blender scene hierarchy, UUID, and privacy handling."""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ...bridge.mesh import inject_mesh_data
from ...utils.point_cloud import ensure_voxel_child_cloud
from ..diagnostics import append_stage_to_last_profile
from ..materials.builder.world_binding import ensure_world_materials
from ..system.save_registry import get_save_registry

logger = logging.getLogger("MoziToolKit.Save.Hierarchy")


def _stamp_save_mesh_origin(obj: Any) -> None:
    """Stamp a save-imported mesh with the explicit MTK save origin."""
    from ..mesh.ownership import ORIGIN_SAVE, stamp_geometry_origin

    stamp_geometry_origin(obj, ORIGIN_SAVE, overwrite=True)


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
    material_mode: str = "ATLAS",
    enable_ctm: bool = True,
    enable_animated_textures: bool = True,
    dynamic_skin_atlas: Optional[Any] = None,
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

    if dynamic_skin_atlas is None:
        dynamic_skin_atlas = getattr(mesh_data, "dynamic_skin_atlas", None)

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
        if target_coll is not None and hasattr(target_coll, "objects") and hasattr(target_coll.objects, "link"):
            try:
                target_coll.objects.link(mesh_obj)
            except Exception:
                pass
    else:
        b_mesh = mesh_obj.data
        if hasattr(mesh_obj, "parent") and mesh_obj.parent != root_obj:
            mesh_obj.parent = root_obj

    # Ownership marker applies to reused meshes too: legacy files only had the
    # creation-time marker, which made reused meshes look external.
    _safe_set_custom_prop(mesh_obj, "mtk:is_save_mesh", True)
    _stamp_save_mesh_origin(mesh_obj)

    # 3. Inject mesh geometry
    t_inject = time.perf_counter()
    inject_mesh_data(
        b_mesh,
        mesh_data,
        update_topology=True,
        update_normals=True,
    )
    inject_ms = (time.perf_counter() - t_inject) * 1000.0

    # 4. Bind Atlas materials and shaders
    t_materials = time.perf_counter()
    used_chunk_ids = mesh_data.used_materials() if hasattr(mesh_data, "used_materials") else None
    ensure_world_materials(
        mesh_obj,
        prefs=prefs,
        atlas=atlas,
        used_chunk_ids=used_chunk_ids,
        dynamic_skin_atlas=dynamic_skin_atlas,
    )
    materials_ms = (time.perf_counter() - t_materials) * 1000.0

    # 5. Extract unculled VoxelPointCloud and ensure child companion object under root Empty
    t_cloud = time.perf_counter()
    cloud_obj = ensure_voxel_child_cloud(
        parent_obj=root_obj,
        storage=storage,
        origin_centered=origin_centered,
        initial_hidden=True,
    )
    cloud_ms = (time.perf_counter() - t_cloud) * 1000.0
    cloud_count = len(cloud_obj.data.vertices) if cloud_obj and hasattr(cloud_obj, "data") and hasattr(cloud_obj.data, "vertices") else 0

    host_ms = inject_ms + materials_ms + cloud_ms
    append_stage_to_last_profile(
        "blender_mesh_injection", inject_ms, getattr(mesh_data, "vertex_count", None)
    )
    append_stage_to_last_profile(
        "blender_material_binding",
        materials_ms,
        len(used_chunk_ids) if used_chunk_ids else None,
    )
    if cloud_obj is not None:
        append_stage_to_last_profile("blender_voxel_cloud_sync", cloud_ms, cloud_count)

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
        _safe_set_custom_prop(target, "mtk_enable_ctm", bool(enable_ctm))
        _safe_set_custom_prop(target, "mtk_enable_animated_textures", bool(enable_animated_textures))
        _safe_set_custom_prop(target, "mtk_last_refreshed", float(now_ts))
        _safe_set_custom_prop(target, "mtk:biome_preset", "WORLD")
        sanitize_save_privacy(target)

    # 7. Register VoxelStorage in memory cache for instant WORLD biome restores
    if storage is not None:
        from ..materials.biome.updater import register_object_storage

        if register_object_storage is not None:
            if save_uuid:
                register_object_storage(str(save_uuid), storage)
            if root_obj and hasattr(root_obj, "name"):
                register_object_storage(root_obj.name, storage)
            if mesh_obj and hasattr(mesh_obj, "name"):
                register_object_storage(mesh_obj.name, storage)

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
        "host_ms": round(host_ms, 2),
        "total_ms": round(elapsed_ms + host_ms, 2),
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
    material_mode: str = "ATLAS",
    enable_ctm: bool = True,
    enable_animated_textures: Optional[bool] = None,
) -> Tuple[Any, Dict[str, Any]]:
    """
    Full synchronous end-to-end Minecraft save importer pipeline for Blender:
    1. Loads and meshes voxel selection via bridge.save.load_and_mesh_minecraft_save
    2. Injects geometry, binds materials, creates companion point cloud via apply_imported_save_to_blender.
    """
    from ...bridge.save import load_and_mesh_minecraft_save

    anim_tex_enabled = enable_animated_textures
    if anim_tex_enabled is None:
        raw_val = getattr(prefs, "enable_animated_textures", True) if prefs else True
        anim_tex_enabled = raw_val if isinstance(raw_val, bool) else True
    else:
        anim_tex_enabled = bool(anim_tex_enabled)

    skin_cache_dir = None
    try:
        from ..assets.cache_utils import get_cache_dir
        sc = get_cache_dir() / "skins"
        sc.mkdir(parents=True, exist_ok=True)
        skin_cache_dir = str(sc)
    except Exception:
        pass

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
        material_mode=material_mode,
        enable_ctm=enable_ctm,
        enable_animated_textures=anim_tex_enabled,
        skin_cache_dir=skin_cache_dir,
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
        material_mode=material_mode,
        enable_ctm=enable_ctm,
        enable_animated_textures=anim_tex_enabled,
    )




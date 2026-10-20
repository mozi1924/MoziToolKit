"""
MoziToolKit Utils: Voxel World Scene Injector & Importer Pipeline.

Orchestrates the conversion of VoxelStorage and MeshData into Blender Mesh Objects,
binding Atlas PBR materials or Standalone shaders, configuring child VoxelPointCloud,
and setting up collection hierarchy.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("MoziToolKit.Utils.World.Injector")

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

try:
    from ...bridge.mesh import inject_mesh_data
    from ...utils.point_cloud.hierarchy import ensure_voxel_child_cloud
    from ...utils.materials.builder.world_binding import ensure_world_materials
    from ...utils.mesh.ownership import ORIGIN_VOXEL, stamp_geometry_origin
except (ImportError, ValueError):
    from bridge.mesh import inject_mesh_data
    from utils.point_cloud.hierarchy import ensure_voxel_child_cloud
    from utils.materials.builder.world_binding import ensure_world_materials
    from utils.mesh.ownership import ORIGIN_VOXEL, stamp_geometry_origin


def _stamp_voxel_mesh_origin(obj: Any) -> None:
    """Mark a standalone voxel-generated mesh as MTK-owned."""
    stamp_geometry_origin(obj, ORIGIN_VOXEL, overwrite=True)


def apply_voxel_mesh_to_blender(
    mesh_data: Any,
    storage: Any,
    elapsed_ms: float = 0.0,
    context: Optional[Any] = None,
    name: str = "MTK_World",
    prefs=None,
    atlas: Optional[Any] = None,
    origin_centered: bool = True,
    reuse_existing: bool = True,
    material_mode: str = "ATLAS",
    inject_mesh_func=None,
    ensure_materials_func=None,
    ensure_cloud_func=None,
) -> Tuple[Any, Dict[str, Any]]:
    """
    Main-thread Blender scene injector for pre-meshed voxel world geometry.
    Instantiates or updates target Blender Mesh object, binds Atlas PBR chunk shaders
    or Standalone Principled/LabPBR materials, and synchronizes companion unculled VoxelPointCloud.
    """
    if not HAS_BPY:
        raise RuntimeError("bpy is not available.")

    if context is None:
        context = bpy.context

    # 1. Acquire or create Blender object
    obj = None
    if reuse_existing and name in bpy.data.objects:
        cand = bpy.data.objects[name]
        if cand.type == "MESH":
            obj = cand

    if obj is None:
        b_mesh = bpy.data.meshes.new(name)
        obj = bpy.data.objects.new(name, b_mesh)
        target_coll = context.collection if context and context.collection else bpy.context.scene.collection
        target_coll.objects.link(obj)
    else:
        b_mesh = obj.data

    _stamp_voxel_mesh_origin(obj)

    # 2. Inject topology, positions, UVs, normals, materials
    _inject = inject_mesh_func or inject_mesh_data
    _inject(
        b_mesh,
        mesh_data,
        update_topology=True,
        update_normals=True,
    )

    # 3. Bind only used Atlas chunk materials & shaders
    used_chunk_ids = mesh_data.used_materials() if hasattr(mesh_data, "used_materials") else None
    _ensure_mat = ensure_materials_func or ensure_world_materials
    _ensure_mat(obj, prefs=prefs, atlas=atlas, used_chunk_ids=used_chunk_ids)

    # Voxel meshes always bake true 3D biomes; tag them so the biome panel's
    # WORLD preset is selected instead of the uniform Plains fallback.
    try:
        from ..materials.biome.updater import mark_world_biome
    except (ImportError, ValueError):
        try:
            from utils.materials.biome.updater import mark_world_biome
        except Exception:
            mark_world_biome = None
    if mark_world_biome is not None:
        mark_world_biome(obj, storage)

    # 4. Extract unculled VoxelPointCloud and ensure child companion object
    _ensure_cloud = ensure_cloud_func or ensure_voxel_child_cloud
    cloud_obj = _ensure_cloud(
        parent_obj=obj,
        storage=storage,
        origin_centered=origin_centered,
        initial_hidden=True,
    )
    cloud_count = len(cloud_obj.data.vertices) if cloud_obj and getattr(cloud_obj, "data", None) and hasattr(cloud_obj.data, "vertices") else 0

    # 5. Set active in viewport
    if context and hasattr(context, "view_layer"):
        obj.select_set(True)
        context.view_layer.objects.active = obj

    stats = {
        "object_name": obj.name,
        "vertex_count": len(b_mesh.vertices) if hasattr(b_mesh, "vertices") else 0,
        "quad_count": getattr(mesh_data, "quad_count", 0),
        "polygon_count": len(b_mesh.polygons) if hasattr(b_mesh, "polygons") else 0,
        "materials_count": len(b_mesh.materials) if hasattr(b_mesh, "materials") else 0,
        "voxel_count": cloud_count,
        "voxel_cloud_name": cloud_obj.name if cloud_obj else None,
        "meshing_time_ms": round(elapsed_ms, 2),
    }

    return obj, stats


def ingest_voxel_world(
    storage: Any,
    context: Optional[Any] = None,
    name: str = "MTK_World",
    prefs=None,
    model_db: Optional[Any] = None,
    atlas: Optional[Any] = None,
    biome_resolver: Optional[Any] = None,
    ctm_solver: Optional[Any] = None,
    material_mode: str = "ATLAS",
    enable_ao: bool = True,
    mesh_fluids: bool = True,
    weld_vertices: bool = True,
    origin_centered: bool = True,
    reuse_existing: bool = True,
    progress_callback: Optional[Any] = None,
) -> Tuple[Any, Dict[str, Any]]:
    """
    Complete synchronous end-to-end Voxel World Ingestion Pipeline:
    1. Meshes VoxelStorage using cached Model Database, Atlas/Standalone, CTM Solver, and Biome Resolver
    2. Injects high-throughput geometry into a Blender Mesh object
    3. Builds and binds full Atlas Chunk PBR Materials or Standalone BSDF Materials
    Returns (bpy_object, stats_dict).
    """
    try:
        from ...bridge.world import mesh_voxel_storage
    except (ImportError, ValueError):
        from bridge.world import mesh_voxel_storage

    mesh_data, elapsed_ms = mesh_voxel_storage(
        storage=storage,
        model_db=model_db,
        atlas=atlas,
        biome_resolver=biome_resolver,
        ctm_solver=ctm_solver,
        prefs=prefs,
        enable_ao=enable_ao,
        mesh_fluids=mesh_fluids,
        weld_vertices=weld_vertices,
        origin_centered=origin_centered,
        progress_callback=progress_callback,
        material_mode=material_mode,
    )

    return apply_voxel_mesh_to_blender(
        mesh_data=mesh_data,
        storage=storage,
        elapsed_ms=elapsed_ms,
        context=context,
        name=name,
        prefs=prefs,
        atlas=atlas,
        origin_centered=origin_centered,
        reuse_existing=reuse_existing,
        material_mode=material_mode,
    )


def create_debug_world_object(
    context=None,
    name: str = "MTK_Debug_World",
    prefs=None,
    model_db=None,
    atlas=None,
    biome_resolver=None,
    enable_ao: bool = True,
    mesh_fluids: bool = True,
    weld_vertices: bool = True,
    origin_centered: bool = True,
    reuse_existing: bool = True,
    config=None,
    culler=None,
    states=None,
    stack=None,
    progress_callback: Optional[Any] = None,
) -> Tuple[Any, Dict[str, Any]]:
    """
    Meshes the canonical debug world and creates/updates a Blender Mesh Object in the active scene,
    binding all precompiled Atlas chunk PBR materials and shaders.
    Returns (bpy_object, stats_dict).
    """
    try:
        from ...bridge.debug import load_debug_world_storage
    except (ImportError, ValueError):
        from bridge.debug import load_debug_world_storage

    storage = load_debug_world_storage(prefs=prefs, states=states, stack=stack)

    obj, stats = ingest_voxel_world(
        storage=storage,
        context=context,
        name=name,
        prefs=prefs,
        model_db=model_db,
        atlas=atlas,
        biome_resolver=biome_resolver,
        enable_ao=enable_ao,
        mesh_fluids=mesh_fluids,
        weld_vertices=weld_vertices,
        origin_centered=origin_centered,
        reuse_existing=reuse_existing,
        progress_callback=progress_callback,
    )

    # Ensure backwards compatibility for dict keys
    if "elapsed_ms" not in stats and "meshing_time_ms" in stats:
        stats["elapsed_ms"] = stats["meshing_time_ms"]

    return obj, stats

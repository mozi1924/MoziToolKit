"""
MoziToolKit Unified Voxel World Bridge Module.

Authoritative offline pipeline for converting any VoxelStorage (embedded debug world,
future Anvil save files, schematics, or sync streams) into fully modeled, textured,
and shaded Blender objects with Atlas PBR materials and Biome tinting.
Completely host-agnostic and decoupled from WebSocket network synchronization.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .mesh import inject_mesh_data
from .point_cloud import ensure_voxel_child_cloud, inject_voxel_point_cloud
from .assets import (
    get_cache_dir,
    load_baked_atlas_from_cache,
    load_baked_model_database,
    load_biome_resolver_from_cache,
)

logger = logging.getLogger("MoziToolKit.Bridge.World")

from .engine import get_libmtk, has_libmtk, require_libmtk


def _get_libmtk():
    return get_libmtk()


def __getattr__(name: str) -> Any:
    if name == "libmtk_py":
        return get_libmtk()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def get_world_pipeline_assets(prefs=None) -> Tuple[Optional[Any], Optional[Any], Optional[Any]]:
    """
    Acquires precompiled assets required for high-fidelity world meshing:
    Returns (model_db, atlas, biome_resolver).
    """
    model_db = load_baked_model_database(prefs)
    atlas = load_baked_atlas_from_cache(prefs)
    biome_resolver = load_biome_resolver_from_cache(prefs)
    return model_db, atlas, biome_resolver


def ensure_world_materials(
    world_obj: Any,
    prefs=None,
    atlas: Optional[Any] = None,
    used_chunk_ids: Optional[Any] = None,
) -> None:
    """
    Ensures that the unified world mesh object has corresponding Atlas Chunk materials
    and shaders assigned for chunks actually present in the world geometry, hooking up
    albedo, normals, specular, emission, animated sprites, and biome tinting.
    Avoids loading textures or instantiating materials for unused atlas chunks.
    """
    try:
        import bpy
    except ImportError:
        return

    if not world_obj or world_obj.type != "MESH":
        return

    try:
        from ..utils.materials.builder.atlas_builder import build_atlas_chunk_material
        from ..utils.materials.builder import ensure_material_node_tree
    except (ImportError, ValueError):
        try:
            from utils.materials.builder.atlas_builder import build_atlas_chunk_material
            from utils.materials.builder import ensure_material_node_tree
        except (ImportError, ValueError):
            build_atlas_chunk_material = None
            ensure_material_node_tree = lambda m: getattr(m, "node_tree", None)

    mesh = world_obj.data
    cache_dir = get_cache_dir(prefs)
    atlas_dir = cache_dir / "atlas"
    atlas_mapping_path = atlas_dir / "atlas_mapping.json"

    # 1. Resolve which Chunk IDs are actually present in the mesh geometry
    target_chunk_ids: Optional[set[int]] = None
    if used_chunk_ids is not None:
        target_chunk_ids = {int(c) for c in used_chunk_ids}
    elif hasattr(mesh, "polygons") and len(mesh.polygons) > 0:
        if hasattr(mesh.polygons, "foreach_get"):
            try:
                import numpy as np
                poly_mats = np.empty(len(mesh.polygons), dtype=np.int32)
                mesh.polygons.foreach_get("material_index", poly_mats)
                target_chunk_ids = {int(x) for x in np.unique(poly_mats).tolist()}
            except Exception:
                try:
                    poly_mats = [0] * len(mesh.polygons)
                    mesh.polygons.foreach_get("material_index", poly_mats)
                    target_chunk_ids = {int(x) for x in poly_mats}
                except Exception:
                    target_chunk_ids = {getattr(p, "material_index", 0) for p in mesh.polygons}
        else:
            target_chunk_ids = {getattr(p, "material_index", 0) for p in mesh.polygons}

    # 2. Bind Precompiled Atlas Chunk Materials for used chunks only
    if (atlas is not None or atlas_mapping_path.exists()) and build_atlas_chunk_material is not None:
        try:
            # Query chunk metadata from BakedAtlas (Rust SSOT) or fallback to mapping JSON
            chunk_meta_map: dict[int, dict[str, Any]] = {}
            if atlas is not None and hasattr(atlas, "get_chunk_info"):
                if target_chunk_ids is not None:
                    for cid in sorted(target_chunk_ids):
                        cm = atlas.get_chunk_info(cid)
                        if cm is not None:
                            chunk_meta_map[cid] = cm
                else:
                    all_chunks = atlas.get_all_chunks_info() if hasattr(atlas, "get_all_chunks_info") else []
                    for cm in all_chunks:
                        chunk_meta_map[cm["chunk_id"]] = cm
            elif atlas_mapping_path.exists():
                atlas_data = json.loads(atlas_mapping_path.read_text(encoding="utf-8"))
                for idx, cm in enumerate(atlas_data.get("chunks", [])):
                    cid = cm.get("chunk_id", idx)
                    if target_chunk_ids is None or cid in target_chunk_ids:
                        chunk_meta_map[cid] = cm

            if chunk_meta_map:
                colormaps_dir = cache_dir / "colormaps"
                colormaps = {}
                if colormaps_dir.exists():
                    for cm_name in ("grass", "foliage", "dry_foliage"):
                        p = colormaps_dir / f"{cm_name}.png"
                        if p.exists():
                            colormaps[cm_name] = p

                manifest_path = cache_dir / "cache_manifest.json"
                manifest_fp = None
                if manifest_path.exists():
                    try:
                        manifest_fp = json.loads(manifest_path.read_text(encoding="utf-8")).get("fingerprint")
                    except Exception:
                        pass

                if len(mesh.materials) == 1 and mesh.materials[0] and mesh.materials[0].name.startswith("MTK:Default"):
                    mesh.materials.clear()

                max_chunk_id = max(chunk_meta_map.keys())
                while len(mesh.materials) <= max_chunk_id:
                    mesh.materials.append(None)

                for chunk_id, cm in chunk_meta_map.items():
                    cat = cm.get("category", "blocks")
                    c_idx = cm.get("category_chunk_index", chunk_id + 1)
                    is_anim = cm.get("is_animated", False)
                    stem = cm.get("file_stem") or (f"{cat}_anim_chunk_{c_idx:03}" if is_anim else f"{cat}_chunk_{c_idx:03}")

                    albedo_file = atlas_dir / f"{stem}.png"
                    normal_file = atlas_dir / f"{stem}_n.png" if cm.get("has_normal") else None
                    specular_file = atlas_dir / f"{stem}_s.png" if cm.get("has_specular") else None
                    overlay_file = atlas_dir / f"{stem}_overlay.png" if cm.get("has_overlay") else None
                    chunk_width = float(cm.get("width", 4096))
                    chunk_height = float(cm.get("height", 4096))

                    mat = build_atlas_chunk_material(
                        chunk_id=chunk_id,
                        albedo_path=albedo_file,
                        normal_path=normal_file,
                        specular_path=specular_file,
                        overlay_path=overlay_file,
                        colormaps=colormaps,
                        category=cat,
                        category_chunk_index=c_idx,
                        is_animated=is_anim,
                        stack_fingerprint=manifest_fp,
                        use_attribute_node=False,
                        atlas_width=chunk_width,
                        atlas_height=chunk_height,
                        tile_width=16.0,
                        tile_height=16.0,
                    )

                    if mesh.materials[chunk_id] != mat:
                        mesh.materials[chunk_id] = mat

                # Clear unused material slots that are not present in chunk_meta_map
                for idx in range(len(mesh.materials)):
                    if idx not in chunk_meta_map and mesh.materials[idx] is not None:
                        mesh.materials[idx] = None

                if len(mesh.materials) > 0:
                    return
        except Exception as e:
            logger.warning(f"Failed binding Atlas chunk materials: {e}")

    # 2. Fallback: Default shaded material with vertex colors / AO
    default_mat_name = "MTK:Default:AO"
    mat = bpy.data.materials.get(default_mat_name)
    if mat is None:
        mat = bpy.data.materials.new(name=default_mat_name)
        ensure_material_node_tree(mat)
        nodes = mat.node_tree.nodes
        nodes.clear()
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (200, 0)
        output = nodes.new("ShaderNodeOutputMaterial")
        output.location = (500, 0)
        mat.node_tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

        attr_node = nodes.new("ShaderNodeAttribute")
        attr_node.location = (-150, 0)
        attr_node.attribute_name = "color"
        mat.node_tree.links.new(attr_node.outputs["Color"], bsdf.inputs["Base Color"])

    if len(mesh.materials) == 0:
        mesh.materials.append(mat)
    elif mesh.materials[0] is None:
        mesh.materials[0] = mat


def mesh_voxel_storage(
    storage: Any,
    config: Optional[Any] = None,
    model_db: Optional[Any] = None,
    atlas: Optional[Any] = None,
    biome_resolver: Optional[Any] = None,
    prefs=None,
    enable_ao: bool = True,
    mesh_fluids: bool = True,
    weld_vertices: bool = True,
    origin_centered: bool = True,
    num_threads: Optional[int] = None,
) -> Tuple[Any, float]:
    """
    Meshes a VoxelStorage volume with full model resolution, atlas UV remapping,
    culling, and biome tinting.
    Returns (mesh_data, elapsed_ms).
    """
    mtk = require_libmtk("mesh_voxel_storage")

    # Auto-load cached assets if not explicitly passed
    if model_db is None or atlas is None or biome_resolver is None:
        cached_model_db, cached_atlas, cached_biome_resolver = get_world_pipeline_assets(prefs)
        model_db = model_db or cached_model_db
        atlas = atlas or cached_atlas
        biome_resolver = biome_resolver or cached_biome_resolver

    # Auto-resolve thread count from preferences if not explicitly set
    if num_threads is None:
        if prefs is None:
            try:
                from ..utils.system.dependencies import get_prefs
                prefs = get_prefs()
            except Exception:
                pass
        if prefs is not None:
            num_threads = getattr(prefs, "thread_count", 0) or None

    if config is None:
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
    elif num_threads is not None and hasattr(config, "num_threads"):
        config.num_threads = num_threads

    culler = mtk.FaceCuller() if hasattr(mtk, "FaceCuller") else None

    t0 = time.perf_counter()
    if hasattr(mtk, "VoxelWorld") and hasattr(mtk.VoxelWorld, "from_storage"):
        try:
            world = mtk.VoxelWorld.from_storage(
                storage=storage,
                config=config,
                culler=culler,
                model_db=model_db,
                unified_mesh=True,
                num_threads=num_threads,
            )
        except TypeError:
            world = mtk.VoxelWorld.from_storage(
                storage=storage,
                config=config,
                culler=culler,
                model_db=model_db,
                unified_mesh=True,
            )
        mesh_data = world.rebuild_all()
    else:
        mesh_data = mtk.SectionMesher.mesh_world(storage, config, culler, model_db)
    t1 = time.perf_counter()

    elapsed_ms = (t1 - t0) * 1000.0
    return mesh_data, elapsed_ms


def ingest_voxel_world(
    storage: Any,
    context: Optional[Any] = None,
    name: str = "MTK_World",
    prefs=None,
    model_db: Optional[Any] = None,
    atlas: Optional[Any] = None,
    biome_resolver: Optional[Any] = None,
    enable_ao: bool = True,
    mesh_fluids: bool = True,
    weld_vertices: bool = True,
    origin_centered: bool = True,
    reuse_existing: bool = True,
) -> Tuple[Any, Dict[str, Any]]:
    """
    Complete end-to-end Voxel World Ingestion Pipeline:
    1. Meshes VoxelStorage using cached Model Database, Atlas, and Biome Resolver
    2. Injects high-throughput geometry into a Blender Mesh object
    3. Builds and binds full Atlas Chunk PBR Materials and Shaders
    Returns (bpy_object, stats_dict).
    """
    try:
        import bpy
    except ImportError:
        raise RuntimeError("bpy is not available.")

    if context is None:
        context = bpy.context

    # 1. Mesh the voxel volume
    mesh_data, elapsed_ms = mesh_voxel_storage(
        storage=storage,
        model_db=model_db,
        atlas=atlas,
        biome_resolver=biome_resolver,
        prefs=prefs,
        enable_ao=enable_ao,
        mesh_fluids=mesh_fluids,
        weld_vertices=weld_vertices,
        origin_centered=origin_centered,
    )

    # 2. Acquire or create Blender object
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

    # 3. Inject topology, positions, UVs, normals, materials
    inject_mesh_data(
        b_mesh,
        mesh_data,
        update_topology=True,
        update_normals=True,
    )

    # 4. Bind only used Atlas chunk materials & shaders
    used_chunk_ids = mesh_data.used_materials() if hasattr(mesh_data, "used_materials") else None
    ensure_world_materials(obj, prefs=prefs, atlas=atlas, used_chunk_ids=used_chunk_ids)

    # 5. Extract unculled VoxelPointCloud and ensure child companion object
    cloud_obj = ensure_voxel_child_cloud(
        parent_obj=obj,
        storage=storage,
        origin_centered=origin_centered,
        initial_hidden=True,
    )
    cloud_count = len(cloud_obj.data.vertices) if cloud_obj and cloud_obj.data else 0

    # 6. Set active in viewport
    if context and hasattr(context, "view_layer"):
        obj.select_set(True)
        context.view_layer.objects.active = obj

    stats = {
        "object_name": obj.name,
        "vertex_count": len(b_mesh.vertices),
        "quad_count": mesh_data.quad_count,
        "polygon_count": len(b_mesh.polygons),
        "materials_count": len(b_mesh.materials),
        "voxel_count": cloud_count,
        "voxel_cloud_name": cloud_obj.name if cloud_obj else None,
        "meshing_time_ms": round(elapsed_ms, 2),
    }

    return obj, stats

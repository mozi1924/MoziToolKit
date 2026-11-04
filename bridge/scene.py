"""
MoziToolKit Scene Interchange Bridge Module.

Encapsulates .mtkscene package reading, sparse voxel ingestion, tree-shaken
mini-atlas extraction, and end-to-end scene interchange export.
Completely host-agnostic and decoupled from Blender UI/host objects.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .assets.cache import open_active_asset_cache
from .engine import get_libmtk, require_libmtk
from .world import mesh_voxel_storage

logger = logging.getLogger("MoziToolKit.Bridge.Scene")


def inspect_scene_package(path: str | Path) -> Dict[str, Any]:
    """
    Inspects an .mtkscene package header and metadata manifest without
    decoding large voxel grids or texture payloads.
    """
    mtk = require_libmtk("inspect_scene_package")
    target_path = str(Path(path).resolve())

    reader = mtk.ScenePackageReader.open(target_path)
    meta = reader.metadata
    return meta.to_dict()


def read_scene_package(
    path: str | Path,
    origin_centered: bool = True,
    z_up: bool = True,
) -> Dict[str, Any]:
    """
    Reads an .mtkscene package into memory:
    - metadata (dict)
    - point_cloud (VoxelPointCloud)
    - models (BakedModelDatabase or None)
    - atlas (BakedAtlas or None)
    - atlas_mapping_json (str or None)
    - texture_names (list[str])
    - biome_resolver (BiomeResolver or None)
    - colormaps (VanillaColormaps or None)
    - dynamic_entity_slots (dict or None)
    - ctm_solver (CtmSolver or None)
    - reader (ScenePackageReader)
    """
    mtk = require_libmtk("read_scene_package")
    target_path = str(Path(path).resolve())

    reader = mtk.ScenePackageReader.open(target_path)
    if hasattr(reader, "unpack"):
        bundle = reader.unpack(origin_centered=origin_centered, z_up=z_up)
        bundle["reader"] = reader
        return bundle

    meta = reader.metadata.to_dict()
    point_cloud = reader.read_point_cloud(origin_centered=origin_centered, z_up=z_up)
    models = reader.read_models()
    atlas = reader.read_atlas()
    atlas_mapping_json = reader.read_atlas_mapping_json()
    texture_names = reader.get_atlas_texture_names()
    biome_resolver = reader.read_biome_resolver() if hasattr(reader, "read_biome_resolver") else None
    ctm_solver = reader.read_ctm_solver() if hasattr(reader, "read_ctm_solver") else None
    colormaps = reader.read_colormaps() if hasattr(reader, "read_colormaps") else None
    dynamic_entity_slots = reader.read_dynamic_entity_slots() if hasattr(reader, "read_dynamic_entity_slots") else None

    return {
        "metadata": meta,
        "point_cloud": point_cloud,
        "models": models,
        "atlas": atlas,
        "atlas_mapping_json": atlas_mapping_json,
        "texture_names": texture_names,
        "biome_resolver": biome_resolver,
        "colormaps": colormaps,
        "dynamic_entity_slots": dynamic_entity_slots,
        "ctm_solver": ctm_solver,
        "reader": reader,
    }


def load_and_mesh_scene_package(
    path: str | Path,
    prefs=None,
    enable_ao: bool = True,
    mesh_fluids: bool = True,
    weld_vertices: bool = True,
    origin_centered: bool = True,
    enable_animated_textures: bool = True,
    num_threads: Optional[int] = None,
    z_up: bool = True,
    allow_host_fallback: bool = False,
    enable_ctm: bool = True,
) -> Dict[str, Any]:
    """
    High-level headless scene loader: reads .mtkscene, reconstructs VoxelStorage,
    and meshes the geometry with the self-contained mini-atlas and tree-shaken models.
    Supports animated texture toggle via dual-volume mini-atlas.
    Returns dictionary with mesh_data, point_cloud, storage, metadata, atlas, and reader.
    """
    t0 = time.perf_counter()
    data = read_scene_package(path, origin_centered=origin_centered, z_up=z_up)
    point_cloud = data["point_cloud"]
    models = data["models"]
    atlas = data["atlas"]
    reader = data["reader"]
    metadata = data["metadata"]
    biome_resolver = data.get("biome_resolver")
    colormaps = data.get("colormaps")
    ctm_solver = data.get("ctm_solver") if enable_ctm else None
    has_pkg_ctm = ctm_solver is not None

    storage = point_cloud.to_storage()

    degraded = False
    if models is None or atlas is None:
        if not allow_host_fallback:
            raise ValueError(
                f"Scene package '{path}' is incomplete: missing required models or atlas chunks. "
                "Host fallback is disabled."
            )
        logger.warning(
            "Scene package '%s' is incomplete (missing models or atlas); falling back to host cache assets.",
            path,
        )
        degraded = True
    elif biome_resolver is None and allow_host_fallback:
        degraded = True

    # Mesh voxel volume using package-embedded models and atlas
    resolve_prefs = allow_host_fallback and (models is None or atlas is None or biome_resolver is None)
    resolve_ctm = enable_ctm and allow_host_fallback and (not has_pkg_ctm)
    mesh_data, mesher_ms = mesh_voxel_storage(
        storage=storage,
        model_db=models,
        atlas=atlas,
        biome_resolver=biome_resolver,
        colormaps=colormaps,
        ctm_solver=ctm_solver,
        prefs=prefs,
        enable_ao=enable_ao,
        mesh_fluids=mesh_fluids,
        weld_vertices=weld_vertices,
        origin_centered=origin_centered,
        enable_animated_textures=enable_animated_textures,
        num_threads=num_threads,
        resolve_prefs=resolve_prefs,
        resolve_ctm=resolve_ctm,
    )
    total_ms = (time.perf_counter() - t0) * 1000.0

    dynamic_entity_slots = data.get("dynamic_entity_slots")
    if hasattr(mesh_data, "dynamic_entity_slots") and getattr(mesh_data, "dynamic_entity_slots", None) is None and dynamic_entity_slots:
        try:
            mesh_data.dynamic_entity_slots = dynamic_entity_slots
        except Exception:
            pass

    return {
        "mesh_data": mesh_data,
        "point_cloud": point_cloud,
        "storage": storage,
        "metadata": metadata,
        "models": models,
        "atlas": atlas,
        "biome_resolver": biome_resolver,
        "colormaps": colormaps,
        "dynamic_entity_slots": dynamic_entity_slots,
        "ctm_solver": ctm_solver,
        "reader": reader,
        "degraded": degraded,
        "mesher_ms": mesher_ms,
        "total_ms": total_ms,
    }


def export_scene_package(
    output_path: str | Path,
    point_cloud: Any,
    prefs=None,
    options: Optional[Dict[str, Any]] = None,
    max_atlas_size: int = 2048,
    mip_level: int = 0,
    dynamic_entity_atlases: Optional[Dict[int, bytes]] = None,
    ctm_solver: Optional[Any] = None,
    enable_ctm: Optional[bool] = None,
    dynamic_entity_slots: Optional[Dict[str, Tuple[int, int]]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Exports a live VoxelPointCloud into a self-contained .mtkscene interchange package.
    Automatically tree-shakes block models, crops referenced textures from the active
    asset cache and dynamic entity buffers into a compact Scene Mini-Atlas, remaps model UVs,
    and compresses into .mtkscene.
    """
    mtk = require_libmtk("export_scene_package")
    cache = open_active_asset_cache(prefs)
    if cache is None:
        raise RuntimeError(
            "Active asset cache (.mtkcache) is required to build scene mini-atlas and export .mtkscene. "
            "Please precompile or ensure an active resource pack cache exists in preferences."
        )

    out_p = Path(output_path).resolve()
    if out_p.parent:
        out_p.parent.mkdir(parents=True, exist_ok=True)

    # Merge explicitly passed options dict with keyword args
    opts = dict(options) if options else {}
    for k, v in kwargs.items():
        opts.setdefault(k, v)

    resolved_enable_ctm = opts.get("enable_ctm", enable_ctm)
    resolved_ctm_solver = opts.get("ctm_solver", ctm_solver)

    if resolved_enable_ctm is None and prefs is not None:
        raw = getattr(prefs, "enable_ctm", True)
        resolved_enable_ctm = bool(raw) if isinstance(raw, bool) else True
    elif resolved_enable_ctm is not None:
        resolved_enable_ctm = bool(resolved_enable_ctm)

    # Older caches may predate the packaged `ctm/rules` chunk. If the active cache has
    # no CTM rules but the live pack stack does, fall back to the live solver so a stale
    # cache does not silently strip working connected textures from the export.
    if resolved_enable_ctm and resolved_ctm_solver is None and prefs is not None:
        cache_has_ctm = getattr(cache, "has_ctm_rules", None)
        cache_is_missing_ctm = callable(cache_has_ctm) and not cache_has_ctm()
        if cache_is_missing_ctm:
            from .assets.pack import get_configured_ctm_solver

            resolved_ctm_solver = get_configured_ctm_solver(prefs, force=True)
            if resolved_ctm_solver is not None:
                logger.warning(
                    "Active asset cache has no packaged CTM rules; using the live resource-pack CTM solver for scene export. Recompile the cache to make it self-contained."
                )

    export_options = {
        "max_atlas_size": opts.get("max_atlas_size", max_atlas_size),
        "mip_level": opts.get("mip_level", mip_level),
        "dynamic_entity_atlases": opts.get("dynamic_entity_atlases", dynamic_entity_atlases),
        "ctm_solver": resolved_ctm_solver,
        "enable_ctm": resolved_enable_ctm,
        "dynamic_entity_slots": opts.get("dynamic_entity_slots", dynamic_entity_slots),
    }

    meta = mtk.export_scene_package(
        output_path=str(out_p),
        point_cloud=point_cloud,
        asset_cache=cache,
        options=export_options,
    )

    return meta.to_dict()

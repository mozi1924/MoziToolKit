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
    - reader (ScenePackageReader)
    """
    mtk = require_libmtk("read_scene_package")
    target_path = str(Path(path).resolve())

    reader = mtk.ScenePackageReader.open(target_path)
    meta = reader.metadata.to_dict()
    point_cloud = reader.read_point_cloud(origin_centered=origin_centered, z_up=z_up)
    models = reader.read_models()
    atlas = reader.read_atlas()
    atlas_mapping_json = reader.read_atlas_mapping_json()
    texture_names = reader.get_atlas_texture_names()

    return {
        "metadata": meta,
        "point_cloud": point_cloud,
        "models": models,
        "atlas": atlas,
        "atlas_mapping_json": atlas_mapping_json,
        "texture_names": texture_names,
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

    storage = point_cloud.to_storage()

    # Mesh voxel volume using package-embedded models and atlas
    resolve_prefs = models is None or atlas is None
    mesh_data, mesher_ms = mesh_voxel_storage(
        storage=storage,
        model_db=models,
        atlas=atlas,
        prefs=prefs,
        enable_ao=enable_ao,
        mesh_fluids=mesh_fluids,
        weld_vertices=weld_vertices,
        origin_centered=origin_centered,
        enable_animated_textures=enable_animated_textures,
        num_threads=num_threads,
        resolve_prefs=resolve_prefs,
        resolve_ctm=False,
    )
    total_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "mesh_data": mesh_data,
        "point_cloud": point_cloud,
        "storage": storage,
        "metadata": metadata,
        "models": models,
        "atlas": atlas,
        "reader": reader,
        "mesher_ms": mesher_ms,
        "total_ms": total_ms,
    }


def export_scene_package(
    output_path: str | Path,
    point_cloud: Any,
    prefs=None,
    max_atlas_size: int = 2048,
    mip_level: int = 0,
    dynamic_entity_atlases: Optional[Dict[int, bytes]] = None,
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

    meta = mtk.export_scene_package(
        str(out_p),
        point_cloud,
        cache,
        max_atlas_size,
        mip_level,
        dynamic_entity_atlases,
    )

    return meta.to_dict()

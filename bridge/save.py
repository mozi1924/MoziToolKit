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

from .assets import get_configured_ctm_solver
from .engine import get_libmtk, has_libmtk, require_libmtk
from .world import get_world_pipeline_assets

logger = logging.getLogger("MoziToolKit.Bridge.Save")



def inspect_minecraft_save(path: str | Path) -> Dict[str, Any]:
    """
    Inspects a Minecraft save folder or level.dat path, returning world metadata
    and discovered dimensions without loading chunk geometry.
    """
    mtk = require_libmtk("inspect_minecraft_save")
    target_path = str(Path(path).resolve())

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
    material_mode: str = "ATLAS",
    enable_ctm: bool = True,
    enable_animated_textures: Optional[bool] = None,
    ctm_solver: Optional[Any] = None,
    skin_cache_dir: Optional[str] = None,
    resolve_prefs: bool = True,
    resolve_ctm: bool = True,
) -> Tuple[Any, Dict[str, Any], Any, float]:
    """
    Directly streams and meshes a bounded 3D selection from an Anvil save.
    Returns (mesh_data, level_meta_dict, storage, elapsed_ms).
    """
    mtk = require_libmtk("load_and_mesh_minecraft_save")
    target_path = str(Path(world_dir).resolve())

    # Auto-resolve pipeline assets if not supplied. AsyncTask callers pass all
    # three explicitly and set resolve_prefs=False so this worker never touches bpy.
    if resolve_prefs and (model_db is None or atlas is None or biome_resolver is None):
        cached_mdb, cached_atlas, cached_resolver = get_world_pipeline_assets(prefs)
        model_db = model_db or cached_mdb
        atlas = atlas or cached_atlas
        biome_resolver = biome_resolver or cached_resolver

    # Thread count resolution
    if resolve_prefs and num_threads is None and prefs is not None:
        raw_threads = getattr(prefs, "thread_count", 0)
        num_threads = raw_threads if isinstance(raw_threads, int) and not isinstance(raw_threads, bool) and raw_threads > 0 else None

    if resolve_ctm and ctm_solver is None and enable_ctm:
        ctm_solver = get_configured_ctm_solver(prefs)

    anim_tex_enabled = enable_animated_textures
    if anim_tex_enabled is None:
        raw_val = getattr(prefs, "enable_animated_textures", True) if (resolve_prefs and prefs) else True
        anim_tex_enabled = raw_val if isinstance(raw_val, bool) else True
    else:
        anim_tex_enabled = bool(anim_tex_enabled)

    config_kwargs = {
        "enable_ao": enable_ao,
        "mesh_fluids": mesh_fluids,
        "z_up_coordinates": True,
        "origin_centered": origin_centered,
        "weld_vertices": weld_vertices,
        "num_threads": num_threads,
        "atlas": atlas,
        "biome_resolver": biome_resolver,
        "enable_animated_textures": anim_tex_enabled,
    }
    if ctm_solver is not None:
        config_kwargs["ctm_solver"] = ctm_solver

    config = mtk.MesherConfig(**config_kwargs)

    culler = mtk.FaceCuller() if hasattr(mtk, "FaceCuller") else None

    wrapped_cb = None
    if progress_callback is not None:
        from .progress import wrap_progress_callback
        wrapped_cb = wrap_progress_callback(progress_callback)

    t0 = time.perf_counter()
    call_kwargs: Dict[str, Any] = {
        "world_dir": target_path,
        "dimension": dimension,
        "min_block": min_block,
        "max_block": max_block,
        "config": config,
        "culler": culler,
        "model_db": model_db,
        "num_threads": num_threads,
        "callback": wrapped_cb,
    }
    if skin_cache_dir is None:
        try:
            from .assets import get_cache_dir
            sc = get_cache_dir(prefs if resolve_prefs else None) / "skins"
            sc.mkdir(parents=True, exist_ok=True)
            skin_cache_dir = str(sc)
        except Exception as e:
            logger.debug("Failed configuring skin cache dir in save bridge: %s", e)

    if skin_cache_dir is not None:
        call_kwargs["skin_cache_dir"] = skin_cache_dir

    try:
        from ..utils.system.network import sync_system_proxies
        sync_system_proxies()
    except Exception:
        pass

    mesh_data, level_meta, storage = mtk.load_and_mesh_minecraft_save(**call_kwargs)
    t1 = time.perf_counter()
    elapsed_ms = (t1 - t0) * 1000.0

    if getattr(mesh_data, "profile", None) is not None:
        from .diagnostics import record_operation_profile

        record_operation_profile(f"Import Save ({dimension})", mesh_data.profile)

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


__all__ = [
    "inspect_minecraft_save",
    "load_and_mesh_minecraft_save",
]

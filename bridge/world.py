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

from .assets import (
    get_cache_fingerprint,
    get_cache_timestamp,
    ensure_atlas_textures_extracted,
    load_baked_atlas_from_cache,
    load_atlas_mapping_from_cache,
    load_baked_model_database,
    load_biome_resolver_from_cache,
    get_active_cache_package_path,
    get_configured_ctm_solver,
)

logger = logging.getLogger("MoziToolKit.Bridge.World")

from .engine import get_libmtk, has_libmtk, require_libmtk


def _get_libmtk():
    return get_libmtk()


def __getattr__(name: str) -> Any:
    if name == "libmtk_py":
        return get_libmtk()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


_WORLD_PIPELINE_ASSETS_CACHE: Optional[Tuple[Any, Any, Any]] = None
_WORLD_PIPELINE_FP_CACHE: Optional[str] = None
_WORLD_PIPELINE_TS_CACHE: float = 0.0

# Reused across rebuilds: the Rust `FaceCuller` owns a state-string keyed metadata
# cache, so constructing a fresh instance per call forces it to re-derive cull
# metadata for every unique blockstate. The cull modes are fixed here, so a single
# instance is safe for the whole session.
_SHARED_FACE_CULLER: Optional[Any] = None
_SHARED_FACE_CULLER_OWNER: Optional[Any] = None


def get_shared_face_culler(mtk: Optional[Any] = None) -> Optional[Any]:
    """Returns a process-wide `FaceCuller` instance (or None when unavailable).

    The instance is tied to the native module that created it, so reloading the
    extension produces a fresh culler instead of reusing a stale native object.
    """
    global _SHARED_FACE_CULLER, _SHARED_FACE_CULLER_OWNER
    mtk = mtk or get_libmtk()
    if mtk is None or not hasattr(mtk, "FaceCuller"):
        return None
    if _SHARED_FACE_CULLER is not None and _SHARED_FACE_CULLER_OWNER is mtk:
        return _SHARED_FACE_CULLER
    _SHARED_FACE_CULLER = mtk.FaceCuller()
    _SHARED_FACE_CULLER_OWNER = mtk
    return _SHARED_FACE_CULLER


def reset_shared_face_culler() -> None:
    """Drops the shared culler so the next call rebuilds (and re-warms) its cache."""
    global _SHARED_FACE_CULLER, _SHARED_FACE_CULLER_OWNER
    _SHARED_FACE_CULLER = None
    _SHARED_FACE_CULLER_OWNER = None


def invalidate_world_pipeline_assets() -> None:
    """Invalidates in-memory cached pipeline assets tuple."""
    global _WORLD_PIPELINE_ASSETS_CACHE, _WORLD_PIPELINE_FP_CACHE, _WORLD_PIPELINE_TS_CACHE
    _WORLD_PIPELINE_ASSETS_CACHE = None
    _WORLD_PIPELINE_FP_CACHE = None
    _WORLD_PIPELINE_TS_CACHE = 0.0


def get_world_pipeline_assets(prefs=None) -> Tuple[Optional[Any], Optional[Any], Optional[Any]]:
    """
    Acquires precompiled assets required for high-fidelity world meshing:
    Returns (model_db, atlas, biome_resolver).
    Memoized in memory against the active package fingerprint and timestamp.
    """
    global _WORLD_PIPELINE_ASSETS_CACHE, _WORLD_PIPELINE_FP_CACHE, _WORLD_PIPELINE_TS_CACHE
    fp = get_cache_fingerprint(prefs)
    ts = get_cache_timestamp(prefs)
    if (
        _WORLD_PIPELINE_ASSETS_CACHE is not None
        and _WORLD_PIPELINE_FP_CACHE == fp
        and _WORLD_PIPELINE_TS_CACHE == ts
        and fp is not None
    ):
        return _WORLD_PIPELINE_ASSETS_CACHE

    model_db = load_baked_model_database(prefs, verify_fingerprint=False)
    atlas = load_baked_atlas_from_cache(prefs)
    biome_resolver = load_biome_resolver_from_cache(prefs)
    _WORLD_PIPELINE_ASSETS_CACHE = (model_db, atlas, biome_resolver)
    _WORLD_PIPELINE_FP_CACHE = fp
    _WORLD_PIPELINE_TS_CACHE = ts
    return _WORLD_PIPELINE_ASSETS_CACHE


def prepare_world_mesh_context(prefs=None) -> Dict[str, Any]:
    """Resolve every asset/config value a background mesher needs, on the main thread.

    The returned dict is plain Python/Rust data: it contains no Blender RNA
    objects, so it is safe to pass into an AsyncTask worker. Call this only after
    the asset cache has been verified/precompiled on the main thread.
    """
    model_db, atlas, biome_resolver = get_world_pipeline_assets(prefs)
    active_pkg = get_active_cache_package_path(prefs)
    ctm_solver = get_configured_ctm_solver(prefs)
    raw_threads = getattr(prefs, "thread_count", 0) if prefs is not None else 0
    num_threads = raw_threads if isinstance(raw_threads, int) and not isinstance(raw_threads, bool) and raw_threads > 0 else None
    raw_anim = getattr(prefs, "enable_animated_textures", True) if prefs is not None else True
    enable_animated_textures = raw_anim if isinstance(raw_anim, bool) else True
    skin_cache_dir = None
    try:
        from .assets import get_cache_dir
        sc = get_cache_dir(prefs) / "skins"
        sc.mkdir(parents=True, exist_ok=True)
        skin_cache_dir = str(sc)
    except Exception as e:
        logger.debug("Failed configuring skin cache dir in prepare_world_mesh_context: %s", e)
    return {
        "model_db": model_db,
        "atlas": atlas,
        "biome_resolver": biome_resolver,
        "cache_package_path": str(active_pkg.resolve()) if active_pkg else None,
        "ctm_solver": ctm_solver,
        "num_threads": num_threads,
        "enable_animated_textures": enable_animated_textures,
        "skin_cache_dir": skin_cache_dir,
        "cache_fingerprint": get_cache_fingerprint(prefs),
        "cache_timestamp": get_cache_timestamp(prefs),
    }



_WORLD_SESSIONS: Dict[str, Any] = {}
_WORLD_SESSION_META: Dict[str, Dict[str, Any]] = {}


def clear_world_sessions(session_key: Optional[str] = None) -> None:
    """Clears cached VoxelWorld instances across sessions."""
    global _WORLD_SESSIONS, _WORLD_SESSION_META
    if session_key is None:
        for w in _WORLD_SESSIONS.values():
            if hasattr(w, "clear_cache"):
                try:
                    w.clear_cache()
                except Exception:
                    pass
        _WORLD_SESSIONS.clear()
        _WORLD_SESSION_META.clear()
    else:
        w = _WORLD_SESSIONS.pop(session_key, None)
        if w is not None and hasattr(w, "clear_cache"):
            try:
                w.clear_cache()
            except Exception:
                pass
        _WORLD_SESSION_META.pop(session_key, None)


def get_world_session_dynamic_entity_atlas(session_key: str) -> Optional[Any]:
    """Returns dynamic entity atlas bytes or dict for the cached VoxelWorld session, if any."""
    w = _WORLD_SESSIONS.get(session_key)
    if w is not None:
        if hasattr(w, "get_dynamic_entity_atlases"):
            try:
                atlases = w.get_dynamic_entity_atlases()
                if atlases:
                    return atlases
            except Exception:
                pass
        if hasattr(w, "get_dynamic_entity_atlas"):
            try:
                res = w.get_dynamic_entity_atlas()
                if res is not None:
                    return res
            except Exception:
                pass
    return None


def mesh_voxel_storage(
    storage: Any,
    config: Optional[Any] = None,
    model_db: Optional[Any] = None,
    atlas: Optional[Any] = None,
    biome_resolver: Optional[Any] = None,
    ctm_solver: Optional[Any] = None,
    prefs=None,
    enable_ao: bool = True,
    mesh_fluids: bool = True,
    weld_vertices: bool = True,
    origin_centered: bool = True,
    num_threads: Optional[int] = None,
    progress_callback: Optional[Any] = None,
    world_session_key: Optional[str] = None,
    material_mode: str = "ATLAS",
    force_rebuild: bool = False,
    enable_animated_textures: Optional[bool] = None,
    skin_cache_dir: Optional[str] = None,
    cache_fingerprint: Optional[str] = None,
    cache_timestamp: Optional[float] = None,
    resolve_prefs: bool = True,
    resolve_ctm: bool = True,
) -> Tuple[Any, float]:
    """
    Meshes a VoxelStorage volume with full model resolution, atlas UV remapping,
    culling, and biome tinting. Supports incremental dirty sync when world_session_key is provided.
    Returns (mesh_data, elapsed_ms).
    """
    mtk = require_libmtk("mesh_voxel_storage")

    # Auto-load cached assets if not explicitly passed and caller didn't opt out
    if resolve_prefs and atlas is not False and material_mode != "STANDALONE":
        if model_db is None or atlas is None or biome_resolver is None:
            cached_model_db, cached_atlas, cached_biome_resolver = get_world_pipeline_assets(prefs)
            model_db = model_db or cached_model_db
            atlas = atlas or cached_atlas
            biome_resolver = biome_resolver or cached_biome_resolver
    else:
        if atlas is False:
            atlas = None

    # Auto-resolve CTM solver from pack stack if available
    if resolve_ctm:
        ctm_solver = ctm_solver or get_configured_ctm_solver(prefs)

    # Auto-resolve thread count from preferences if not explicitly set
    if resolve_prefs and num_threads is None:
        if prefs is None:
            try:
                from ..utils.system.dependencies import get_prefs
                prefs = get_prefs()
            except Exception:
                pass
        if prefs is not None:
            raw_threads = getattr(prefs, "thread_count", 0)
            num_threads = raw_threads if isinstance(raw_threads, int) and not isinstance(raw_threads, bool) and raw_threads > 0 else None

    anim_tex_enabled = enable_animated_textures
    if anim_tex_enabled is None:
        raw_val = getattr(prefs, "enable_animated_textures", True) if (resolve_prefs and prefs) else True
        anim_tex_enabled = raw_val if isinstance(raw_val, bool) else True
    else:
        anim_tex_enabled = bool(anim_tex_enabled)

    if config is None:
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
    else:
        if num_threads is not None and hasattr(config, "num_threads"):
            config.num_threads = num_threads
        if ctm_solver is not None and hasattr(config, "set_ctm_solver"):
            config.set_ctm_solver(ctm_solver)
        if hasattr(config, "enable_animated_textures"):
            config.enable_animated_textures = anim_tex_enabled

    culler = get_shared_face_culler(mtk)

    if skin_cache_dir is None:
        try:
            from .assets import get_cache_dir
            sc = get_cache_dir(prefs if resolve_prefs else None) / "skins"
            sc.mkdir(parents=True, exist_ok=True)
            skin_cache_dir = str(sc)
        except Exception:
            pass

    t0 = time.perf_counter()
    # The fingerprint/timestamp pair only guards the incremental world session cache
    # below. Reading it is filesystem-backed and costs ~1 ms, so skip it entirely when
    # no session key is active (single-shot rebuilds never consume the value).
    current_fp = None
    current_ts = None
    if world_session_key:
        # AsyncTask callers precompute these on the main thread; synchronous callers
        # fall back to the bpy-backed cache readers here.
        if cache_timestamp is not None:
            current_fp = cache_fingerprint
            current_ts = float(cache_timestamp)
        else:
            current_fp = get_cache_fingerprint(prefs)
            current_ts = get_cache_timestamp(prefs)

    if world_session_key:
        cached_world = _WORLD_SESSIONS.get(world_session_key)
        cached_meta = _WORLD_SESSION_META.get(world_session_key)

        is_cache_valid = (
            cached_world is not None
            and cached_meta is not None
            and cached_meta.get("fingerprint") == current_fp
            and cached_meta.get("timestamp") == current_ts
            and not force_rebuild
        )

        if is_cache_valid:
            dirty_count = cached_world.sync_from_storage(storage)
            if dirty_count == 0:
                mesh_data = cached_world.get_world_mesh()
            elif dirty_count <= 30:
                cached_world.rebuild_dirty()
                mesh_data = cached_world.get_world_mesh()
            else:
                mesh_data = cached_world.rebuild_all()
        else:
            if cached_world is not None:
                cached_world.clear_cache()
            cached_world = mtk.VoxelWorld.from_storage(
                storage=storage,
                config=config,
                culler=culler,
                model_db=model_db,
                num_threads=num_threads,
            )
            if skin_cache_dir is not None and hasattr(cached_world, "set_skin_cache_dir"):
                try:
                    cached_world.set_skin_cache_dir(skin_cache_dir)
                except Exception:
                    pass
            _WORLD_SESSIONS[world_session_key] = cached_world
            _WORLD_SESSION_META[world_session_key] = {
                "fingerprint": current_fp,
                "timestamp": current_ts,
            }
            if progress_callback is not None:
                from .progress import wrap_progress_callback
                wrapped_cb = wrap_progress_callback(progress_callback)
                mesh_data = cached_world.rebuild_all(callback=wrapped_cb)
            else:
                mesh_data = cached_world.rebuild_all()
    else:
        world = mtk.VoxelWorld.from_storage(
            storage=storage,
            config=config,
            culler=culler,
            model_db=model_db,
            num_threads=num_threads,
        )
        if skin_cache_dir is not None and hasattr(world, "set_skin_cache_dir"):
            try:
                world.set_skin_cache_dir(skin_cache_dir)
            except Exception:
                pass
        if progress_callback is not None:
            from .progress import wrap_progress_callback
            wrapped_cb = wrap_progress_callback(progress_callback)
            mesh_data = world.rebuild_all(callback=wrapped_cb)
        else:
            mesh_data = world.rebuild_all()
    t1 = time.perf_counter()

    if getattr(mesh_data, "profile", None) is not None:
        from .diagnostics import record_operation_profile

        record_operation_profile("Mesh Voxel Storage", mesh_data.profile)

    elapsed_ms = (t1 - t0) * 1000.0
    return mesh_data, elapsed_ms


__all__ = [
    "get_shared_face_culler",
    "reset_shared_face_culler",
    "invalidate_world_pipeline_assets",
    "get_world_pipeline_assets",
    "prepare_world_mesh_context",
    "clear_world_sessions",
    "mesh_voxel_storage",
]

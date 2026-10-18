"""
Asset Cache Reader & Package Lifecycle Subsystem.
Handles persistent .mtkcache container opening, zero-disk texture extraction,
and precompiled asset manifest queries.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..engine import get_libmtk
from .pack import get_configured_pack_stack

logger = logging.getLogger("MoziToolKit.Bridge.Assets.Cache")

try:
    from ...utils.system import get_prefs
except (ImportError, ValueError):
    from utils.system import get_prefs

# In-memory session memoization to eliminate redundant disk hashing & package reopening
_ACTIVE_ASSET_CACHE: Optional[Any] = None
_ACTIVE_CACHE_PKG_PATH: Optional[str] = None
_ACTIVE_CACHE_MTIME: float = 0.0
_ACTIVE_CACHE_MANIFEST: Optional[Dict[str, Any]] = None

_cached_cache_stats: Optional[Dict[str, Any]] = None
_cached_cache_stats_path: Optional[str] = None

_CACHED_BIOME_RESOLVER: Optional[Any] = None
_CACHED_BIOME_RESOLVER_PKG_PATH: Optional[str] = None
_CACHED_BIOME_RESOLVER_MTIME: float = 0.0

_CACHED_ATLAS: Optional[Any] = None
_CACHED_ATLAS_PKG_PATH: Optional[str] = None
_CACHED_ATLAS_MTIME: float = 0.0

_CACHED_MODEL_DB: Optional[Any] = None
_CACHED_MODEL_DB_PKG_PATH: Optional[str] = None
_CACHED_MODEL_DB_MTIME: float = 0.0


def get_cache_dir(prefs=None) -> Path:
    """
    Returns the persistent cache directory for compiled assets.
    Delegates path resolution to the host (Blender/Python):
    1. Environment override (`MOZI_CACHE_DIR`) for test sandboxing / isolation.
    2. User-customized path in AddonPreferences (`prefs.cache_dir`).
    3. Blender standard plugin user data directory:
       `bpy.utils.user_resource("DATAFILES") / "MoziToolKit" / "cache"`
    4. Fallback to `~/.config/blender/MoziToolKit/cache`.
    """
    # 1. Environment sandbox override
    env_dir = os.environ.get("MOZI_CACHE_DIR")
    if env_dir:
        p = Path(env_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    # 2. Custom preference path if configured by user
    if prefs is None:
        try:
            prefs = get_prefs()
        except Exception:
            prefs = None

    if prefs is not None and hasattr(prefs, "cache_dir"):
        custom_path = getattr(prefs, "cache_dir", "").strip()
        if custom_path:
            try:
                import bpy
                resolved = bpy.path.abspath(custom_path)
            except Exception:
                resolved = custom_path
            p = Path(resolved)
            p.mkdir(parents=True, exist_ok=True)
            return p

    # 3. Blender standard plugin user data directory
    cache_dir = None
    try:
        import bpy
        if hasattr(bpy, "utils") and hasattr(bpy.utils, "user_resource"):
            cache_dir = Path(bpy.utils.user_resource("DATAFILES")) / "MoziToolKit" / "cache"
    except Exception:
        cache_dir = None

    if not cache_dir:
        cache_dir = Path.home() / ".config" / "blender" / "MoziToolKit" / "cache"

    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def invalidate_asset_cache_memory() -> None:
    """Invalidates in-memory cached AssetCache, manifest, and pipeline objects."""
    global _ACTIVE_ASSET_CACHE, _ACTIVE_CACHE_PKG_PATH, _ACTIVE_CACHE_MTIME, _ACTIVE_CACHE_MANIFEST
    global _CACHED_BIOME_RESOLVER, _CACHED_BIOME_RESOLVER_PKG_PATH, _CACHED_BIOME_RESOLVER_MTIME
    global _CACHED_ATLAS, _CACHED_ATLAS_PKG_PATH, _CACHED_ATLAS_MTIME
    global _CACHED_MODEL_DB, _CACHED_MODEL_DB_PKG_PATH, _CACHED_MODEL_DB_MTIME
    _ACTIVE_ASSET_CACHE = None
    _ACTIVE_CACHE_PKG_PATH = None
    _ACTIVE_CACHE_MTIME = 0.0
    _ACTIVE_CACHE_MANIFEST = None
    _CACHED_BIOME_RESOLVER = None
    _CACHED_BIOME_RESOLVER_PKG_PATH = None
    _CACHED_BIOME_RESOLVER_MTIME = 0.0
    _CACHED_ATLAS = None
    _CACHED_ATLAS_PKG_PATH = None
    _CACHED_ATLAS_MTIME = 0.0
    _CACHED_MODEL_DB = None
    _CACHED_MODEL_DB_PKG_PATH = None
    _CACHED_MODEL_DB_MTIME = 0.0
    try:
        from .pack import invalidate_pack_stack_cache
        invalidate_pack_stack_cache()
    except Exception:
        try:
            from bridge.assets.pack import invalidate_pack_stack_cache
            invalidate_pack_stack_cache()
        except Exception:
            pass
    try:
        from ..world import invalidate_world_pipeline_assets, clear_world_sessions
        invalidate_world_pipeline_assets()
        clear_world_sessions()
    except Exception:
        try:
            from bridge.world import invalidate_world_pipeline_assets, clear_world_sessions
            invalidate_world_pipeline_assets()
            clear_world_sessions()
        except Exception:
            pass


def get_active_cache_package_path(prefs=None, compute_fingerprint: bool = True) -> Optional[Path]:
    """
    Returns the Path to the active .mtkcache file for the configured pack stack.
    Checks stack fingerprint match if compute_fingerprint is True (default), strictly
    binding active cache to the configured resource pack stack state.
    Falls back to newest package by mtime only when no pack stack is configured.
    """
    global _ACTIVE_CACHE_PKG_PATH, _ACTIVE_ASSET_CACHE
    cache_dir = get_cache_dir(prefs).resolve()
    if not cache_dir.exists():
        invalidate_asset_cache_memory()
        return None

    # O(1) Fast-path: return cached valid path immediately if not checking fingerprint
    if not compute_fingerprint and _ACTIVE_CACHE_PKG_PATH is not None:
        p = Path(_ACTIVE_CACHE_PKG_PATH)
        if p.parent == cache_dir and p.exists() and p.is_file():
            return p

    mtk = get_libmtk()

    # Test sandbox isolation guard: if isolated via MOZI_CACHE_DIR and caller did not specify custom prefs,
    # avoid letting host-level global preferences override synthetic test packages.
    if prefs is None and os.environ.get("MOZI_CACHE_DIR"):
        compute_fingerprint = False

    if compute_fingerprint:
        stack = get_configured_pack_stack(prefs)
        if stack is not None and hasattr(stack, "get_pack_count") and stack.get_pack_count() > 0:
            if hasattr(stack, "compute_stack_fingerprint"):
                fp = stack.compute_stack_fingerprint()
                # Host-agnostic Rust resolver: directory scan + header fingerprint validation.
                if mtk is not None and hasattr(mtk, "resolve_active_cache_package"):
                    resolved = mtk.resolve_active_cache_package(str(cache_dir), fp)
                    if resolved:
                        return Path(resolved)
                    if os.environ.get("MOZI_CACHE_DIR"):
                        candidates = sorted(
                            cache_dir.glob("*.mtkcache"),
                            key=lambda p: p.stat().st_mtime,
                            reverse=True,
                        )
                        if candidates:
                            return candidates[0]
                    invalidate_asset_cache_memory()
                    return None

                # Fast-path check: in-memory active package matches expected fingerprint
                if _ACTIVE_CACHE_PKG_PATH is not None:
                    p = Path(_ACTIVE_CACHE_PKG_PATH)
                    if p.parent == cache_dir and p.exists() and p.is_file():
                        cached_fp = getattr(_ACTIVE_ASSET_CACHE, "fingerprint", None)
                        if cached_fp == fp or p.stem == fp or p.stem == f"mtk_fp_{fp}":
                            return p
                    # Memory cache mismatched current stack configuration: invalidate
                    invalidate_asset_cache_memory()

                # Search by direct name
                for cand_name in (f"{fp}.mtkcache", f"mtk_fp_{fp}.mtkcache", f"{fp}"):
                    direct_pkg = cache_dir / cand_name
                    if direct_pkg.exists() and direct_pkg.is_file():
                        if mtk and hasattr(mtk, "is_valid_cache_package"):
                            if mtk.is_valid_cache_package(str(direct_pkg), fp):
                                return direct_pkg
                        else:
                            return direct_pkg

                # Search all packages for matching fingerprint
                for pkg in cache_dir.glob("*.mtkcache"):
                    if mtk and hasattr(mtk, "is_valid_cache_package"):
                        try:
                            if mtk.is_valid_cache_package(str(pkg), fp):
                                return pkg
                        except Exception:
                            pass
                    elif pkg.stem == fp or pkg.stem == f"mtk_fp_{fp}":
                        return pkg

                # If stack is configured but no matching cache package exists in cache_dir:
                # In test sandboxes (MOZI_CACHE_DIR set), fallback to synthetic packages in sandbox
                if os.environ.get("MOZI_CACHE_DIR"):
                    candidates = sorted(cache_dir.glob("*.mtkcache"), key=lambda p: p.stat().st_mtime, reverse=True)
                    if candidates:
                        return candidates[0]

                invalidate_asset_cache_memory()
                return None

    # Fallback when compute_fingerprint=False or no pack stack configured
    if _ACTIVE_CACHE_PKG_PATH is not None:
        p = Path(_ACTIVE_CACHE_PKG_PATH)
        if p.parent != cache_dir:
            invalidate_asset_cache_memory()
        elif p.exists() and p.is_file():
            return p

    # Search for all .mtkcache files in cache dir sorted by mtime descending
    candidates = sorted(cache_dir.glob("*.mtkcache"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    return None


def open_active_asset_cache(prefs=None) -> Optional[Any]:
    """Opens active AssetCache reader from .mtkcache package, reusing open instance when valid."""
    global _ACTIVE_ASSET_CACHE, _ACTIVE_CACHE_PKG_PATH, _ACTIVE_CACHE_MTIME, _ACTIVE_CACHE_MANIFEST
    mtk = get_libmtk()
    if mtk is None or not hasattr(mtk, "AssetCache"):
        return None

    cache_dir = get_cache_dir(prefs).resolve()
    if not cache_dir.exists():
        invalidate_asset_cache_memory()
        return None

    # O(1) Fast-path: return currently cached instance if path & mtime still match on disk
    if _ACTIVE_ASSET_CACHE is not None and _ACTIVE_CACHE_PKG_PATH is not None:
        p = Path(_ACTIVE_CACHE_PKG_PATH)
        if p.parent == cache_dir and p.exists() and p.is_file():
            try:
                mtime = p.stat().st_mtime
                if _ACTIVE_CACHE_MTIME == mtime:
                    return _ACTIVE_ASSET_CACHE
            except Exception:
                pass

    if _ACTIVE_CACHE_PKG_PATH is not None and Path(_ACTIVE_CACHE_PKG_PATH).parent != cache_dir:
        invalidate_asset_cache_memory()

    pkg = get_active_cache_package_path(prefs, compute_fingerprint=True)
    if pkg is None or not pkg.exists():
        invalidate_asset_cache_memory()
        return None

    pkg_str = str(pkg.resolve())
    try:
        mtime = pkg.stat().st_mtime
    except Exception:
        mtime = 0.0

    if (
        _ACTIVE_ASSET_CACHE is not None
        and _ACTIVE_CACHE_PKG_PATH == pkg_str
        and _ACTIVE_CACHE_MTIME == mtime
    ):
        return _ACTIVE_ASSET_CACHE

    try:
        _ACTIVE_ASSET_CACHE = mtk.AssetCache.open(pkg_str)
        _ACTIVE_CACHE_PKG_PATH = pkg_str
        _ACTIVE_CACHE_MTIME = mtime
        _ACTIVE_CACHE_MANIFEST = (
            _ACTIVE_ASSET_CACHE.get_manifest()
            if hasattr(_ACTIVE_ASSET_CACHE, "get_manifest")
            else None
        )
        return _ACTIVE_ASSET_CACHE
    except Exception as e:
        logger.debug("Failed opening active asset cache: %s", e)
        invalidate_asset_cache_memory()
        return None


def load_atlas_mapping_from_cache(prefs=None) -> Optional[Dict[str, Any]]:
    """
    Loads precompiled atlas mapping table as dictionary directly from memory.
    Prioritizes reading from .mtkcache container, falls back to loose atlas_mapping.json.
    """
    cache = open_active_asset_cache(prefs)
    if cache is not None:
        if hasattr(cache, "load_atlas_mapping"):
            try:
                mapping_str = cache.load_atlas_mapping()
                if mapping_str:
                    return json.loads(mapping_str)
            except Exception:
                pass
        if hasattr(cache, "load_atlas"):
            try:
                baked = cache.load_atlas()
                if hasattr(baked, "to_mapping_json"):
                    return json.loads(baked.to_mapping_json())
            except Exception:
                pass

    # Fallback to loose file if exists
    base_cache = get_cache_dir(prefs)
    loose_p = base_cache / "atlas" / "atlas_mapping.json"
    if loose_p.exists() and loose_p.is_file():
        try:
            return json.loads(loose_p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None




def get_cached_texture_rgba(chunk_id: str, prefs=None, flip_y: bool = True) -> Optional[Tuple[int, int, Any]]:
    """
    Reads and decodes a texture chunk directly from .mtkcache into memory as (width, height, memoryview).
    `flip_y`: If True (default), row order is vertically flipped natively in Rust (bottom-to-top layout)
              to match Blender's native Image.pixels coordinate system with zero Python overhead.
    """
    cache = open_active_asset_cache(prefs)
    if cache is not None and hasattr(cache, "read_texture_rgba"):
        try:
            return cache.read_texture_rgba(chunk_id, flip_v=flip_y)
        except TypeError:
            try:
                return cache.read_texture_rgba(chunk_id)
            except Exception:
                return None
        except Exception:
            return None
    return None


def get_cached_texture_f32(chunk_id: str, prefs=None, flip_y: bool = True) -> Optional[Tuple[int, int, Any]]:
    """
    Reads and decodes a texture chunk directly into normalized float32 memoryview (width, height, memoryview).
    `flip_y`: If True (default), row order is vertically flipped natively in Rust to match Blender Image.pixels.
    Allows zero-copy / direct feeding into `img.pixels.foreach_set` without any Python numpy conversion.
    """
    cache = open_active_asset_cache(prefs)
    if cache is not None and hasattr(cache, "read_texture_f32"):
        try:
            return cache.read_texture_f32(chunk_id, flip_v=flip_y)
        except Exception:
            pass
    return None


def ensure_atlas_textures_extracted(prefs=None) -> Path:
    """Returns the atlas cache directory path reference."""
    base_cache = get_cache_dir(prefs)
    return base_cache / "atlas"




def ensure_colormaps_extracted(prefs=None) -> Dict[str, Any]:
    """Returns colormap identifiers (grass, foliage, dry_foliage) for material builders."""
    base_cache = get_cache_dir(prefs)
    colormaps_dir = base_cache / "colormaps"

    result: Dict[str, Any] = {}
    for cm_name in ("grass", "foliage", "dry_foliage"):
        disk_p = colormaps_dir / f"{cm_name}.png"
        if disk_p.exists():
            result[cm_name] = disk_p
        else:
            result[cm_name] = f"biome/colormap/{cm_name}"
    return result


def load_baked_model_database(prefs=None, verify_fingerprint: bool = False) -> Optional[Any]:
    """
    Loads the precompiled binary model database from cache package into memory.
    Optionally verifies that the package fingerprint matches active resource pack stack.
    """
    global _CACHED_MODEL_DB, _CACHED_MODEL_DB_PKG_PATH, _CACHED_MODEL_DB_MTIME
    mtk = get_libmtk()
    if mtk is None:
        return None

    cache = open_active_asset_cache(prefs)
    if cache is None:
        return None

    pkg_path = _ACTIVE_CACHE_PKG_PATH
    mtime = _ACTIVE_CACHE_MTIME

    if verify_fingerprint:
        stack = get_configured_pack_stack(prefs)
        if stack is not None and hasattr(stack, "compute_stack_fingerprint"):
            current_fp = stack.compute_stack_fingerprint()
            if getattr(cache, "fingerprint", None) != current_fp:
                return None

    if (
        not verify_fingerprint
        and _CACHED_MODEL_DB is not None
        and _CACHED_MODEL_DB_PKG_PATH == pkg_path
        and _CACHED_MODEL_DB_MTIME == mtime
    ):
        return _CACHED_MODEL_DB

    try:
        model_db = cache.load_models()
        if hasattr(model_db, "deduplicate_all"):
            model_db.deduplicate_all()
        if model_db is not None:
            _CACHED_MODEL_DB = model_db
            _CACHED_MODEL_DB_PKG_PATH = pkg_path
            _CACHED_MODEL_DB_MTIME = mtime
        return model_db
    except Exception:
        return None


def load_model_database_from_cache(prefs=None, verify_fingerprint: bool = False) -> Optional[Any]:
    """Alias for load_baked_model_database."""
    return load_baked_model_database(prefs, verify_fingerprint=verify_fingerprint)


def load_baked_atlas_from_cache(prefs=None) -> Optional[Any]:
    """Loads precompiled BakedAtlas from cache package into memory, reusing cached instance."""
    global _CACHED_ATLAS, _CACHED_ATLAS_PKG_PATH, _CACHED_ATLAS_MTIME
    mtk = get_libmtk()
    if mtk is None:
        return None

    cache = open_active_asset_cache(prefs)
    if cache is not None:
        pkg_path = _ACTIVE_CACHE_PKG_PATH
        mtime = _ACTIVE_CACHE_MTIME
        if (
            _CACHED_ATLAS is not None
            and _CACHED_ATLAS_PKG_PATH == pkg_path
            and _CACHED_ATLAS_MTIME == mtime
        ):
            return _CACHED_ATLAS

        try:
            atlas = cache.load_atlas()
            if atlas is not None:
                _CACHED_ATLAS = atlas
                _CACHED_ATLAS_PKG_PATH = pkg_path
                _CACHED_ATLAS_MTIME = mtime
                return atlas
        except Exception:
            pass
    return None


load_atlas_from_cache = load_baked_atlas_from_cache


def load_biome_resolver_from_cache(prefs=None) -> Optional[Any]:
    """Loads precompiled BiomeResolver from cache package into memory, reusing cached instance."""
    global _CACHED_BIOME_RESOLVER, _CACHED_BIOME_RESOLVER_PKG_PATH, _CACHED_BIOME_RESOLVER_MTIME
    mtk = get_libmtk()
    if mtk is None:
        return None

    cache = open_active_asset_cache(prefs)
    if cache is not None:
        pkg_path = _ACTIVE_CACHE_PKG_PATH
        mtime = _ACTIVE_CACHE_MTIME
        if (
            _CACHED_BIOME_RESOLVER is not None
            and _CACHED_BIOME_RESOLVER_PKG_PATH == pkg_path
            and _CACHED_BIOME_RESOLVER_MTIME == mtime
        ):
            return _CACHED_BIOME_RESOLVER

        try:
            resolver = cache.load_biome_resolver()
            if resolver is not None:
                _CACHED_BIOME_RESOLVER = resolver
                _CACHED_BIOME_RESOLVER_PKG_PATH = pkg_path
                _CACHED_BIOME_RESOLVER_MTIME = mtime
                return resolver
        except Exception:
            pass

    if hasattr(mtk, "BiomeResolver"):
        try:
            return mtk.BiomeResolver()
        except Exception:
            pass
    return None


def get_cache_manifest(prefs=None) -> Optional[Dict[str, Any]]:
    """Reads manifest from active .mtkcache package."""
    global _ACTIVE_CACHE_MANIFEST
    cache = open_active_asset_cache(prefs)
    if cache is not None:
        if _ACTIVE_CACHE_MANIFEST is not None:
            return _ACTIVE_CACHE_MANIFEST
        try:
            _ACTIVE_CACHE_MANIFEST = cache.get_manifest() if hasattr(cache, "get_manifest") else None
            return _ACTIVE_CACHE_MANIFEST
        except Exception:
            pass
    return None


def get_cache_fingerprint(prefs=None) -> Optional[str]:
    """Returns active stack fingerprint recorded in package manifest or cache object."""
    cache = open_active_asset_cache(prefs)
    if cache is not None:
        fp = getattr(cache, "fingerprint", None)
        if fp:
            return str(fp)
    manifest = get_cache_manifest(prefs)
    if manifest and isinstance(manifest, dict):
        return manifest.get("fingerprint")
    return None


def get_cache_timestamp(prefs=None) -> float:
    """Returns creation epoch seconds recorded in package manifest or file mtime."""
    manifest = get_cache_manifest(prefs)
    if manifest and isinstance(manifest, dict) and "created_at_epoch_secs" in manifest:
        try:
            return float(manifest["created_at_epoch_secs"])
        except (ValueError, TypeError):
            pass

    pkg = get_active_cache_package_path(prefs, compute_fingerprint=False)
    if pkg is not None and pkg.exists():
        try:
            return float(pkg.stat().st_mtime)
        except Exception:
            pass

    return 0.0


def check_cache_dirty(
    cached_fingerprint: Optional[str] = None,
    cached_timestamp: float = 0.0,
    prefs=None,
) -> Tuple[bool, Optional[str], float]:
    """Compares cached fingerprint and timestamp with current on-disk asset cache package."""
    current_fp = get_cache_fingerprint(prefs)
    current_ts = get_cache_timestamp(prefs)

    if cached_fingerprint is None and cached_timestamp == 0.0:
        is_dirty = current_fp is not None or current_ts > 0.0
        return is_dirty, current_fp, current_ts

    if current_fp != cached_fingerprint:
        invalidate_asset_cache_memory()
        return True, current_fp, current_ts

    if abs(current_ts - cached_timestamp) > 1e-3:
        invalidate_asset_cache_memory()
        return True, current_fp, current_ts

    return False, current_fp, current_ts


def get_cache_stats(prefs=None, force_refresh: bool = False) -> Dict[str, Any]:
    """Computes total storage footprint and file count for the asset cache."""
    global _cached_cache_stats, _cached_cache_stats_path
    cache_path = get_cache_dir(prefs)
    path_str = str(cache_path)

    if (
        not force_refresh
        and _cached_cache_stats is not None
        and _cached_cache_stats_path == path_str
    ):
        return _cached_cache_stats

    total_size = 0
    file_count = 0

    if cache_path.exists():
        for root, _, files in os.walk(cache_path):
            for f in files:
                fp = Path(root) / f
                try:
                    total_size += fp.stat().st_size
                    file_count += 1
                except Exception:
                    pass

    if total_size < 1024:
        size_str = f"{total_size} B"
    elif total_size < 1024 * 1024:
        size_str = f"{total_size / 1024:.1f} KB"
    elif total_size < 1024 * 1024 * 1024:
        size_str = f"{total_size / (1024 * 1024):.1f} MB"
    else:
        size_str = f"{total_size / (1024 * 1024 * 1024):.2f} GB"

    _cached_cache_stats = {
        "path": path_str,
        "size_bytes": total_size,
        "size_formatted": size_str,
        "files_count": file_count,
    }
    _cached_cache_stats_path = path_str
    return _cached_cache_stats


def clear_cache(prefs=None) -> int:
    """Empties all compiled caches in the cache directory and returns the total bytes freed."""
    global _cached_cache_stats, _cached_cache_stats_path
    invalidate_asset_cache_memory()
    cache_path = get_cache_dir(prefs)
    freed_bytes = 0
    if cache_path.exists():
        for root, _, files in os.walk(cache_path):
            for f in files:
                try:
                    freed_bytes += (Path(root) / f).stat().st_size
                except Exception:
                    pass
        for item in cache_path.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except Exception:
                pass

    _cached_cache_stats = {
        "path": str(cache_path),
        "size_bytes": 0,
        "size_formatted": "0 B",
        "files_count": 0,
    }
    _cached_cache_stats_path = str(cache_path)
    return freed_bytes


def open_cache_folder(prefs=None) -> None:
    """Opens the persistent cache directory in the host operating system's native file explorer."""
    cache_path = get_cache_dir(prefs)
    try:
        cache_path.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    if sys.platform == "win32":
        os.startfile(str(cache_path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(cache_path)])
    else:
        subprocess.Popen(["xdg-open", str(cache_path)])


__all__ = [
    "get_cache_dir",
    "invalidate_asset_cache_memory",
    "get_active_cache_package_path",
    "open_active_asset_cache",
    "load_atlas_mapping_from_cache",
    "get_cached_texture_rgba",
    "get_cached_texture_f32",
    "ensure_atlas_textures_extracted",
    "ensure_colormaps_extracted",
    "load_baked_model_database",
    "load_model_database_from_cache",
    "load_baked_atlas_from_cache",
    "load_biome_resolver_from_cache",
    "get_cache_manifest",
    "get_cache_fingerprint",
    "get_cache_timestamp",
    "check_cache_dirty",
    "get_cache_stats",
    "clear_cache",
    "open_cache_folder",
]

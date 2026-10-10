"""
Bridge: Asset Precompilation & Resource Stack Management.
Transfers resource pack configuration from Blender to libmtk (Rust) for
headless Atlas stitching, Standalone material generation, and Model baking.
Zero-computation on the Python side: all parsing, packing, image decoding,
and geometric meshing are handled entirely within libmtk.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from ..utils.system import get_prefs
except (ImportError, ValueError):
    from utils.system import get_prefs

from .engine import get_libmtk, has_libmtk, require_libmtk
from .progress import ProgressCallback, wrap_progress_callback


def _get_libmtk():
    return get_libmtk()


def _has_libmtk() -> bool:
    return has_libmtk()


def __getattr__(name: str) -> Any:
    if name == "HAS_LIBMTK":
        return has_libmtk()
    if name == "libmtk_py":
        return get_libmtk()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


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


def get_configured_pack_stack(prefs=None) -> Optional[Any]:
    """
    Builds a libmtk ResourcePackStack from the Blender preferences configuration.
    Traverses enabled entries in order and pushes them to Rust.
    """
    mtk = _get_libmtk()
    if mtk is None:
        return None

    if prefs is None:
        prefs = get_prefs()

    stack = mtk.ResourcePackStack()

    if prefs is None or not hasattr(prefs, "resource_packs"):
        return stack

    for entry in prefs.resource_packs:
        if not getattr(entry, "enabled", True):
            continue

        raw_path = getattr(entry, "path", "").strip()
        if not raw_path:
            continue

        p = Path(raw_path)
        if not p.exists():
            continue

        name = getattr(entry, "name", None) or p.stem

        if p.is_dir():
            stack.add_directory_pack(str(p.resolve()), name)
        elif p.is_file() and p.suffix.lower() in {".zip", ".jar"}:
            stack.add_zip_pack(str(p.resolve()))

    return stack


def precompile_stack(
    prefs=None,
    num_threads: Optional[int] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """
    Executes end-to-end asset precompilation via libmtk:
    1. Compiles blocks Atlas and saves all chunk PNGs + atlas_mapping.json
    2. Precompiles Standalone PBR textures + standalone_mapping.json
    3. Bakes all block models into compact binary models.bin
    4. Writes cache_manifest.json with resource pack stack fingerprint
    Returns a summary dictionary of compiled assets.
    """
    mtk = _get_libmtk()
    if mtk is None:
        raise RuntimeError("libmtk_py (Rust backend) is not installed or available.")

    stack = get_configured_pack_stack(prefs)
    if stack is None or stack.get_pack_count() == 0:
        raise ValueError("No valid enabled resource packs or JARs found in the active stack.")

    if num_threads is None and prefs is not None:
        num_threads = getattr(prefs, "thread_count", 0)
    if num_threads == 0:
        num_threads = None

    start_time = time.time()
    base_cache = get_cache_dir(prefs)

    wrapped_cb = wrap_progress_callback(progress_callback)

    # Use unified high-performance Rust engine with thread pool control & progress callback
    if hasattr(mtk, "precompile_all_assets"):
        try:
            res = mtk.precompile_all_assets(
                stack,
                str(base_cache.resolve()),
                atlas_category="blocks",
                max_atlas_width=4096,
                max_atlas_height=4096,
                compile_atlas=True,
                compile_standalone=True,
                compile_models=True,
                num_threads=num_threads,
                callback=wrapped_cb,
            )
        except TypeError:
            try:
                # Fallback for bindings without callback keyword
                res = mtk.precompile_all_assets(
                    stack,
                    str(base_cache.resolve()),
                    atlas_category="blocks",
                    max_atlas_width=4096,
                    max_atlas_height=4096,
                    compile_atlas=True,
                    compile_standalone=True,
                    compile_models=True,
                    num_threads=num_threads,
                )
            except TypeError:
                res = mtk.precompile_all_assets(
                    stack,
                    str(base_cache.resolve()),
                    atlas_category="blocks",
                    max_atlas_width=4096,
                    max_atlas_height=4096,
                    compile_atlas=True,
                    compile_standalone=True,
                    compile_models=True,
                )
        package_path = getattr(res, "package_path", "")
        invalidate_asset_cache_memory()
        get_cache_stats(prefs, force_refresh=True)
        duration = time.time() - start_time

        return {
            "success": getattr(res, "success", True),
            "pack_count": getattr(res, "pack_count", 0),
            "atlas_chunks": getattr(res, "atlas_chunks", 0),
            "standalone_textures": getattr(res, "standalone_textures", 0),
            "baked_models": getattr(res, "baked_models", 0),
            "models": getattr(res, "baked_models", 0),
            "duration_seconds": duration,
            "fingerprint": getattr(res, "fingerprint", ""),
            "package_path": package_path,
            "cache_dir": getattr(res, "cache_dir", str(base_cache.resolve())),
        }


def precompile_stack_async(
    prefs=None,
    num_threads: Optional[int] = None,
    on_complete=None,
    on_error=None,
    progress_callback: Optional[ProgressCallback] = None,
):
    """
    Executes precompile_stack asynchronously in a background worker thread.
    Takes advantage of libmtk_py releasing the Python GIL to prevent freezing Blender UI.
    """
    import concurrent.futures

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def worker():
        try:
            res = precompile_stack(prefs, num_threads=num_threads, progress_callback=progress_callback)
            if on_complete:
                on_complete(res)
            return res
        except Exception as e:
            if on_error:
                on_error(e)
            raise

    future = executor.submit(worker)
    executor.shutdown(wait=False)
    return future


# In-memory session memoization to eliminate redundant disk hashing & package reopening
_ACTIVE_ASSET_CACHE: Optional[Any] = None
_ACTIVE_CACHE_PKG_PATH: Optional[str] = None
_ACTIVE_CACHE_MTIME: float = 0.0
_ACTIVE_CACHE_MANIFEST: Optional[Dict[str, Any]] = None


def invalidate_asset_cache_memory() -> None:
    """Invalidates in-memory cached AssetCache, manifest, and pipeline objects."""
    global _ACTIVE_ASSET_CACHE, _ACTIVE_CACHE_PKG_PATH, _ACTIVE_CACHE_MTIME, _ACTIVE_CACHE_MANIFEST
    _ACTIVE_ASSET_CACHE = None
    _ACTIVE_CACHE_PKG_PATH = None
    _ACTIVE_CACHE_MTIME = 0.0
    _ACTIVE_CACHE_MANIFEST = None
    try:
        from .world import invalidate_world_pipeline_assets
        invalidate_world_pipeline_assets()
    except Exception:
        pass


def get_active_cache_package_path(prefs=None, compute_fingerprint: bool = False) -> Optional[Path]:
    """
    Returns the Path to the active .mtkcache file for the configured pack stack.
    Checks stack fingerprint match if compute_fingerprint is True, otherwise fast-paths
    to currently active package or newest package by mtime.
    """
    global _ACTIVE_CACHE_PKG_PATH
    cache_dir = get_cache_dir(prefs).resolve()
    if not cache_dir.exists():
        invalidate_asset_cache_memory()
        return None

    if _ACTIVE_CACHE_PKG_PATH is not None:
        p = Path(_ACTIVE_CACHE_PKG_PATH)
        if p.parent != cache_dir:
            invalidate_asset_cache_memory()
        elif not compute_fingerprint and p.exists() and p.is_file():
            return p

    mtk = _get_libmtk()
    if compute_fingerprint:
        stack = get_configured_pack_stack(prefs)
        if stack is not None and hasattr(stack, "compute_stack_fingerprint"):
            fp = stack.compute_stack_fingerprint()
            for cand_name in (f"{fp}.mtkcache", f"mtk_fp_{fp}.mtkcache", f"{fp}"):
                direct_pkg = cache_dir / cand_name
                if direct_pkg.exists() and direct_pkg.is_file():
                    if mtk and hasattr(mtk, "is_valid_cache_package"):
                        if mtk.is_valid_cache_package(str(direct_pkg), fp):
                            return direct_pkg
                    else:
                        return direct_pkg

    # Search for all .mtkcache files in cache dir sorted by mtime descending
    candidates = sorted(cache_dir.glob("*.mtkcache"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    return None


def open_active_asset_cache(prefs=None) -> Optional[Any]:
    """Opens active AssetCache reader from .mtkcache package, reusing open instance when valid."""
    global _ACTIVE_ASSET_CACHE, _ACTIVE_CACHE_PKG_PATH, _ACTIVE_CACHE_MTIME, _ACTIVE_CACHE_MANIFEST
    mtk = _get_libmtk()
    if mtk is None or not hasattr(mtk, "AssetCache"):
        return None

    cache_dir = get_cache_dir(prefs).resolve()
    if not cache_dir.exists():
        invalidate_asset_cache_memory()
        return None

    if _ACTIVE_CACHE_PKG_PATH is not None and Path(_ACTIVE_CACHE_PKG_PATH).parent != cache_dir:
        invalidate_asset_cache_memory()

    pkg = get_active_cache_package_path(prefs, compute_fingerprint=False)
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
    import json
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


def load_standalone_mapping_from_cache(prefs=None) -> Optional[Dict[str, Any]]:
    """
    Loads precompiled standalone mapping table as dictionary directly from memory.
    Prioritizes reading from .mtkcache container, falls back to loose standalone_mapping.json.
    """
    import json
    cache = open_active_asset_cache(prefs)
    if cache is not None and hasattr(cache, "load_standalone_mapping"):
        try:
            mapping_str = cache.load_standalone_mapping()
            if mapping_str:
                return json.loads(mapping_str)
        except Exception:
            pass

    # Fallback to loose file if exists
    base_cache = get_cache_dir(prefs)
    loose_p = base_cache / "standalone" / "standalone_mapping.json"
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
    """
    Returns the atlas cache directory path reference.
    Directory creation and loose extraction are disabled in favor of zero-disk in-memory streaming.
    """
    base_cache = get_cache_dir(prefs)
    return base_cache / "atlas"


def ensure_standalone_textures_extracted(prefs=None) -> Path:
    """
    Returns the standalone cache directory path reference.
    Directory creation and loose extraction are disabled in favor of zero-disk in-memory streaming.
    """
    base_cache = get_cache_dir(prefs)
    return base_cache / "standalone"


def ensure_colormaps_extracted(prefs=None) -> Dict[str, Any]:
    """
    Returns colormap identifiers (grass, foliage, dry_foliage) for material builders.
    Prioritizes in-memory package streaming without creating directories or loose files on disk.
    """
    base_cache = get_cache_dir(prefs)
    colormaps_dir = base_cache / "colormaps"

    result: Dict[str, Any] = {}
    for cm_name in ("grass", "foliage", "dry_foliage"):
        disk_p = colormaps_dir / f"{cm_name}.png"
        if disk_p.exists():
            result[cm_name] = disk_p
        else:
            # Zero-disk in-memory chunk identifier from .mtkcache
            result[cm_name] = f"biome/colormap/{cm_name}"
    return result


def load_baked_model_database(prefs=None, verify_fingerprint: bool = False) -> Optional[Any]:
    """
    Loads the precompiled binary model database from cache package into memory.
    Optionally verifies that the package fingerprint matches active resource pack stack.
    Returns None if cache does not exist, is stale, or libmtk is unavailable.
    """
    mtk = _get_libmtk()
    if mtk is None:
        return None

    cache = open_active_asset_cache(prefs)
    if cache is None:
        return None

    if verify_fingerprint:
        stack = get_configured_pack_stack(prefs)
        if stack is not None and hasattr(stack, "compute_stack_fingerprint"):
            current_fp = stack.compute_stack_fingerprint()
            if cache.fingerprint != current_fp:
                return None

    try:
        model_db = cache.load_models()
        if hasattr(model_db, "deduplicate_all"):
            model_db.deduplicate_all()
        return model_db
    except Exception:
        return None


def load_model_database_from_cache(prefs=None, verify_fingerprint: bool = False) -> Optional[Any]:
    """Alias for load_baked_model_database."""
    return load_baked_model_database(prefs, verify_fingerprint=verify_fingerprint)


def load_baked_atlas_from_cache(prefs=None) -> Optional[Any]:
    """
    Loads precompiled BakedAtlas from cache package into memory.
    Returns None if cache does not exist or libmtk is unavailable.
    """
    mtk = _get_libmtk()
    if mtk is None:
        return None

    cache = open_active_asset_cache(prefs)
    if cache is not None:
        try:
            return cache.load_atlas()
        except Exception:
            pass
    return None


def load_biome_resolver_from_cache(prefs=None) -> Optional[Any]:
    """
    Loads precompiled BiomeResolver from cache package into memory.
    Falls back to a default Vanilla 1.21+ BiomeResolver if missing.
    """
    mtk = _get_libmtk()
    if mtk is None:
        return None

    cache = open_active_asset_cache(prefs)
    if cache is not None:
        try:
            return cache.load_biome_resolver()
        except Exception:
            pass

    if hasattr(mtk, "BiomeResolver"):
        try:
            return mtk.BiomeResolver()
        except Exception:
            pass
    return None


def get_cache_manifest(prefs=None) -> Optional[Dict[str, Any]]:
    """
    Reads manifest from active .mtkcache package.
    Returns parsed dictionary or None.
    """
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
    """
    Returns active stack fingerprint recorded in package manifest or cache object,
    or None if cache does not exist.
    """
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
    """
    Returns creation epoch seconds recorded in package manifest or file mtime.
    Returns 0.0 if cache does not exist.
    """
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
    """
    Compares cached fingerprint and timestamp with current on-disk asset cache package.
    Returns (is_dirty, current_fingerprint, current_timestamp).
    """
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


def reload_atlas_images(prefs=None) -> int:
    """
    Finds loaded Blender image datablocks originating from the atlas cache directory
    and triggers img.reload() so updated pixels and mipmaps immediately reflect on screen.
    Returns the count of successfully reloaded images.
    """
    try:
        import bpy
    except ImportError:
        return 0

    cache_dir = get_cache_dir(prefs)
    atlas_dir = cache_dir / "atlas"
    atlas_dir_str = str(atlas_dir.resolve()).lower()

    reloaded_count = 0
    if not hasattr(bpy, "data") or not hasattr(bpy.data, "images"):
        return 0

    for img in bpy.data.images:
        fp = getattr(img, "filepath", "")
        if not fp:
            continue
        try:
            resolved_fp = str(Path(bpy.path.abspath(fp)).resolve()).lower()
            if atlas_dir_str in resolved_fp or "atlas" in resolved_fp:
                if hasattr(img, "reload"):
                    img.reload()
                    reloaded_count += 1
        except Exception:
            continue

    return reloaded_count


_cached_cache_stats: Optional[Dict[str, Any]] = None
_cached_cache_stats_path: Optional[str] = None


def get_cache_stats(prefs=None, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Computes total storage footprint and file count for the asset cache.
    Results are cached in-memory to prevent UI redraw stutter during continuous render loops.
    Scans only on-demand when explicitly requested or after cache mutations.
    """
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

    # Human-readable formatted size
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
    """Opens the cache directory in the host system's file explorer using Blender or OS."""
    cache_path = get_cache_dir(prefs)
    try:
        import bpy
        if hasattr(bpy.ops.wm, "path_open"):
            bpy.ops.wm.path_open(filepath=str(cache_path.resolve()))
            return
    except Exception:
        pass

    if sys.platform == "win32":
        os.startfile(str(cache_path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(cache_path)])
    else:
        subprocess.Popen(["xdg-open", str(cache_path)])


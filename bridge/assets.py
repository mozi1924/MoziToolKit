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
        get_cache_stats(prefs, force_refresh=True)
        duration = time.time() - start_time
        return {
            "success": res.success,
            "pack_count": res.pack_count,
            "atlas_chunks": res.atlas_chunks,
            "standalone_textures": res.standalone_textures,
            "baked_models": res.baked_models,
            "models": res.baked_models,
            "duration_seconds": duration,
            "fingerprint": res.fingerprint,
            "cache_dir": res.cache_dir,
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

    # Fallback to individual builders if unified binding is not available
    atlas_dir = base_cache / "atlas"
    standalone_dir = base_cache / "standalone"
    models_dir = base_cache / "models"
    atlas_dir.mkdir(parents=True, exist_ok=True)
    standalone_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    atlas_builder = libmtk_py.AtlasBuilder(4096, 4096, 0, 0)
    baked_atlas = atlas_builder.build(stack, "blocks")
    chunk_count = baked_atlas.get_chunk_count()
    (atlas_dir / "atlas_mapping.json").write_text(baked_atlas.to_mapping_json(), encoding="utf-8")

    for i in range(chunk_count):
        _, _, _, _, stem = baked_atlas.get_chunk_meta(i)
        (atlas_dir / f"{stem}.png").write_bytes(baked_atlas.get_chunk_albedo_png_bytes(i))
        normal_bytes = baked_atlas.get_chunk_normal_png_bytes(i)
        if normal_bytes is not None:
            (atlas_dir / f"{stem}_n.png").write_bytes(normal_bytes)
        specular_bytes = baked_atlas.get_chunk_specular_png_bytes(i)
        if specular_bytes is not None:
            (atlas_dir / f"{stem}_s.png").write_bytes(specular_bytes)

    sa_builder = libmtk_py.StandaloneBuilder()
    sa_res = sa_builder.build(stack, str(standalone_dir.resolve()))

    baker = libmtk_py.ModelBaker()
    model_db = baker.bake_all(stack)
    if hasattr(model_db, "deduplicate_all"):
        model_db.deduplicate_all()
    (models_dir / "models.bin").write_bytes(model_db.to_bincode_bytes())

    get_cache_stats(prefs, force_refresh=True)
    duration = time.time() - start_time
    return {
        "success": True,
        "pack_count": stack.get_pack_count(),
        "atlas_chunks": chunk_count,
        "standalone_textures": sa_res.texture_count,
        "baked_models": len(model_db),
        "models": len(model_db),
        "duration_seconds": duration,
        "cache_dir": str(base_cache),
    }


def load_baked_model_database(prefs=None, verify_fingerprint: bool = True) -> Optional[Any]:
    """
    Loads the precompiled binary model database from cache into memory.
    Optionally verifies that cache_manifest.json matches the active resource pack stack fingerprint.
    Returns None if cache does not exist, is stale, or libmtk is unavailable.
    """
    mtk = _get_libmtk()
    if mtk is None:
        return None

    cache_dir = get_cache_dir(prefs)
    manifest_file = cache_dir / "cache_manifest.json"
    models_bin = cache_dir / "models" / "models.bin"
    if not models_bin.exists():
        return None

    if verify_fingerprint and manifest_file.exists():
        try:
            import json
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            stack = get_configured_pack_stack(prefs)
            if stack is not None and hasattr(stack, "compute_stack_fingerprint"):
                current_fp = stack.compute_stack_fingerprint()
                if manifest.get("fingerprint") != current_fp:
                    # Stale cache detected: resource pack stack changed
                    return None
        except Exception:
            pass

    try:
        raw_bytes = models_bin.read_bytes()
        model_db = mtk.BakedModelDatabase.from_bincode_bytes(raw_bytes)
        if hasattr(model_db, "deduplicate_all"):
            culled = model_db.deduplicate_all()
            if culled > 0:
                try:
                    models_bin.write_bytes(model_db.to_bincode_bytes())
                except Exception:
                    pass
        return model_db
    except Exception:
        return None


def load_baked_atlas_from_cache(prefs=None) -> Optional[Any]:
    """
    Loads precompiled BakedAtlas from cache into memory.
    Returns None if cache does not exist or libmtk is unavailable.
    """
    mtk = _get_libmtk()
    if mtk is None:
        return None

    cache_dir = get_cache_dir(prefs)
    mapping_file = cache_dir / "atlas" / "atlas_mapping.json"
    if not mapping_file.exists():
        return None

    try:
        json_str = mapping_file.read_text(encoding="utf-8")
        return mtk.BakedAtlas.from_mapping_json(json_str)
    except Exception:
        return None


def load_biome_resolver_from_cache(prefs=None) -> Optional[Any]:
    """
    Loads precompiled BiomeResolver from cache into memory.
    Falls back to a default Vanilla 1.21+ BiomeResolver if cache file is missing.
    Returns None only if libmtk is unavailable.
    """
    mtk = _get_libmtk()
    if mtk is None:
        return None

    cache_dir = get_cache_dir(prefs)
    candidates = [
        cache_dir / "biome_mapping.json",
        cache_dir / "atlas" / "biome_mapping.json",
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            try:
                return mtk.BiomeResolver.from_file(str(c.resolve()))
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
    Reads cache_manifest.json from the active cache directory if it exists.
    Returns parsed dictionary or None.
    """
    cache_dir = get_cache_dir(prefs)
    manifest_file = cache_dir / "cache_manifest.json"
    if not manifest_file.exists():
        return None
    try:
        import json
        return json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_cache_fingerprint(prefs=None) -> Optional[str]:
    """
    Returns the active resource pack stack fingerprint recorded in cache_manifest.json,
    or None if cache does not exist.
    """
    manifest = get_cache_manifest(prefs)
    if manifest and isinstance(manifest, dict):
        return manifest.get("fingerprint")
    return None


def get_cache_timestamp(prefs=None) -> float:
    """
    Returns creation epoch seconds recorded in cache_manifest.json or file modification time.
    Returns 0.0 if cache does not exist.
    """
    manifest = get_cache_manifest(prefs)
    if manifest and isinstance(manifest, dict) and "created_at_epoch_secs" in manifest:
        try:
            return float(manifest["created_at_epoch_secs"])
        except (ValueError, TypeError):
            pass

    cache_dir = get_cache_dir(prefs)
    candidates = [
        cache_dir / "cache_manifest.json",
        cache_dir / "atlas" / "atlas_mapping.json",
        cache_dir / "models" / "models.bin",
    ]
    for c in candidates:
        if c.exists():
            try:
                return float(c.stat().st_mtime)
            except Exception:
                pass
    return 0.0


def check_cache_dirty(
    cached_fingerprint: Optional[str] = None,
    cached_timestamp: float = 0.0,
    prefs=None,
) -> Tuple[bool, Optional[str], float]:
    """
    Compares cached fingerprint and timestamp with the current on-disk asset cache.
    Returns (is_dirty, current_fingerprint, current_timestamp).
    """
    current_fp = get_cache_fingerprint(prefs)
    current_ts = get_cache_timestamp(prefs)

    # If neither fingerprint nor timestamp was previously recorded, consider dirty if cache exists
    if cached_fingerprint is None and cached_timestamp == 0.0:
        is_dirty = current_fp is not None or current_ts > 0.0
        return is_dirty, current_fp, current_ts

    # Fingerprint mismatch
    if current_fp != cached_fingerprint:
        return True, current_fp, current_ts

    # Timestamp mismatch (file rewritten or recompiled)
    if abs(current_ts - cached_timestamp) > 1e-3:
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


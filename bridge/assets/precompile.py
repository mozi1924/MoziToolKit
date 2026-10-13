"""
Asset Precompilation Execution Engine.
Invokes headless multi-threaded baking in libmtk and triggers
Blender image datablock live reloading.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..engine import get_libmtk
from ..progress import ProgressCallback, wrap_progress_callback
from .cache import (
    get_cache_dir,
    get_cache_stats,
    invalidate_asset_cache_memory,
)
from .pack import get_configured_pack_stack

logger = logging.getLogger("MoziToolKit.Bridge.Assets.Precompile")


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
    mtk = get_libmtk()
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

    raise RuntimeError("libmtk_py is missing precompile_all_assets export.")


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


__all__ = [
    "precompile_stack",
    "precompile_stack_async",
    "reload_atlas_images",
]

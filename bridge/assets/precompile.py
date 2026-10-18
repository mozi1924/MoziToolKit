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
    invalidate_asset_cache_memory,
)
from .pack import get_configured_pack_stack

logger = logging.getLogger("MoziToolKit.Bridge.Assets.Precompile")


def precompile_stack(
    prefs=None,
    num_threads: Optional[int] = None,
    progress_callback: Optional[ProgressCallback] = None,
    stack: Optional[Any] = None,
    cache_dir: Optional[str] = None,
    reload_images: bool = True,
    resolve_prefs: bool = True,
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

    if stack is None:
        stack = get_configured_pack_stack(prefs)
    if stack is None or stack.get_pack_count() == 0:
        raise ValueError("No valid enabled resource packs or JARs found in the active stack.")

    if resolve_prefs and num_threads is None and prefs is not None:
        raw_threads = getattr(prefs, "thread_count", 0)
        num_threads = raw_threads if isinstance(raw_threads, int) and not isinstance(raw_threads, bool) and raw_threads > 0 else None
    elif num_threads == 0:
        num_threads = None

    start_time = time.time()
    # cache_dir is resolved on the Blender main thread by the caller when this
    # function runs in an AsyncTask worker (resolve/precompile split).
    base_cache = Path(cache_dir) if cache_dir else get_cache_dir(prefs)

    wrapped_cb = wrap_progress_callback(progress_callback)

    # Use unified high-performance Rust engine with thread pool control & progress callback
    if hasattr(mtk, "precompile_all_assets"):
        res = mtk.precompile_all_assets(
            stack,
            str(base_cache.resolve()),
            atlas_category="blocks",
            max_atlas_width=4096,
            max_atlas_height=4096,
            compile_atlas=True,
            compile_models=True,
            num_threads=num_threads,
            callback=wrapped_cb,
        )
        package_path = getattr(res, "package_path", "")
        invalidate_asset_cache_memory()
        try:
            from ..world import clear_world_sessions
            clear_world_sessions()
        except Exception:
            pass
        # Never touch bpy from a worker thread. The main-thread caller refreshes
        # image datablocks after this function returns (synchronous call sites
        # keep reload_images=True; AsyncTask call sites pass False and run the
        # reload in on_success).
        if reload_images:
            try:
                reload_atlas_images(prefs)
            except Exception:
                pass
        duration = time.time() - start_time

        return {
            "success": getattr(res, "success", True),
            "pack_count": getattr(res, "pack_count", 0),
            "atlas_chunks": getattr(res, "atlas_chunks", 0),
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
    stack: Optional[Any] = None,
    cache_dir: Optional[str] = None,
    resolve_prefs: bool = False,
):
    """
    Executes precompile_stack asynchronously in a background worker thread.
    Takes advantage of libmtk_py releasing the Python GIL to prevent freezing Blender UI.
    """
    import concurrent.futures

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def worker():
        try:
            # Worker thread: never touch bpy. on_complete runs on this worker too;
            # callers that need image reload must schedule it on the main thread.
            res = precompile_stack(
                prefs,
                num_threads=num_threads,
                progress_callback=progress_callback,
                stack=stack,
                cache_dir=cache_dir,
                reload_images=False,
                resolve_prefs=resolve_prefs,
            )
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
    or compiled .mtkcache container, refreshing image pixels and mipmaps so changes immediately
    reflect on screen.
    Returns the count of successfully reloaded images.
    """
    try:
        import bpy
    except ImportError:
        return 0

    if not hasattr(bpy, "data") or not hasattr(bpy.data, "images"):
        return 0

    cache_dir = get_cache_dir(prefs)
    atlas_dir = cache_dir / "atlas"
    atlas_dir_str = str(atlas_dir.resolve()).lower()

    reloaded_count = 0

    # 1. Reload file-backed images
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

    # 2. Reload in-memory packed atlas images from active cache package
    try:
        from .cache import load_baked_atlas_from_cache
        active_atlas = load_baked_atlas_from_cache(prefs)
        if active_atlas is not None and hasattr(active_atlas, "get_all_chunks_info"):
            chunks_info = active_atlas.get_all_chunks_info()
            for cm in chunks_info:
                cid = cm.get("chunk_id", 0)
                cat = cm.get("category", "blocks")
                c_idx = cm.get("category_chunk_index", cid + 1)
                is_anim = cm.get("is_animated", False)
                stem = cm.get("file_stem") or (f"{cat}_anim_chunk_{c_idx:03}" if is_anim else f"{cat}_chunk_{c_idx:03}")
                w = int(cm.get("width", 4096))
                h = int(cm.get("height", 4096))

                cand_names = [f"{stem}.png", stem, f"{cat}_chunk_{c_idx:03}.png"]
                img = None
                for nm in cand_names:
                    img = bpy.data.images.get(nm)
                    if img is not None:
                        break
                f32_tuple = None
                if active_atlas is not None and hasattr(active_atlas, "get_chunk_albedo_f32"):
                    try:
                        albedo_f32 = active_atlas.get_chunk_albedo_f32(cid, flip_v=True)
                        if albedo_f32 is not None:
                            f32_tuple = (w, h, albedo_f32)
                    except Exception:
                        pass
                if f32_tuple is None:
                    from .cache import get_cached_texture_f32
                    f32_tuple = get_cached_texture_f32(f"atlas/textures/{stem}.png", prefs=prefs, flip_y=True)

                if img is not None and f32_tuple is not None:
                    _, _, albedo_f32 = f32_tuple
                    try:
                        if img.size[0] != w or img.size[1] != h:
                            img.scale(w, h)
                        mv = memoryview(albedo_f32)
                        if mv.format != "f":
                            mv = mv.cast("f")
                        img.pixels.foreach_set(mv)
                        img.update()
                        reloaded_count += 1
                    except Exception:
                        pass
    except Exception as e:
        logger.debug("Failed refreshing in-memory atlas images: %s", e)

    return reloaded_count


__all__ = [
    "precompile_stack",
    "precompile_stack_async",
    "reload_atlas_images",
]

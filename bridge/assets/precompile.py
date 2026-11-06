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
    resolve_prefs: bool = True,
    resolver_overrides_json: Optional[str] = None,
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
    if cache_dir is None and prefs is not None and getattr(prefs, "cache_dir", None):
        cache_dir = getattr(prefs, "cache_dir")
    base_cache = Path(cache_dir) if cache_dir else get_cache_dir(prefs)

    wrapped_cb = wrap_progress_callback(progress_callback)

    # Release our memory-mapped .mtkcache handle before the Rust writer publishes
    # the replacement. The writer stages to a temp file and renames atomically,
    # so readers on POSIX keep a valid snapshot; Windows cannot replace a
    # destination that still has an open mapped view, so drop it first.
    invalidate_asset_cache_memory()

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
            resolver_overrides_json=resolver_overrides_json,
        )
        package_path = getattr(res, "package_path", "")
        if hasattr(res, "profile") and res.profile is not None:
            from ..diagnostics import record_operation_profile

            record_operation_profile("Precompile Assets", res.profile)
        invalidate_asset_cache_memory()
        try:
            from ..world import clear_world_sessions
            clear_world_sessions()
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



__all__ = [
    "precompile_stack",
    "precompile_stack_async",
]

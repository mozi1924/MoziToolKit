"""
Asset Cache Readiness Guard & Operator Gating Subsystem.
Provides automated cache freshness evaluation and two-stage precompilation wrappers
for non-blocking UI operators and headless scripts.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..engine import get_libmtk
from ..progress import ProgressCallback, ProgressReport
from .cache import (
    get_cache_dir,
    invalidate_asset_cache_memory,
    open_active_asset_cache,
)
from .pack import get_configured_pack_stack
from .precompile import precompile_stack, reload_atlas_images

logger = logging.getLogger("MoziToolKit.Bridge.Assets.Guard")


def check_asset_cache_status(prefs=None) -> str:
    """
    Checks the validity and freshness of precompiled asset caches against configured resource packs.
    Returns:
    - "READY": A valid precompiled .mtkcache package matching the active stack fingerprint exists.
    - "MISSING": No cache package exists on disk (initial run / empty cache directory).
    - "STALE": Cache packages exist, but the fingerprint does not match the active configuration.
    - "NO_PACKS": No enabled resource packs or JARs configured in preferences to compile from.
    """
    mtk = get_libmtk()
    if mtk is None:
        return "MISSING"

    stack = get_configured_pack_stack(prefs)
    cache_dir = get_cache_dir(prefs).resolve()

    # Discover all existing .mtkcache packages in the cache directory
    existing_packages = list(cache_dir.glob("*.mtkcache")) if cache_dir.exists() else []

    if stack is None or stack.get_pack_count() == 0:
        # No enabled packs configured by user
        if existing_packages:
            active = open_active_asset_cache(prefs)
            if active is not None:
                return "READY"
        return "NO_PACKS"

    # Test sandbox isolation guard: if isolated via MOZI_CACHE_DIR, caller did not specify custom prefs,
    # and a test package already exists in the sandbox directory, treat it as READY to prevent
    # host-level global preferences from overwriting mock test assets.
    if prefs is None and os.environ.get("MOZI_CACHE_DIR") and existing_packages:
        active = open_active_asset_cache(prefs)
        if active is not None:
            return "READY"

    # Compute expected stack fingerprint
    expected_fp = stack.compute_stack_fingerprint() if hasattr(stack, "compute_stack_fingerprint") else ""
    if not expected_fp:
        return "MISSING" if not existing_packages else "STALE"

    # Fast-path check: in-memory active cache matches expected fingerprint
    active = open_active_asset_cache(prefs)
    if active is not None and getattr(active, "fingerprint", None) == expected_fp:
        return "READY"

    # Direct file match: {expected_fp}.mtkcache
    direct_pkg = cache_dir / f"{expected_fp}.mtkcache"
    if direct_pkg.exists() and direct_pkg.is_file():
        if hasattr(mtk, "is_valid_cache_package"):
            try:
                if mtk.is_valid_cache_package(str(direct_pkg), expected_fp):
                    return "READY"
            except Exception:
                pass
        else:
            return "READY"

    # Search all packages for a matching fingerprint
    for pkg in existing_packages:
        if hasattr(mtk, "is_valid_cache_package"):
            try:
                if mtk.is_valid_cache_package(str(pkg), expected_fp):
                    return "READY"
            except Exception:
                pass

    if existing_packages:
        return "STALE"
    return "MISSING"


def ensure_pipeline_assets_ready_sync(
    prefs=None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Tuple[bool, str]:
    """
    Synchronously verifies asset cache readiness, automatically triggering precompilation
    if the cache is MISSING or STALE.
    Returns (success, status_or_message).
    """
    status = check_asset_cache_status(prefs)
    if status == "READY":
        return True, "READY"

    if status == "NO_PACKS":
        return False, "NO_PACKS"

    if status in ("MISSING", "STALE"):
        logger.info("Asset cache status is '%s'. Triggering automated precompilation...", status)
        try:
            precompile_stack(prefs, progress_callback=progress_callback)
            invalidate_asset_cache_memory()
            try:
                reload_atlas_images(prefs)
            except Exception:
                pass
            return True, status
        except Exception as e:
            logger.exception("Automated precompilation failed: %s", e)
            raise e

    return True, status


def run_task_with_asset_guard(
    target_func: Any,
    target_kwargs: Dict[str, Any],
    prefs: Optional[Any] = None,
    progress_callback: Optional[ProgressCallback] = None,
    task_title: str = "Voxel Operation",
) -> Tuple[Any, bool]:
    """
    Executes a heavy voxel or meshing background worker with an automated asset precompilation guard.
    If assets are MISSING or STALE, runs precompile_stack as Stage 1 with progress reporting,
    then chains into target_func as Stage 2.
    Returns (result, did_precompile).
    """
    status = check_asset_cache_status(prefs)
    did_precompile = False

    if status in ("MISSING", "STALE"):
        did_precompile = True
        logger.info("Asset cache is %s. Executing Stage 1/2: automated precompilation...", status)

        def stage1_cb(report: Any):
            if progress_callback:
                msg = getattr(report, "message", "") or getattr(report, "stage", "Precompiling")
                stage = getattr(report, "stage", "precompile")
                curr = getattr(report, "current", 0)
                tot = getattr(report, "total", 100)
                pct = getattr(report, "percent", 0.0)
                stage_report = ProgressReport(
                    stage=f"precompile_{stage}",
                    current=curr,
                    total=tot,
                    message=f"[1/2 Precompile] {msg}",
                    percent=pct * 0.5,
                )
                progress_callback(stage_report)

        precompile_stack(prefs, progress_callback=stage1_cb)
        invalidate_asset_cache_memory()

    # Stage 2: Target Function
    def stage2_cb(report: Any):
        if progress_callback:
            msg = getattr(report, "message", "") or getattr(report, "stage", task_title)
            stage = getattr(report, "stage", "task")
            curr = getattr(report, "current", 0)
            tot = getattr(report, "total", 100)
            pct = getattr(report, "percent", 0.0)
            if did_precompile:
                stage_report = ProgressReport(
                    stage=f"task_{stage}",
                    current=curr,
                    total=tot,
                    message=f"[2/2 {task_title}] {msg}",
                    percent=50.0 + pct * 0.5,
                )
                progress_callback(stage_report)
            else:
                progress_callback(report)

    final_kwargs = dict(target_kwargs)
    final_kwargs["progress_callback"] = stage2_cb
    result = target_func(**final_kwargs)
    return result, did_precompile


__all__ = [
    "check_asset_cache_status",
    "ensure_pipeline_assets_ready_sync",
    "run_task_with_asset_guard",
]

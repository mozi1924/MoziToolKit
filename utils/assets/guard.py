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

from ...bridge.engine import get_libmtk
from ...bridge.progress import ProgressCallback, ProgressReport
from ...utils.system import get_prefs
from ...i18n import tr


def _get_configured_pack_stack(prefs=None):
    from ...bridge.assets.pack import get_configured_pack_stack
    return get_configured_pack_stack(prefs)


def _open_active_asset_cache(prefs=None):
    from ...bridge.assets.cache import open_active_asset_cache
    return open_active_asset_cache(prefs)


def _invalidate_asset_cache_memory():
    from ...bridge.assets.cache import invalidate_asset_cache_memory
    return invalidate_asset_cache_memory()


def _precompile_stack(*args, **kwargs):
    from ...bridge.assets.precompile import precompile_stack
    return precompile_stack(*args, **kwargs)


def _reload_atlas_images(*args, **kwargs):
    from ..materials.builder.atlas_refresh import reload_atlas_images
    return reload_atlas_images(*args, **kwargs)

from .cache_utils import get_cache_dir

logger = logging.getLogger("MoziToolKit.Utils.Assets.Guard")


#: Host-level asset roots / archives honoured when no preferences are registered (CLI, CI).
ENV_ASSET_ROOTS = ("MC_DIR", "MC_ASSETS_DIR", "MTK_TEST_ASSETS")
ENV_ASSET_ARCHIVES = ("MTK_TEST_JAR", "MC_JAR")

#: Block identifiers probed by Rust core for canonical base foundation.
BASE_PROBE_BLOCKS = ("stone", "dirt", "oak_planks")

_VANILLA_PROBE_CACHE: Dict[Tuple[str, int, int], bool] = {}
_VANILLA_CHECK_CACHE: Dict[Any, bool] = {}
_GUARD_STATUS_CACHE: Dict[Any, str] = {}


def invalidate_guard_cache() -> None:
    """Invalidate all cached pack readiness and cache status evaluations."""
    _VANILLA_PROBE_CACHE.clear()
    _VANILLA_CHECK_CACHE.clear()
    _GUARD_STATUS_CACHE.clear()


def _get_pack_signature(prefs=None) -> tuple:
    if prefs is None:
        try:
            prefs = get_prefs()
        except Exception:
            prefs = None
    packs = getattr(prefs, "resource_packs", None) or []
    entries = []
    for e in packs:
        raw = getattr(e, "path", "") or ""
        enabled = getattr(e, "enabled", True)
        pt = getattr(e, "pack_type", "")
        mtime = 0.0
        if raw:
            try:
                mtime = os.path.getmtime(raw)
            except OSError:
                mtime = 0.0
        entries.append((raw, enabled, pt, mtime))
    single = getattr(prefs, "resource_pack_path", "") or ""
    single_mtime = 0.0
    if single:
        try:
            single_mtime = os.path.getmtime(single)
        except OSError:
            single_mtime = 0.0
    env_sig = tuple((k, os.environ.get(k, "")) for k in ENV_ASSET_ROOTS + ENV_ASSET_ARCHIVES)
    return (tuple(entries), single, single_mtime, env_sig)


def _path_provides_vanilla_client(path: Path) -> bool:
    """Single source of truth for 'can this path serve as the vanilla client foundation'.
    Delegates directly to libmtk native core (GEMINI.md Rule 1 & Rule 2).
    """
    mtk = get_libmtk()
    if mtk is None:
        raise RuntimeError("libmtk native core is required for vanilla client validation")
    try:
        if not path.exists():
            return False
        stat = path.stat()
        key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return False

    if key in _VANILLA_PROBE_CACHE:
        return _VANILLA_PROBE_CACHE[key]

    res = mtk.path_provides_vanilla_client(str(path.resolve()))
    _VANILLA_PROBE_CACHE[key] = res
    return res


def _is_entry_valid_vanilla_client(entry: Any) -> bool:
    """Whether a resource-pack entry is enabled and provides vanilla client assets."""
    if not getattr(entry, "enabled", True):
        return False
    raw_path = getattr(entry, "path", "")
    if not raw_path or not isinstance(raw_path, str):
        return False
    return _path_provides_vanilla_client(Path(raw_path.strip()))


def _has_configured_packs(prefs: Any) -> bool:
    """True when the preferences actually configure at least one pack entry."""
    for entry in getattr(prefs, "resource_packs", None) or []:
        raw_path = getattr(entry, "path", "")
        if isinstance(raw_path, str) and raw_path.strip():
            return True
    single_path = getattr(prefs, "resource_pack_path", None)
    return isinstance(single_path, str) and bool(single_path.strip())


def has_valid_vanilla_pack(prefs=None) -> bool:
    """
    Checks whether the active configuration can provide Minecraft client assets.
    """
    sig = _get_pack_signature(prefs)
    if sig in _VANILLA_CHECK_CACHE:
        return _VANILLA_CHECK_CACHE[sig]

    if prefs is None:
        try:
            prefs = get_prefs()
        except Exception:
            prefs = None

    result = False
    if prefs is not None:
        for entry in getattr(prefs, "resource_packs", None) or []:
            if _is_entry_valid_vanilla_client(entry):
                result = True
                break

        if not result:
            single_path = getattr(prefs, "resource_pack_path", None)
            if isinstance(single_path, str) and single_path.strip():
                if _path_provides_vanilla_client(Path(single_path.strip())):
                    result = True

        # A stack is configured but none of it can back the pipeline: fail closed.
        if not result and _has_configured_packs(prefs):
            _VANILLA_CHECK_CACHE[sig] = False
            return False

    if not result:
        # No packs configured (CLI / CI / first run): the host environment may point at
        # unpacked client assets or a client JAR, still subject to the content check.
        for env_var in ENV_ASSET_ROOTS + ENV_ASSET_ARCHIVES:
            val = os.environ.get(env_var)
            if val and _path_provides_vanilla_client(Path(val)):
                result = True
                break

    _VANILLA_CHECK_CACHE[sig] = result
    return result


def can_execute_asset_pipeline(prefs=None) -> Tuple[bool, str]:
    """
    Evaluates whether the asset pipeline (meshing, material replacement, precompilation) can be executed.
    Returns (can_execute, reason_message).
    When False, reason_message provides a clear, user-facing explanation suitable for UI tooltips or reports.
    """
    if not has_valid_vanilla_pack(prefs):
        status = check_asset_cache_status(prefs)
        if status == "NO_PACKS":
            return False, tr("No Minecraft resource packs configured. Please configure a Vanilla Client JAR in Preferences.")
        return False, tr("A Minecraft Vanilla Client JAR is required. Resource packs and mods cannot be used without a vanilla base pack.")
    return True, ""


def check_asset_cache_status(prefs=None) -> str:
    """
    Checks the validity and freshness of precompiled asset caches against configured resource packs.
    Returns:
    - "READY": A valid precompiled .mtkcache package matching the active stack fingerprint exists.
    - "MISSING": Valid vanilla client pack is configured, but no cache package exists on disk.
    - "STALE": Cache packages exist, but the fingerprint does not match the active configuration.
    - "NO_PACKS": No resource packs or JARs configured or enabled in preferences.
    - "NO_VANILLA": Resource packs or mod JARs are configured, but no valid Vanilla Client JAR base pack is enabled.
    """
    sig = _get_pack_signature(prefs)
    cache_dir = get_cache_dir(prefs).resolve()
    cache_dir_mtime = 0.0
    if cache_dir.exists():
        try:
            cache_dir_mtime = os.path.getmtime(cache_dir)
        except OSError:
            cache_dir_mtime = 0.0
    cache_key = (sig, str(cache_dir), cache_dir_mtime)
    if cache_key in _GUARD_STATUS_CACHE:
        return _GUARD_STATUS_CACHE[cache_key]

    mtk = get_libmtk()
    if mtk is None:
        return "MISSING"

    stack = _get_configured_pack_stack(prefs)
    pack_count = stack.get_pack_count() if stack is not None else 0
    if pack_count == 0:
        _GUARD_STATUS_CACHE[cache_key] = "NO_PACKS"
        return "NO_PACKS"

    has_vanilla = has_valid_vanilla_pack(prefs)
    if not has_vanilla:
        _GUARD_STATUS_CACHE[cache_key] = "NO_VANILLA"
        return "NO_VANILLA"

    expected_fp = stack.compute_stack_fingerprint() if hasattr(stack, "compute_stack_fingerprint") else ""

    # Test sandbox isolation guard
    has_custom_packs = prefs is not None and hasattr(prefs, "resource_packs")
    is_test_sandbox = os.environ.get("MTK_TEST_SANDBOX") == "1"
    existing_packages = list(cache_dir.glob("*.mtkcache")) if cache_dir.exists() else []
    if not has_custom_packs and is_test_sandbox and existing_packages:
        active = _open_active_asset_cache(prefs)
        if active is not None:
            _GUARD_STATUS_CACHE[cache_key] = "READY"
            return "READY"

    # Fast-path check: in-memory active cache matches expected fingerprint
    active = _open_active_asset_cache(prefs)
    if active is not None and getattr(active, "fingerprint", None) == expected_fp:
        _GUARD_STATUS_CACHE[cache_key] = "READY"
        return "READY"

    status = mtk.evaluate_cache_status(str(cache_dir), pack_count, has_vanilla, expected_fp)
    _GUARD_STATUS_CACHE[cache_key] = status
    return status


def prepare_asset_context(prefs=None) -> Dict[str, Any]:
    """Resolve cache status/stack/path on the Blender main thread."""
    status = check_asset_cache_status(prefs)
    stack = _get_configured_pack_stack(prefs)
    try:
        cache_dir = str(get_cache_dir(prefs))
    except Exception:
        cache_dir = None
    raw_threads = getattr(prefs, "thread_count", 0) if prefs is not None else 0
    num_threads = raw_threads if isinstance(raw_threads, int) and not isinstance(raw_threads, bool) and raw_threads > 0 else None
    return {"status": status, "stack": stack, "cache_dir": cache_dir, "num_threads": num_threads}


def ensure_pipeline_assets_ready_sync(
    prefs=None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Tuple[bool, str]:
    """
    Synchronously verifies asset cache readiness, automatically triggering precompilation
    if the cache is MISSING or STALE.
    """
    status = check_asset_cache_status(prefs)
    if status == "READY":
        return True, "READY"

    if status in ("NO_PACKS", "NO_VANILLA"):
        return False, status

    if status in ("MISSING", "STALE"):
        logger.info("Asset cache status is '%s'. Triggering automated precompilation...", status)
        try:
            _precompile_stack(prefs, progress_callback=progress_callback)
            _invalidate_asset_cache_memory()
            return True, status
        except Exception as e:
            logger.exception("Automated precompilation failed: %s", e)
            raise e

    return True, status


def run_task_with_asset_guard(
    target_func: Any,
    target_kwargs: Optional[Dict[str, Any]] = None,
    prefs=None,
    progress_callback: Optional[ProgressCallback] = None,
    task_title: str = "Processing",
    asset_context: Optional[Dict[str, Any]] = None,
) -> Tuple[Any, bool]:
    """
    Execution wrapper guarding operations requiring precompiled assets.
    Executes a two-stage pipeline:
    - Stage 1: Automated asset precompilation (0% - 50% progress) if cache is MISSING or STALE.
    - Stage 2: Target operation execution (50% - 100% progress).
    Returns (result, did_precompile).
    """
    if target_kwargs is None:
        target_kwargs = {}

    status = asset_context.get("status") if asset_context else check_asset_cache_status(prefs)

    if status in ("NO_PACKS", "NO_VANILLA"):
        raise RuntimeError(
            f"Cannot execute task: asset cache status is '{status}'. A Minecraft Vanilla Client JAR must be configured."
        )

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

        _precompile_stack(
            prefs,
            num_threads=asset_context.get("num_threads") if asset_context else None,
            progress_callback=stage1_cb,
            stack=asset_context.get("stack") if asset_context else None,
            cache_dir=asset_context.get("cache_dir") if asset_context else None,
            resolve_prefs=asset_context is None,
        )
        _invalidate_asset_cache_memory()

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
    "has_valid_vanilla_pack",
    "can_execute_asset_pipeline",
    "prepare_asset_context",
    "check_asset_cache_status",
    "ensure_pipeline_assets_ready_sync",
    "run_task_with_asset_guard",
]

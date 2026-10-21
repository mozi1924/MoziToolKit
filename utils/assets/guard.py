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

try:
    from ...bridge.engine import get_libmtk
    from ...bridge.progress import ProgressCallback, ProgressReport
    from ...utils.system import get_prefs
    from ...utils.pack_detect import (
        VALID_BASE_PACK_KINDS,
        peek_cached_probe,
        detect_pack_kind,
    )
    from ...i18n import tr
except (ImportError, ValueError):
    from bridge.engine import get_libmtk
    from bridge.progress import ProgressCallback, ProgressReport
    try:
        from utils.system import get_prefs
    except (ImportError, ValueError):
        def get_prefs(context=None):
            return None
    try:
        from utils.pack_detect import (
            VALID_BASE_PACK_KINDS,
            peek_cached_probe,
            detect_pack_kind,
        )
    except (ImportError, ValueError):
        VALID_BASE_PACK_KINDS = frozenset({"VANILLA_CLIENT"})
        def peek_cached_probe(path):
            return None
        def detect_pack_kind(path):
            return type("PackProbe", (), {"kind": "UNKNOWN"})()
    try:
        from i18n import tr
    except (ImportError, ValueError):
        def tr(msgid: str, msgctxt: str | None = None) -> str:
            return msgid


def _get_configured_pack_stack(prefs=None):
    try:
        from ...bridge.assets.pack import get_configured_pack_stack
    except (ImportError, ValueError):
        from bridge.assets.pack import get_configured_pack_stack
    return get_configured_pack_stack(prefs)


def _open_active_asset_cache(prefs=None):
    try:
        from ...bridge.assets.cache import open_active_asset_cache
    except (ImportError, ValueError):
        from bridge.assets.cache import open_active_asset_cache
    return open_active_asset_cache(prefs)


def _invalidate_asset_cache_memory():
    try:
        from ...bridge.assets.cache import invalidate_asset_cache_memory
    except (ImportError, ValueError):
        from bridge.assets.cache import invalidate_asset_cache_memory
    return invalidate_asset_cache_memory()


def _precompile_stack(*args, **kwargs):
    try:
        from ...bridge.assets.precompile import precompile_stack
    except (ImportError, ValueError):
        from bridge.assets.precompile import precompile_stack
    return precompile_stack(*args, **kwargs)


def _reload_atlas_images(*args, **kwargs):
    try:
        from ...bridge.assets.precompile import reload_atlas_images
    except (ImportError, ValueError):
        from bridge.assets.precompile import reload_atlas_images
    return reload_atlas_images(*args, **kwargs)

from .cache_utils import get_cache_dir

logger = logging.getLogger("MoziToolKit.Utils.Assets.Guard")


#: Subdirectories a pack must provide to be able to back the whole client asset pipeline.
CLIENT_ASSET_ROOTS = ("blockstates", "models", "textures")

#: Host-level asset roots / archives honoured when no preferences are registered (CLI, CI).
ENV_ASSET_ROOTS = ("MC_DIR", "MC_ASSETS_DIR", "MTK_TEST_ASSETS")
ENV_ASSET_ARCHIVES = ("MTK_TEST_JAR", "MC_JAR")


def _probe_archive(path: Path) -> Any:
    """Returns a cached probe when available, otherwise classifies the archive once."""
    probe = peek_cached_probe(str(path.resolve()))
    return probe if probe is not None else detect_pack_kind(path)


def _path_provides_vanilla_client(path: Path) -> bool:
    """Single source of truth for "can this path serve as the vanilla client foundation".

    - An unpacked client tree must expose ``assets/minecraft/{blockstates,models,textures}``.
    - An archive must be content-classified as a vanilla *client* jar. A server jar,
      mod jar, or plain resource pack is rejected regardless of how the user tagged it.
    - ``pack_type`` / ``detected_kind`` metadata is never trusted: both are user-editable.
    """
    if path.is_dir():
        root = path / "assets" / "minecraft"
        return all((root / part).is_dir() for part in CLIENT_ASSET_ROOTS)

    if path.is_file() and path.suffix.lower() in (".jar", ".zip"):
        probe = _probe_archive(path)
        return probe is not None and probe.kind in VALID_BASE_PACK_KINDS

    return False


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

    Accepted sources, in order:
    1. An enabled entry in ``prefs.resource_packs`` (JAR classified as vanilla client,
       or an unpacked tree with the full client asset roots).
    2. The legacy single ``prefs.resource_pack_path``.
    3. A host-level asset root/archive from the environment (CLI/CI/dev), which must
       satisfy the exact same content check.

    Environment variables only apply while **no packs are configured at all**. Once the
    user has configured a stack, a non-qualifying stack is a hard failure -- the
    environment can never rescue a wrong configuration.

    Resource packs that only override a namespace, mod JARs, vanilla server JARs, and
    empty directories do NOT qualify.
    """
    if prefs is None:
        try:
            prefs = get_prefs()
        except Exception:
            prefs = None

    if prefs is not None:
        for entry in getattr(prefs, "resource_packs", None) or []:
            if _is_entry_valid_vanilla_client(entry):
                return True

        single_path = getattr(prefs, "resource_pack_path", None)
        if isinstance(single_path, str) and single_path.strip():
            if _path_provides_vanilla_client(Path(single_path.strip())):
                return True

        # A stack is configured but none of it can back the pipeline: fail closed.
        if _has_configured_packs(prefs):
            return False

    # No packs configured (CLI / CI / first run): the host environment may point at
    # unpacked client assets or a client JAR, still subject to the content check.
    for env_var in ENV_ASSET_ROOTS + ENV_ASSET_ARCHIVES:
        val = os.environ.get(env_var)
        if val and _path_provides_vanilla_client(Path(val)):
            return True

    return False


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
    mtk = get_libmtk()
    if mtk is None:
        return "MISSING"

    stack = _get_configured_pack_stack(prefs)
    cache_dir = get_cache_dir(prefs).resolve()

    # Discover all existing .mtkcache packages in the cache directory
    existing_packages = list(cache_dir.glob("*.mtkcache")) if cache_dir.exists() else []

    if stack is None or stack.get_pack_count() == 0:
        # No enabled packs configured by user
        # CRITICAL FIX: Never return "READY" just because stale packages exist on disk!
        return "NO_PACKS"

    # Enforce base pack gate: must have a valid Vanilla Client pack
    if not has_valid_vanilla_pack(prefs):
        return "NO_VANILLA"

    # Test sandbox isolation guard: if isolated via MOZI_CACHE_DIR, caller did not specify custom prefs,
    # and a test package already exists in the sandbox directory, treat it as READY to prevent
    # host-level global preferences from overwriting mock test assets.
    if prefs is None and os.environ.get("MOZI_CACHE_DIR") and existing_packages:
        active = _open_active_asset_cache(prefs)
        if active is not None:
            return "READY"

    # Compute expected stack fingerprint
    expected_fp = stack.compute_stack_fingerprint() if hasattr(stack, "compute_stack_fingerprint") else ""
    if not expected_fp:
        return "MISSING" if not existing_packages else "STALE"

    # Fast-path check: in-memory active cache matches expected fingerprint
    active = _open_active_asset_cache(prefs)
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


def prepare_asset_context(prefs=None) -> Dict[str, Any]:
    """Resolve cache status/stack/path on the Blender main thread.

    check_asset_cache_status reads Blender preferences/RNA and resolves the
    cache directory through bpy. Doing that inside an AsyncTask worker is not
    thread-safe. Operators call this helper before launching a worker and pass
    the resulting dict to run_task_with_asset_guard.
    """
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
    Returns (success, status_or_message).
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
            try:
                _reload_atlas_images(prefs)
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
    asset_context: Optional[Dict[str, Any]] = None,
) -> Tuple[Any, bool]:
    """
    Executes a heavy voxel or meshing background worker with an automated asset precompilation guard.
    If assets are MISSING or STALE, runs precompile_stack as Stage 1 with progress reporting,
    then chains into target_func as Stage 2.
    Returns (result, did_precompile).
    """
    if asset_context is not None:
        status = str(asset_context.get("status", "READY"))
    else:
        status = check_asset_cache_status(prefs)
    did_precompile = False

    if status in ("NO_PACKS", "NO_VANILLA"):
        raise RuntimeError(
            f"Cannot execute task: asset cache status is '{status}'. A Minecraft Vanilla Client JAR must be configured."
        )

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
            reload_images=False,
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

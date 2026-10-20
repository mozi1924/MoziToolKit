"""
Host-level asset cache directory resolvers, statistics, and system folder openers.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("MoziToolKit.Utils.Assets.Cache")

try:
    from ..system import get_prefs
except (ImportError, ValueError):
    from utils.system import get_prefs

_cached_cache_stats: Optional[Dict[str, Any]] = None
_cached_cache_stats_path: Optional[str] = None


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


def get_cache_stats(prefs=None, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Returns human-readable and byte statistics for all cached packages on disk.
    Memoized against the resolved cache path string.
    """
    global _cached_cache_stats, _cached_cache_stats_path
    cache_path = get_cache_dir(prefs)
    path_str = str(cache_path)

    if (
        not force_refresh
        and _cached_cache_stats_path is not None
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


def clear_cache(prefs=None, on_invalidate_callback=None) -> int:
    """Empties all compiled caches in the cache directory and returns the total bytes freed."""
    global _cached_cache_stats, _cached_cache_stats_path
    try:
        from ...bridge.assets import invalidate_asset_cache_memory
        invalidate_asset_cache_memory()
    except (ImportError, ValueError):
        try:
            from bridge.assets import invalidate_asset_cache_memory
            invalidate_asset_cache_memory()
        except Exception:
            pass

    if on_invalidate_callback is not None:
        try:
            on_invalidate_callback()
        except Exception:
            pass
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
    "get_cache_stats",
    "clear_cache",
    "open_cache_folder",
]

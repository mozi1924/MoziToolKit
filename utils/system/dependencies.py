"""
Dependency and Environment Utilities for MoziToolKit.
Handles dynamic site-packages path discovery, extension wheels detection,
and runtime dependency status checks for Blender 4.2+ Extensions.
"""

from dataclasses import dataclass
import importlib
import importlib.metadata
import importlib.util
import os
from pathlib import Path
import site
import sys
from functools import lru_cache
import time
from typing import Dict, List, Optional


@dataclass
class Dependency:
    """Definition of an external Python dependency required by MoziToolKit features."""
    name: str              # package name (e.g. "Pillow")
    module_name: str       # import module name (e.g. "PIL")
    display_name: str      # human readable name
    min_version: Optional[str] = None
    description: str = ""
    required_by: str = ""


# Registry of external dependencies used by MoziToolKit
DEPENDENCIES: Dict[str, Dependency] = {
    "Pillow": Dependency(
        name="Pillow",
        module_name="PIL",
        display_name="Pillow (PIL)",
        min_version="9.0.0",
        description="Required for Minecraft Texture Atlas generation & image processing",
        required_by="Atlas Material Mode (Replace Material -> Atlas Mode)",
    ),
    "websockets": Dependency(
        name="websockets",
        module_name="websockets",
        display_name="websockets",
        min_version="13.0",
        description="Required for Minecraft Live Sync with Fabric Mod (Yefira)",
        required_by="Live Sync Panel & Operators",
    ),
}


@lru_cache(maxsize=1)
def get_blender_site_packages() -> List[str]:
    """
    Discover site-packages directories belonging to Blender's Python environment
    and extension-isolated packages directories.
    """
    discovered = []

    # 1. Extension's own site-packages if present
    addon_dir = Path(__file__).parent.parent.parent.resolve()
    ext_sp = addon_dir / "site-packages"
    if ext_sp.exists():
        resolved = str(ext_sp.resolve())
        if resolved not in discovered:
            discovered.append(resolved)

    # 2. Standard Blender Python site-packages
    try:
        sp = site.getsitepackages()
        if isinstance(sp, list):
            for p in sp:
                if p not in discovered and Path(p).exists():
                    discovered.append(p)
    except Exception:
        pass

    # 3. Blender sys.prefix / sys.exec_prefix lib fallback
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    prefix = Path(sys.prefix)
    fallbacks = [
        prefix / "lib" / f"python{py_ver}" / "site-packages",
        prefix / "lib" / "site-packages",
        prefix / "Lib" / "site-packages",  # Windows standard
    ]
    for fb in fallbacks:
        if fb.exists():
            resolved = str(fb.resolve())
            if resolved not in discovered:
                discovered.append(resolved)

    return discovered


_installed_modules_cache = {}


def ensure_sys_paths(force: bool = False) -> List[str]:
    """
    Ensure local addon site-packages directory (if bundled) is added to sys.path.
    Blender 4.2+ handles declared wheels automatically at the extension layer,
    so this function avoids unpacking archives or mutating external environments.
    Returns list of paths successfully added to sys.path.
    """
    added_paths = []
    addon_dir = Path(__file__).parent.parent.parent.resolve()

    # Mount addon's own site-packages if present (e.g. for local developer testing)
    ext_site_packages = addon_dir / "site-packages"
    if ext_site_packages.exists() and ext_site_packages.is_dir():
        resolved = str(ext_site_packages.resolve())
        if resolved not in sys.path:
            sys.path.insert(0, resolved)
            added_paths.append(resolved)

    if added_paths or force:
        importlib.invalidate_caches()
        _installed_modules_cache.clear()
        try:
            get_installed_version.cache_clear()
        except Exception:
            pass

    return added_paths


# Ensure bundled sys.paths are available upon module load
ensure_sys_paths()


@lru_cache(maxsize=1)
def get_python_executable() -> str:
    """
    Find the active Python binary executable used by the current Blender process.
    Handles embedded Python across macOS, Windows, and Linux.
    """
    exe = sys.executable

    # If sys.executable is already a python binary
    if "python" in os.path.basename(exe).lower():
        return exe

    # If sys.executable points to Blender binary, inspect sys.prefix
    if sys.platform == "win32":
        candidates = [
            os.path.join(sys.prefix, "bin", "python.exe"),
            os.path.join(sys.prefix, "python.exe"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
    else:
        candidates = [
            os.path.join(sys.prefix, "bin", f"python{sys.version_info.major}.{sys.version_info.minor}"),
            os.path.join(sys.prefix, "bin", "python3"),
            os.path.join(sys.prefix, "bin", "python"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c

    return exe


def is_module_installed(module_name: str) -> bool:
    """Check if a Python module is available in the Python environment (cached)."""
    if module_name in sys.modules:
        return True
    if module_name in _installed_modules_cache:
        return _installed_modules_cache[module_name]
    try:
        found = importlib.util.find_spec(module_name) is not None
    except Exception:
        found = False

    if not found:
        # Fallback: ensure bundled paths are mounted
        ensure_sys_paths()
        try:
            found = importlib.util.find_spec(module_name) is not None
        except Exception:
            found = False

    _installed_modules_cache[module_name] = found
    return found


@lru_cache(maxsize=32)
def get_installed_version(module_name: str, package_name: Optional[str] = None) -> Optional[str]:
    """Retrieve installed version of a package or module (cached)."""
    pkg_name = package_name or module_name
    try:
        return importlib.metadata.version(pkg_name)
    except Exception:
        pass

    # Fallback to importing module and inspecting __version__
    try:
        mod = importlib.import_module(module_name)
        return getattr(mod, "__version__", None)
    except Exception:
        return None


def get_dependency_status(dep: Dependency) -> dict:
    """Get the live installation status and version info for a Dependency."""
    installed = is_module_installed(dep.module_name)
    version = get_installed_version(dep.module_name, dep.name) if installed else None

    is_satisfied = installed
    # If a minimum version is specified, check compatibility
    if installed and version and dep.min_version:
        try:
            from packaging import version as pkg_version
            is_satisfied = pkg_version.parse(version) >= pkg_version.parse(dep.min_version)
        except Exception:
            is_satisfied = True

    return {
        "name": dep.name,
        "module_name": dep.module_name,
        "display_name": dep.display_name,
        "installed": installed,
        "version": version,
        "min_version": dep.min_version,
        "description": dep.description,
        "required_by": dep.required_by,
        "is_satisfied": is_satisfied,
    }


_cached_dep_statuses = None
_cached_dep_statuses_time = 0.0


def get_all_dependency_statuses(force_refresh: bool = False) -> List[dict]:
    """Get installation statuses for all registered dependencies (cached for 5 seconds to avoid UI redraw lag)."""
    global _cached_dep_statuses, _cached_dep_statuses_time
    now = time.time()
    if not force_refresh and _cached_dep_statuses is not None and (now - _cached_dep_statuses_time) < 5.0:
        return _cached_dep_statuses

    if force_refresh:
        _installed_modules_cache.clear()
        get_installed_version.cache_clear()

    _cached_dep_statuses = [get_dependency_status(dep) for dep in DEPENDENCIES.values()]
    _cached_dep_statuses_time = now
    return _cached_dep_statuses


def has_all_dependencies() -> bool:
    """Check if all registered dependencies are installed and satisfied."""
    return all(get_dependency_status(dep)["is_satisfied"] for dep in DEPENDENCIES.values())


def has_pillow() -> bool:
    """Convenience helper to check if Pillow (PIL) is available."""
    return is_module_installed("PIL")


def has_websockets() -> bool:
    """Convenience helper to check if websockets module is available."""
    return is_module_installed("websockets")


def draw_pillow_warning(
    layout,
    title: str = "Material replacement requires 'Pillow' (PIL) module (Missing)!",
    subtitle: str = "Please ensure Pillow or extension wheels are available.",
    tab: str = "MISC"
):
    """Draw a standardized alert box warning the user that Pillow is missing with a button to check environment."""
    alert_box = layout.box()
    alert_box.alert = True
    alert_box.label(text=title, icon='ERROR')
    if subtitle:
        alert_box.label(text=subtitle)
    op = alert_box.operator("mozi.open_preferences", text="Check Environment", icon='PREFERENCES')
    op.tab = tab


def draw_websockets_warning(
    layout,
    title: str = "Live Sync requires 'websockets' module (Missing)!",
    subtitle: str = "Please ensure websockets or extension wheels are available.",
    tab: str = "SYNC"
):
    """Draw a standardized alert box warning the user that websockets is missing with a button to check environment."""
    alert_box = layout.box()
    alert_box.alert = True
    alert_box.label(text=title, icon='ERROR')
    if subtitle:
        alert_box.label(text=subtitle)
    op = alert_box.operator("mozi.open_preferences", text="Check Environment", icon='PREFERENCES')
    op.tab = tab


def get_prefs(context=None):
    """
    Retrieve MoziToolKit AddonPreferences safely across legacy add-on
    and Blender 4.2+ extensions packaging environments.
    """
    import bpy

    if context is None:
        context = bpy.context

    if not hasattr(context, "preferences") or not context.preferences:
        return None

    addons = getattr(context.preferences, "addons", None)
    if addons is None:
        return None

    # 1. Search for any addon entry whose .preferences is an instance of MOZI_AddonPreferences
    pref_cls = getattr(bpy.types, "MOZI_AddonPreferences", None)
    for addon in addons.values():
        pref = getattr(addon, "preferences", None)
        if pref is not None:
            if pref_cls and isinstance(pref, pref_cls):
                return pref
            if hasattr(pref, "resource_packs") or hasattr(pref, "added_mesh"):
                return pref

    # 2. Check known addon idnames
    for name in ["bl_ext.vscode_development.MoziToolKit", "MoziToolKit"]:
        addon = addons.get(name)
        if addon and getattr(addon, "preferences", None) is not None:
            return addon.preferences

    # 3. If in test or headless environment, ensure registered in addons
    idname = getattr(pref_cls, "bl_idname", "MoziToolKit") if pref_cls else "MoziToolKit"
    try:
        if idname not in addons:
            addons.new(name=idname)
        addon = addons.get(idname)
        if addon and getattr(addon, "preferences", None) is not None:
            return addon.preferences
    except Exception:
        pass

    return None

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
}


def get_blender_site_packages() -> List[str]:
    """
    Discover site-packages directories belonging to Blender's Python environment
    and extension-isolated packages directories.
    """
    discovered = []

    # 1. Extension's own directory (wheels / site-packages if unpacked)
    addon_dir = Path(__file__).parent.parent.parent.resolve()
    ext_site_packages = [
        addon_dir / "site-packages",
        addon_dir / "wheels",
    ]
    for esp in ext_site_packages:
        if esp.exists():
            resolved = str(esp.resolve())
            if resolved not in discovered:
                discovered.append(resolved)

    # 2. Standard Blender Python site-packages
    try:
        site_dirs = site.getsitepackages()
        if isinstance(site_dirs, list):
            for sd in site_dirs:
                p = Path(sd)
                if p.exists():
                    resolved = str(p.resolve())
                    if resolved not in discovered:
                        discovered.append(resolved)
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


def ensure_sys_paths() -> List[str]:
    """
    Compatibility no-op retained for callers from pre-extension builds.

    Blender Extensions owns wheel installation and its import paths.  Adding the
    extension's ``wheels/`` directory to ``sys.path`` violates Blender's
    extension policy and does not make a wheel importable in any case.
    """
    return []


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
    """Check if a Python module is available in the Python environment."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def get_installed_version(module_name: str, package_name: Optional[str] = None) -> Optional[str]:
    """Retrieve installed version of a package or module."""
    # Try importlib.metadata first
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


def get_all_dependency_statuses() -> List[dict]:
    """Get installation statuses for all registered dependencies."""
    return [get_dependency_status(dep) for dep in DEPENDENCIES.values()]


def has_all_dependencies() -> bool:
    """Check if all registered dependencies are installed and satisfied."""
    return all(get_dependency_status(dep)["is_satisfied"] for dep in DEPENDENCIES.values())


def has_pillow() -> bool:
    """Convenience helper to check if Pillow (PIL) is available."""
    return is_module_installed("PIL")


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

    # 1. Try resolving via the top-level root package name
    root_pkg = __name__.split(".")[0]
    if root_pkg in addons:
        return addons[root_pkg].preferences

    # 2. Check if any addon key matches or ends with MoziToolKit (e.g. bl_ext.*.MoziToolKit)
    for name, addon in addons.items():
        if name == "MoziToolKit" or name.endswith(".MoziToolKit") or "MoziToolKit" in name or name.endswith(".mozitoolkit") or "mozitoolkit" in name:
            return addon.preferences

    return None

"""
Dependency Manager for MoziToolKit.
Handles dynamic site-packages path discovery, dependency verification,
pip package installation inside Blender Python environment, and mirror configuration.
"""

from dataclasses import dataclass
import importlib
import importlib.metadata
import importlib.util
import os
from pathlib import Path
import site
import subprocess
import sys
from typing import Dict, List, Optional
from urllib.parse import urlparse


@dataclass
class Dependency:
    """Definition of an external Python dependency required by MoziToolKit features."""
    name: str              # pip package name (e.g. "Pillow")
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

# Preconfigured PyPI Mirrors for fast and reliable downloads
PYPI_MIRRORS = {
    "OFFICIAL": {
        "label": "Official PyPI",
        "url": "https://pypi.org/simple",
    },
    "TSINGHUA": {
        "label": "Tsinghua Mirror",
        "url": "https://pypi.tuna.tsinghua.edu.cn/simple",
    },
    "ALIYUN": {
        "label": "Aliyun Mirror",
        "url": "https://mirrors.aliyun.com/pypi/simple/",
    },
    "TENCENT": {
        "label": "Tencent Mirror",
        "url": "https://mirrors.cloud.tencent.com/pypi/simple/",
    },
    "USTC": {
        "label": "USTC Mirror",
        "url": "https://pypi.mirrors.ustc.edu.cn/simple/",
    },
}


def get_blender_site_packages() -> List[str]:
    """
    Discover site-packages directories belonging exclusively to Blender's bundled Python environment.
    Strictly excludes external system or user-specific directories (~/.local, Library/Python, etc.).
    """
    discovered = []

    # 1. Standard Blender Python site-packages
    try:
        site_dirs = site.getsitepackages()
        if isinstance(site_dirs, list):
            for sd in site_dirs:
                p = Path(sd)
                if p.exists():
                    discovered.append(str(p.resolve()))
    except Exception:
        pass

    # 2. Blender sys.prefix / sys.exec_prefix lib fallback
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
    Ensure Blender's bundled Python site-packages directories are present in sys.path.
    Never injects external user or OS-level Python directories.
    """
    added_paths = []
    blender_sites = get_blender_site_packages()

    for p in blender_sites:
        if p not in sys.path:
            sys.path.append(p)
            added_paths.append(p)

    return added_paths


# Run dynamic path resolution on module load
ensure_sys_paths()


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
    """Check if a Python module is installed in Blender's Python environment."""
    ensure_sys_paths()
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def get_installed_version(module_name: str, package_name: Optional[str] = None) -> Optional[str]:
    """Retrieve installed version of a package or module."""
    ensure_sys_paths()

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


def install_package(
    package_name: str,
    mirror_key: str = "TSINGHUA",
    custom_url: Optional[str] = None,
    upgrade: bool = False,
    timeout: int = 180,
) -> tuple[bool, str]:
    """
    Install or update a Python package into Blender's Python environment via pip.
    Completely isolated to Blender bundled environment without --user flag.

    Args:
        package_name: Name of the pip package to install.
        mirror_key: Key in PYPI_MIRRORS or "CUSTOM".
        custom_url: Custom index URL if mirror_key is "CUSTOM".
        upgrade: Whether to pass --upgrade to pip.
        timeout: Maximum seconds to wait for installation process.

    Returns:
        (success: bool, output_log: str)
    """
    # Check Blender online access preference (Blender 4.2+ standard)
    try:
        import bpy
        if hasattr(bpy.app, "online_access") and not bpy.app.online_access:
            msg = (
                "[MoziToolKit Error] Online access is disabled in Blender preferences.\n"
                "Please enable 'Allow Online Access' in Blender Preferences > System > Network to install dependencies."
            )
            return False, msg
    except Exception:
        pass

    python_exe = get_python_executable()
    logs = []

    # Ensure pip is available inside Blender
    try:
        subprocess.run(
            [python_exe, "-m", "ensurepip", "--default-pip"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    except Exception as e:
        logs.append(f"[Note] ensurepip check: {e}")

    # Build pip install command targeting Blender's bundled environment (no --user)
    cmd = [python_exe, "-m", "pip", "install", package_name, "--no-user"]

    if upgrade:
        cmd.append("--upgrade")

    # Determine index URL
    index_url = None
    if mirror_key == "CUSTOM" and custom_url:
        index_url = custom_url.strip()
    elif mirror_key in PYPI_MIRRORS:
        index_url = PYPI_MIRRORS[mirror_key]["url"]

    if index_url:
        cmd.extend(["-i", index_url])
        parsed = urlparse(index_url)
        if parsed.hostname:
            cmd.extend(["--trusted-host", parsed.hostname])

    cmd_str = " ".join(cmd)
    logs.append(f"Executing: {cmd_str}\n" + "-" * 50)

    try:
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        logs.append(process.stdout)
        success = (process.returncode == 0)

        # Invalidate import caches and update sys.path
        importlib.invalidate_caches()
        ensure_sys_paths()

        if success:
            logs.append("\n[MoziToolKit] Package installation completed successfully.")
        else:
            logs.append(f"\n[MoziToolKit] Package installation failed with return code {process.returncode}.")

        return success, "\n".join(logs)

    except subprocess.TimeoutExpired:
        logs.append(f"\n[MoziToolKit Error] Installation timed out after {timeout} seconds.")
        return False, "\n".join(logs)
    except Exception as e:
        logs.append(f"\n[MoziToolKit Error] Exception during installation: {e}")
        return False, "\n".join(logs)


def uninstall_package(
    package_name: str,
    timeout: int = 120,
) -> tuple[bool, str]:
    """
    Uninstall a Python package from Blender's Python environment via pip.

    Args:
        package_name: Name of the pip package to uninstall.
        timeout: Maximum seconds to wait for uninstallation process.

    Returns:
        (success: bool, output_log: str)
    """
    python_exe = get_python_executable()
    logs = []

    cmd = [python_exe, "-m", "pip", "uninstall", "-y", package_name]
    cmd_str = " ".join(cmd)
    logs.append(f"Executing: {cmd_str}\n" + "-" * 50)

    try:
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        logs.append(process.stdout)
        success = (process.returncode == 0)

        # Invalidate module cache from sys.modules
        dep_def = DEPENDENCIES.get(package_name)
        mod_name = dep_def.module_name if dep_def else package_name
        for k in list(sys.modules.keys()):
            if k == mod_name or k.startswith(f"{mod_name}."):
                sys.modules.pop(k, None)

        importlib.invalidate_caches()

        if success:
            logs.append("\n[MoziToolKit] Package uninstalled successfully.")
        else:
            logs.append(f"\n[MoziToolKit] Package uninstallation failed with return code {process.returncode}.")

        return success, "\n".join(logs)

    except subprocess.TimeoutExpired:
        logs.append(f"\n[MoziToolKit Error] Uninstallation timed out after {timeout} seconds.")
        return False, "\n".join(logs)
    except Exception as e:
        logs.append(f"\n[MoziToolKit Error] Exception during uninstallation: {e}")
        return False, "\n".join(logs)


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
        if name == "MoziToolKit" or name.endswith(".MoziToolKit") or "MoziToolKit" in name:
            return addon.preferences

    return None


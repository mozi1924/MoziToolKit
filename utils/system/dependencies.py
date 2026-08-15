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


def ensure_sys_paths() -> List[str]:
    """
    Dynamically discover user site-packages and standard site directories
    and add them to sys.path if not already present.
    Eliminates hardcoded paths across macOS, Windows, and Linux.
    """
    added_paths = []
    candidates = []

    # 1. Standard site module discovery
    try:
        user_site = site.getusersitepackages()
        if user_site:
            candidates.append(Path(user_site))
    except Exception:
        pass

    if hasattr(site, "USER_SITE") and site.USER_SITE:
        candidates.append(Path(site.USER_SITE))

    try:
        site_dirs = site.getsitepackages()
        if isinstance(site_dirs, list):
            for sd in site_dirs:
                candidates.append(Path(sd))
    except Exception:
        pass

    # 2. Dynamic platform-specific user site fallbacks for Blender's Python
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    home = Path.home()

    if sys.platform == "darwin":
        candidates.extend([
            home / "Library" / "Python" / py_ver / "lib" / "python" / "site-packages",
            home / ".local" / "lib" / f"python{py_ver}" / "site-packages",
        ])
    elif sys.platform == "win32":
        app_data = os.environ.get("APPDATA")
        if app_data:
            candidates.append(Path(app_data) / "Python" / f"Python{sys.version_info.major}{sys.version_info.minor}" / "site-packages")
    else:  # Linux / Unix
        candidates.extend([
            home / ".local" / "lib" / f"python{py_ver}" / "site-packages",
        ])

    # Add valid paths to sys.path
    for p in candidates:
        try:
            resolved = str(p.resolve())
            if p.exists() and resolved not in sys.path:
                sys.path.append(resolved)
                added_paths.append(resolved)
        except Exception:
            continue

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
    """Check if a Python module is installed and can be imported."""
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
            # Fallback simple string / tuple comparison if packaging is not available
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

    # Ensure pip is available
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

    # Build pip install command
    cmd = [python_exe, "-m", "pip", "install", package_name]

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
        # Add trusted-host if not standard https
        parsed = urlparse(index_url)
        if parsed.hostname:
            cmd.extend(["--trusted-host", parsed.hostname])

    # Prefer --user to avoid write permission errors in system/app directories
    try:
        user_site = site.getusersitepackages()
        if user_site and not os.access(sys.prefix, os.W_OK):
            cmd.append("--user")
    except Exception:
        cmd.append("--user")

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

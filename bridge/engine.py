"""
MoziToolKit Native Rust Engine Bridge & Dependency Loader.

Single authoritative access point for the underlying libmtk Rust core (libmtk_py).
Unifies dynamic loading across both Development Mode (dev/loader.py direct .so)
and Release Mode (Blender 4.2+ native extension wheels).
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, Optional

logger = logging.getLogger("MoziToolKit.Bridge.Engine")

_libmtk: Optional[Any] = None


def _resolve_libmtk() -> Optional[Any]:
    """
    Dynamically resolves libmtk_py module with fallback to development bootstrap.
    Safe across development mode, release extension wheels, and headless unit tests.
    """
    global _libmtk

    # 0. Return cached reference if already resolved
    if _libmtk is not None:
        return _libmtk

    # 1. Check if already present in sys.modules
    if "libmtk_py" in sys.modules and sys.modules["libmtk_py"] is not None:
        _libmtk = sys.modules["libmtk_py"]
        return _libmtk

    # 2. Try standard import (works in release wheel, or if dev/lib already in sys.path)
    try:
        import libmtk_py
        _libmtk = libmtk_py
        return _libmtk
    except ImportError:
        pass

    # 3. Try development environment bootstrap (dev/loader.py) if in dev mode
    try:
        from ..dev import loader
        if loader.setup_dev_environment():
            import libmtk_py
            _libmtk = libmtk_py
            return _libmtk
    except (ImportError, ValueError, AttributeError):
        pass

    # 4. Fallback attempt for alternative module naming in build scripts
    try:
        import mtk_py
        _libmtk = mtk_py
        return _libmtk
    except ImportError:
        pass

    return None


def get_libmtk() -> Optional[Any]:
    """
    Returns the loaded libmtk_py native module, or None if unavailable.
    Attempts lazy resolution and dev environment mounting on demand.
    """
    return _resolve_libmtk()


def has_libmtk() -> bool:
    """Returns True if the native libmtk_py engine is loaded and accessible."""
    return get_libmtk() is not None


def require_libmtk(feature: str = "") -> Any:
    """
    Returns the native libmtk_py module, or raises a descriptive RuntimeError.
    Provides actionable guidance depending on dev vs release mode.
    """
    mtk = get_libmtk()
    if mtk is None:
        feat_msg = f" for '{feature}'" if feature else ""
        is_dev = False
        try:
            from ..dev import loader  # noqa: F401
            is_dev = True
        except (ImportError, ValueError):
            pass

        if is_dev:
            hint = (
                "Development Mode: Rust core binary (.so / .pyd) is missing or uncompiled.\n"
                "Run 'cargo build --release -p mtk-py --features extension-module' in libmozitoolkit,\n"
                "or check MoziToolKit/dev/lib/libmtk_py.so."
            )
        else:
            hint = (
                "Release Mode: The libmtk_py native extension wheel is missing or incompatible.\n"
                "Please verify platform compatibility or reinstall the release extension package."
            )

        raise RuntimeError(
            f"Native libmtk_py engine is not available{feat_msg}.\n{hint}"
        )
    return mtk


def get_engine_info() -> Dict[str, Any]:
    """
    Inspects runtime status, build origin, and capabilities of the native engine.
    Compatible with both development mode and release mode.
    """
    mtk = get_libmtk()
    info = {
        "available": mtk is not None,
        "mode": "Not Found",
        "path": "None",
        "version": "Unknown",
        "is_dev": False,
    }

    if mtk is not None:
        info["version"] = getattr(mtk, "version", lambda: "0.1.0")() if callable(getattr(mtk, "version", None)) else getattr(mtk, "version", "0.1.0")
        mod_file = getattr(mtk, "__file__", "") or ""
        info["path"] = mod_file

        if "dev/lib" in mod_file or "target/release" in mod_file:
            info["mode"] = "Dev Direct Shared Library (.so)"
            info["is_dev"] = True
        else:
            info["mode"] = "Release Extension Wheel"
            info["is_dev"] = False

    return info

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
_api_error: Optional[str] = None

# Integer ABI/API contract expected from libmtk_py. Bump together with
# `bindings/mtk-py/src/lib.rs::API_VERSION` whenever the Python surface changes
# incompatibly.
REQUIRED_API_VERSION = 1


def _validate_native_api(module: Any) -> bool:
    """Checks the integer native API contract and records an actionable error."""
    global _api_error
    version = getattr(module, "api_version", None)
    if version is None:
        _api_error = (
            "libmtk_py is missing api_version(); this is a pre-2.0 native build. "
            "Rebuild with 'cargo build --release -p mtk-py --features extension-module' "
            "or reinstall the matching libmtk_py wheel."
        )
        return False
    try:
        actual = int(version())
    except Exception as exc:
        _api_error = f"libmtk_py api_version() failed: {exc}"
        return False
    if actual != REQUIRED_API_VERSION:
        _api_error = (
            f"libmtk_py API version {actual} is incompatible with this addon "
            f"(required {REQUIRED_API_VERSION}). Reinstall the matching libmtk_py wheel "
            "or rebuild the native extension."
        )
        return False
    _api_error = None
    return True


def get_api_error() -> Optional[str]:
    """Returns the last native API validation error, if any."""
    return _api_error


def _accept_native(module: Any) -> Optional[Any]:
    """Caches a native module only when its integer API contract matches."""
    global _libmtk
    if _validate_native_api(module):
        _libmtk = module
        return module
    _libmtk = None
    return None


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
        return _accept_native(sys.modules["libmtk_py"])

    # 2. Try standard import (works in release wheel, or if dev/lib already in sys.path)
    try:
        import libmtk_py
        accepted = _accept_native(libmtk_py)
        if accepted is not None:
            return accepted
    except ImportError:
        pass

    # 3. Try development environment bootstrap (dev/loader.py) if in dev mode
    try:
        from ..dev import loader
        if loader.setup_dev_environment():
            import libmtk_py
            accepted = _accept_native(libmtk_py)
            if accepted is not None:
                return accepted
    except (ImportError, ValueError, AttributeError):
        pass

    # 4. Fallback attempt for alternative module naming in build scripts
    try:
        import mtk_py
        accepted = _accept_native(mtk_py)
        if accepted is not None:
            return accepted
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


def get_libmtk_blender() -> Optional[Any]:
    """
    Returns the loaded blender accelerator submodule from unified libmtk_py, or None if unavailable.
    Hardware accelerator for direct Blender memory/DNA manipulation.

    The legacy top-level ``libmtk_py.blender`` alias was removed in the 2026-10 API
    prune; ``libmtk_py.unstable.blender_dna`` is the only supported entry point.
    """
    mtk = get_libmtk()
    if mtk is None:
        return None
    unstable = getattr(mtk, "unstable", None)
    if unstable is None:
        return None
    return getattr(unstable, "blender_dna", None)


def has_libmtk_blender() -> bool:
    """Returns True if the embedded blender hardware accelerator submodule is active."""
    return get_libmtk_blender() is not None


def get_libmtk_dna() -> Optional[Any]:
    """Returns the loaded libmtk_py.unstable.blender_dna native DNA adapter submodule."""
    return get_libmtk_blender()


def has_libmtk_dna() -> bool:
    """Returns True if the embedded blender DNA hardware accelerator submodule is active."""
    return get_libmtk_dna() is not None


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
        if _api_error:
            hint = f"{_api_error}\n{hint}"

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
        "api_version": None,
        "is_dev": False,
    }

    if mtk is not None:
        info["version"] = getattr(mtk, "version", lambda: "0.1.0")() if callable(getattr(mtk, "version", None)) else getattr(mtk, "version", "0.1.0")
        api_fn = getattr(mtk, "api_version", None)
        info["api_version"] = api_fn() if callable(api_fn) else None
        mod_file = getattr(mtk, "__file__", "") or ""
        info["path"] = mod_file

        if "dev/lib" in mod_file or "target/release" in mod_file:
            info["mode"] = "Dev Direct Shared Library (.so)"
            info["is_dev"] = True
        else:
            info["mode"] = "Release Extension Wheel"
            info["is_dev"] = False

    return info

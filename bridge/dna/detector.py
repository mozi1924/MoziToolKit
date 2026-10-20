"""
Blender version detector and capability matrix for DNA direct memory access.

Determines whether the current Blender host environment supports low-level DNA pointer
ingestion, and manages user preferences and environment overrides.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional, Tuple

logger = logging.getLogger("MoziToolKit.Bridge.DNA.Detector")

# Global runtime override for DNA mode (None = use auto-detection)
_dna_enabled_override: Optional[bool] = None

# Supported Blender versions for DNA direct access (major, minor)
SUPPORTED_VERSIONS = {
    (4, 0),
    (4, 1),
    (4, 2),  # Blender 4.2 LTS (Primary target)
    (4, 3),
    (4, 4),
    (5, 0),  # Forward compatible
}


def get_blender_version() -> Tuple[int, int, int]:
    """
    Returns the current Blender version as a (major, minor, patch) tuple.
    Safe when running outside Blender or in headless mock environments.
    """
    if "bpy" in sys.modules:
        bpy = sys.modules["bpy"]
        app = getattr(bpy, "app", None)
        if app is not None:
            ver = getattr(app, "version", None)
            if isinstance(ver, tuple) and len(ver) >= 2:
                patch = ver[2] if len(ver) > 2 else 0
                return (int(ver[0]), int(ver[1]), int(patch))

    # Default fallback for testing outside of Blender host
    return (4, 2, 0)


def is_version_supported() -> bool:
    """
    Returns True if the current host Blender version is within the validated DNA compatibility matrix.
    Supports all Blender 4.x LTS releases and 5.x releases.
    """
    major, minor, _ = get_blender_version()
    return major in (4, 5)


def is_dna_available() -> bool:
    """
    Returns True if:
    1. The standalone `libmtk_blender_dna` raw-memory adapter is loaded;
    2. The current Blender version is supported;
    3. DNA mode is not disabled via environment variable or override.
    """
    # 0. Check environmental disable flag (e.g. MTK_DISABLE_DNA=1)
    if os.environ.get("MTK_DISABLE_DNA", "").strip() in ("1", "true", "TRUE"):
        return False

    # 1. Check user override
    if _dna_enabled_override is False:
        return False

    # 2. Check host version compatibility
    if not is_version_supported():
        return False

    # 3. Check native engine accelerator capability
    try:
        from ..engine import get_libmtk_blender
        return get_libmtk_blender() is not None
    except Exception:
        return False


def is_dna_enabled() -> bool:
    """
    Returns True if DNA direct mode is actively enabled for operations.
    """
    if _dna_enabled_override is not None:
        return _dna_enabled_override and is_dna_available()
    return is_dna_available()


def set_dna_enabled(enabled: Optional[bool]) -> None:
    """
    Overrides the DNA active status at runtime. Pass None to restore automatic detection.
    """
    global _dna_enabled_override
    _dna_enabled_override = enabled
    logger.debug("DNA direct memory mode override set to: %s", enabled)

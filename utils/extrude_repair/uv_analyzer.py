"""
UV area, pixel resolution, and collapse detection utilities for extrusion repair.
"""

from __future__ import annotations

from typing import Tuple, Optional

try:
    from ...bridge.extrude import get_face_pixel_step
except (ImportError, ValueError):
    from bridge.extrude import get_face_pixel_step


def get_active_texture_pixel_step(obj=None) -> float:
    """Legacy helper: Retrieve scalar UV step for active object's material."""
    return 1.0 / 64.0


__all__ = ["get_face_pixel_step", "get_active_texture_pixel_step"]

"""
Common utilities for MoziToolKit preferences, resource packs, and menu management.
"""

from __future__ import annotations

import bpy
from typing import Any, Optional

try:
    from ..utils.system import get_prefs
except (ImportError, ValueError):
    from utils.system import get_prefs


def _safe_get_prefs(self_or_context: Any = None) -> Optional[Any]:
    """Safely retrieves MoziToolKit addon preferences across operator/UI contexts."""
    if hasattr(self_or_context, "resource_packs"):
        return self_or_context
    if isinstance(self_or_context, bpy.types.Context):
        prefs = get_prefs(self_or_context)
        if prefs:
            return prefs
    if hasattr(self_or_context, "id_data") and hasattr(self_or_context.id_data, "resource_packs"):
        return self_or_context.id_data
    prefs = get_prefs(bpy.context)
    if prefs:
        return prefs

    try:
        for addon in bpy.context.preferences.addons.values():
            if hasattr(addon, "preferences") and hasattr(addon.preferences, "resource_packs"):
                return addon.preferences
    except Exception:
        pass
    return None


def refresh_ui_and_menus(context: Optional[bpy.types.Context] = None) -> None:
    """Forces redraw of all open Blender screens/areas."""
    if context is None:
        context = getattr(bpy, "context", None)
    if context and hasattr(context, "window_manager") and context.window_manager:
        try:
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    area.tag_redraw()
        except Exception:
            pass


__all__ = ["_safe_get_prefs", "refresh_ui_and_menus"]

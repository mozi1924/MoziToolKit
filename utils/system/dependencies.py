"""
System environment and preference utilities for MoziToolKit.
Dependency isolation and wheel management is delegated entirely to Blender 4.2+ Extensions.
"""

from typing import Optional


def has_libmtk() -> bool:
    """Check if LibMTK native Rust core (libmtk_py) is available."""
    try:
        import libmtk_py
        return True
    except ImportError:
        return False


def ensure_sys_paths(*args, **kwargs):
    """Deprecated no-op for backward compatibility. Dependencies are handled natively by Blender 4.2+."""
    return []


def get_prefs(context=None):
    """
    Retrieve MoziToolKit AddonPreferences safely across legacy add-on
    and Blender 4.2+ extensions packaging environments.
    """
    try:
        import bpy
    except ImportError:
        return None

    if context is None:
        context = getattr(bpy, "context", None)

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

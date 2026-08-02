"""
MoziToolKit Context Menu Configuration & Registry Manager

This module manages user-configurable right-click context menus for MoziToolKit.

--- Developer Guide: How to add a new Operator to Right-Click Menus ---

Option 1: Use the `@register_menu_item` decorator on your Operator class:
    from ...utils.menu_config import register_menu_item

    @register_menu_item(views=["mesh", "object"], enabled=True)
    class MOZI_OT_my_new_tool(bpy.types.Operator):
        bl_idname = "mozi.my_new_tool"
        bl_label = "My New Tool"
        ...

Option 2: Register it manually in the Menu Manager:
    from ...utils.menu_config import register_operator_menu_item

    register_operator_menu_item(
        op_id="mozi.my_new_tool",
        label="My New Tool",
        views=["mesh", "uv"],
        enabled=True
    )
------------------------------------------------------------------------
"""

import json
import os
from pathlib import Path
import bpy

# Central Registry Dictionary for Registered Menu Items
# Format: { op_id: {"label": str, "default_label": str, "views": list[str], "enabled": bool} }
_REGISTERED_MENU_ITEMS = {}


def normalize_operator_id(op_id: str) -> str:
    """
    Normalize legacy or category-prefixed operator IDs (e.g. 'object.mozi_adaptive_pixel_split')
    to canonical registered operator bl_idnames (e.g. 'mozi.adaptive_pixel_split').
    """
    if not op_id:
        return op_id
    if op_id in _REGISTERED_MENU_ITEMS:
        info = _REGISTERED_MENU_ITEMS[op_id]
        return info.get("canonical_id", op_id)
    if "." in op_id:
        prefix, name = op_id.split(".", 1)
        if name.startswith("mozi_"):
            canonical = f"mozi.{name[5:]}"
            if canonical in _REGISTERED_MENU_ITEMS:
                return canonical
    return op_id


def register_operator_menu_item(op_id: str, label: str, views: list = None, enabled: bool = True):
    """
    Register an operator's menu metadata into the central Menu Manager.
    
    :param op_id: Operator bl_idname (e.g. 'mozi.select_hard_edges') or legacy id.
    :param label: Display label in context menus and preferences.
    :param views: List of view tabs where this item appears by default (e.g. ['mesh', 'object', 'uv']).
    :param enabled: Default enabled state in presets.
    """
    if views is None:
        views = ["mesh"]
    
    item_info = {
        "canonical_id": op_id,
        "label": label,
        "default_label": label,
        "views": list(views),
        "enabled": enabled,
        "is_legacy": False,
    }
    _REGISTERED_MENU_ITEMS[op_id] = item_info

    # Support legacy category-prefixed IDs (e.g. 'mesh.mozi_select_hard_edges') for backward compatibility with existing JSON configs
    if op_id.startswith("mozi."):
        suffix = op_id[len("mozi."):]
        for v in views:
            legacy_id = f"{v}.mozi_{suffix}"
            if legacy_id not in _REGISTERED_MENU_ITEMS:
                _REGISTERED_MENU_ITEMS[legacy_id] = {
                    **item_info,
                    "is_legacy": True,
                }


def register_menu_item(views: list = None, label: str = None, enabled: bool = True):
    """
    Decorator to register a Blender Operator class into the MoziToolKit Context Menu Manager.

    Usage:
        @register_menu_item(views=["mesh", "object"], enabled=True)
        class MOZI_OT_my_operator(bpy.types.Operator):
            bl_idname = "mozi.my_operator"
            bl_label = "My Operator"
    """
    if views is None:
        views = ["mesh"]

    def decorator(cls):
        op_id = getattr(cls, "bl_idname", "")
        op_label = label or getattr(cls, "bl_label", op_id)
        if op_id:
            register_operator_menu_item(op_id, op_label, views=views, enabled=enabled)
        
        # Store metadata on class for introspection
        cls._mozi_menu_views = views
        cls._mozi_menu_label = op_label
        cls._mozi_menu_enabled = enabled
        return cls

    return decorator


def get_all_operators(include_legacy: bool = False) -> dict:
    """Return dictionary of available operators registered for context menus."""
    if include_legacy:
        return _REGISTERED_MENU_ITEMS
    return {k: v for k, v in _REGISTERED_MENU_ITEMS.items() if not v.get("is_legacy", False)}


def get_default_presets() -> dict:
    """Dynamically build default presets dict categorized by view tab ('mesh', 'object', 'uv')."""
    presets = {"mesh": [], "object": [], "uv": []}

    for op_id, info in _REGISTERED_MENU_ITEMS.items():
        if info.get("is_legacy", False):
            continue
        for view in info.get("views", []):
            if view in presets:
                presets[view].append({
                    "operator": op_id,
                    "label": info.get("label", ""),
                    "enabled": info.get("enabled", True),
                })

    return presets


# Module-level accessors for backward compatibility
class _AllOperatorsDict(dict):
    """Fallback dict wrapper that dynamically delegates to get_all_operators()."""
    def __getitem__(self, key):
        return _REGISTERED_MENU_ITEMS[key]
    def get(self, key, default=None):
        return _REGISTERED_MENU_ITEMS.get(key, default)
    def items(self):
        return get_all_operators().items()
    def keys(self):
        return get_all_operators().keys()
    def values(self):
        return get_all_operators().values()
    def __contains__(self, key):
        return key in _REGISTERED_MENU_ITEMS
    def __len__(self):
        return len(get_all_operators())

ALL_OPERATORS = _AllOperatorsDict()


class _DefaultPresetsDict(dict):
    """Fallback dict wrapper that dynamically delegates to get_default_presets()."""
    def __getitem__(self, key):
        return get_default_presets()[key]
    def get(self, key, default=None):
        return get_default_presets().get(key, default)
    def items(self):
        return get_default_presets().items()
    def keys(self):
        return get_default_presets().keys()
    def values(self):
        return get_default_presets().values()
    def __contains__(self, key):
        return key in get_default_presets()

DEFAULT_PRESETS = _DefaultPresetsDict()


def get_config_path() -> Path:
    """Return absolute path to user data config JSON file."""
    try:
        config_dir = Path(bpy.utils.user_resource("CONFIG")) / "MoziToolKit"
    except Exception:
        config_dir = Path.home() / ".config" / "blender" / "MoziToolKit"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "context_menus.json"


def _normalize_views_data(views_data: dict) -> dict:
    """Helper to convert legacy operator IDs in views data to canonical IDs."""
    if not isinstance(views_data, dict):
        return views_data
    normalized = {}
    for view, items in views_data.items():
        if isinstance(items, list):
            norm_items = []
            for item in items:
                if isinstance(item, dict):
                    norm_item = dict(item)
                    if "operator" in norm_item:
                        norm_item["operator"] = normalize_operator_id(norm_item["operator"])
                    norm_items.append(norm_item)
            normalized[view] = norm_items
        else:
            normalized[view] = items
    return normalized


def load_config() -> dict:
    """Load configuration from JSON file or initialize with DEFAULT_PRESETS."""
    filepath = get_config_path()
    defaults = get_default_presets()
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                views = data.get("views", data) if isinstance(data, dict) else None
                if isinstance(views, dict):
                    return _normalize_views_data(views)
        except Exception as e:
            print(f"[MoziToolKit] Error reading config file {filepath}: {e}")

    # Fallback to default presets and save
    save_config(defaults)
    return defaults


def save_config(views_data: dict) -> bool:
    """Save configuration to user JSON file."""
    filepath = get_config_path()
    try:
        normalized = _normalize_views_data(views_data)
        data = {"version": 1, "views": normalized}
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[MoziToolKit] Error saving config file {filepath}: {e}")
        return False


def reset_config() -> dict:
    """Reset configuration to default presets and save."""
    defaults = get_default_presets()
    save_config(defaults)
    return defaults


def export_config(filepath: str, views_data: dict) -> bool:
    """Export configuration to specified filepath."""
    try:
        normalized = _normalize_views_data(views_data)
        data = {"version": 1, "views": normalized}
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[MoziToolKit] Error exporting config to {filepath}: {e}")
        return False


def import_config(filepath: str) -> dict:
    """Import configuration from specified filepath."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            views = data.get("views", data) if isinstance(data, dict) else None
            if isinstance(views, dict):
                normalized = _normalize_views_data(views)
                save_config(normalized)
                return normalized
    except Exception as e:
        print(f"[MoziToolKit] Error importing config from {filepath}: {e}")
    return None


def draw_dynamic_menu(layout, view_name: str):
    """
    Unified drawer helper function to render configured right-click menu items.
    
    :param layout: bpy.types.UILayout instance from menu's draw(self, context) method.
    :param view_name: View identifier ('mesh', 'object', or 'uv').
    """
    config = load_config()
    items = config.get(view_name, [])
    if not items:
        return
        
    valid_items = []
    for item in items:
        if item.get("enabled", True):
            op_id = normalize_operator_id(item.get("operator"))
            if op_id:
                valid_items.append((op_id, item.get("label")))
                
    if not valid_items:
        return

    layout.separator()
    layout.label(text="MoziToolKit")
    for op_id, label in valid_items:
        if label:
            layout.operator(op_id, text=label)
        else:
            layout.operator(op_id)



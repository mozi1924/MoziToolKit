"""
MoziToolKit Context Menu Registration and Dynamic Menu Renderer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, List, Optional

try:
    import bpy
except ImportError:
    bpy = None

from ..config.models import normalize_operator_id, is_valid_operator_id
from ..config import load_config

# Central Registry Dictionary for Registered Menu Items
_REGISTERED_MENU_ITEMS: Dict[str, Dict[str, Any]] = {}


def register_operator_menu_item(op_id: str, label: str, views: Optional[List[str]] = None, enabled: bool = True):
    """Register an operator's menu metadata into the central Menu Registry."""
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

    # Support legacy category-prefixed IDs for backward compatibility
    if op_id.startswith("mozi."):
        suffix = op_id[len("mozi."):]
        for v in views:
            legacy_id = f"{v}.mozi_{suffix}"
            if legacy_id not in _REGISTERED_MENU_ITEMS:
                _REGISTERED_MENU_ITEMS[legacy_id] = {
                    **item_info,
                    "is_legacy": True,
                }


def register_menu_item(views: Optional[List[str]] = None, label: Optional[str] = None, enabled: bool = True):
    """Decorator to register a Blender Operator class into the MoziToolKit Context Menu Registry."""
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


def get_all_operators(include_legacy: bool = False) -> Dict[str, Any]:
    """Return dictionary of available operators registered for context menus."""
    if include_legacy:
        return _REGISTERED_MENU_ITEMS
    return {k: v for k, v in _REGISTERED_MENU_ITEMS.items() if not v.get("is_legacy", False)}


def get_default_presets() -> Dict[str, List[Dict[str, Any]]]:
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


class _AllOperatorsDict(Mapping):
    """Read-only mapping proxy dynamically delegating to get_all_operators()."""

    def __getitem__(self, key):
        return _REGISTERED_MENU_ITEMS[key]

    def __iter__(self):
        return iter(get_all_operators())

    def __len__(self):
        return len(get_all_operators())


ALL_OPERATORS = _AllOperatorsDict()


class _DefaultPresetsDict(Mapping):
    """Read-only mapping proxy dynamically delegating to get_default_presets()."""

    def __getitem__(self, key):
        return get_default_presets()[key]

    def __iter__(self):
        return iter(get_default_presets())

    def __len__(self):
        return len(get_default_presets())


DEFAULT_PRESETS = _DefaultPresetsDict()


def sort_unadded_items(unadded_coll):
    """Sort unadded CollectionProperty items by live OPERATOR_ORDER."""
    if unadded_coll is None:
        return
    op_order = list(ALL_OPERATORS.keys())
    items = [
        {"operator_id": getattr(elem, "operator_id", ""), "label": getattr(elem, "label", "")}
        for elem in unadded_coll
    ]
    items.sort(
        key=lambda x: op_order.index(x["operator_id"])
        if x["operator_id"] in op_order
        else 999
    )
    unadded_coll.clear()
    for item in items:
        elem = unadded_coll.add()
        elem.operator_id = item["operator_id"]
        elem.label = item["label"]


def draw_dynamic_menu(layout, view_name: str):
    """Unified drawer helper function to render configured right-click menu items."""
    config = load_config()
    items = config.get(view_name, [])
    if not items:
        return

    valid_items = []
    for item in items:
        if isinstance(item, dict) and item.get("enabled", True):
            op_id = normalize_operator_id(item.get("operator", ""))
            if op_id and is_valid_operator_id(op_id):
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

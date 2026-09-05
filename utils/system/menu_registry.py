"""
MoziToolKit Context Menu Registration and Dynamic Menu Renderer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, List, Optional



from ..config.models import normalize_operator_id, is_valid_operator_id
from ..config import load_config

CANONICAL_DEFAULT_PRESETS: Dict[str, List[Dict[str, Any]]] = {
    "mesh": [
        {"operator": "mozi.adaptive_pixel_split", "label": "Adaptive Pixel Split", "enabled": True},
        {"operator": "mozi.select_hard_edges", "label": "Select Hard & Sharp Edges", "enabled": True},
        {"operator": "mozi.select_transparent_faces", "label": "Select Transparent Faces", "enabled": True},
        {"operator": "mozi.repair_fluid_uv", "label": "Repair Fluid UV", "enabled": True},
        {"operator": "mozi.random_extrude", "label": "Random Extrude", "enabled": True},
        {"operator": "mozi.auto_extrude_repair", "label": "Auto Extrude Repair", "enabled": True},
        {"operator": "mozi.clear_custom_normals", "label": "Clear Custom Normals", "enabled": True},
    ],
    "object": [
        {"operator": "mozi.replace_material", "label": "Replace Material", "enabled": True},
        {"operator": "mozi.adaptive_pixel_split", "label": "Adaptive Pixel Split", "enabled": True},
        {"operator": "mozi.set_texture_interpolation_closest", "label": "Set Image Interpolation to Closest", "enabled": True},
        {"operator": "mozi.clear_custom_normals", "label": "Clear Custom Normals", "enabled": True},
    ],
    "uv": [
        {"operator": "mozi.adaptive_pixel_split", "label": "Adaptive Pixel Split", "enabled": True},
        {"operator": "mozi.scale_uv", "label": "Scale UV Faces", "enabled": True},
        {"operator": "mozi.select_transparent_faces", "label": "Select Transparent Faces", "enabled": True},
        {"operator": "mozi.repair_fluid_uv", "label": "Repair Fluid UV", "enabled": True},
    ],
}

CANONICAL_OPERATORS: Dict[str, Dict[str, Any]] = {
    "mozi.adaptive_pixel_split": {
        "canonical_id": "mozi.adaptive_pixel_split",
        "label": "Adaptive Pixel Split",
        "default_label": "Adaptive Pixel Split",
        "views": ["mesh", "object", "uv"],
        "enabled": True,
        "is_legacy": False,
    },
    "mozi.auto_extrude_repair": {
        "canonical_id": "mozi.auto_extrude_repair",
        "label": "Auto Extrude Repair",
        "default_label": "Auto Extrude Repair",
        "views": ["mesh"],
        "enabled": True,
        "is_legacy": False,
    },
    "mozi.clear_custom_normals": {
        "canonical_id": "mozi.clear_custom_normals",
        "label": "Clear Custom Normals",
        "default_label": "Clear Custom Normals",
        "views": ["mesh", "object"],
        "enabled": True,
        "is_legacy": False,
    },
    "mozi.random_extrude": {
        "canonical_id": "mozi.random_extrude",
        "label": "Random Extrude",
        "default_label": "Random Extrude",
        "views": ["mesh"],
        "enabled": True,
        "is_legacy": False,
    },
    "mozi.select_hard_edges": {
        "canonical_id": "mozi.select_hard_edges",
        "label": "Select Hard & Sharp Edges",
        "default_label": "Select Hard & Sharp Edges",
        "views": ["mesh"],
        "enabled": True,
        "is_legacy": False,
    },
    "mozi.replace_material": {
        "canonical_id": "mozi.replace_material",
        "label": "Replace Material",
        "default_label": "Replace Material",
        "views": ["object"],
        "enabled": True,
        "is_legacy": False,
    },
    "mozi.set_texture_interpolation_closest": {
        "canonical_id": "mozi.set_texture_interpolation_closest",
        "label": "Set Image Interpolation to Closest",
        "default_label": "Set Image Interpolation to Closest",
        "views": ["object"],
        "enabled": True,
        "is_legacy": False,
    },
    "mozi.repair_fluid_uv": {
        "canonical_id": "mozi.repair_fluid_uv",
        "label": "Repair Fluid UV",
        "default_label": "Repair Fluid UV",
        "views": ["uv", "mesh"],
        "enabled": True,
        "is_legacy": False,
    },
    "mozi.scale_uv": {
        "canonical_id": "mozi.scale_uv",
        "label": "Scale UV Faces",
        "default_label": "Scale UV Faces",
        "views": ["uv"],
        "enabled": True,
        "is_legacy": False,
    },
    "mozi.select_transparent_faces": {
        "canonical_id": "mozi.select_transparent_faces",
        "label": "Select Transparent Faces",
        "default_label": "Select Transparent Faces",
        "views": ["mesh", "uv"],
        "enabled": True,
        "is_legacy": False,
    },
}

# Central Registry Dictionary for Registered Menu Items initialized with Canonical Operators
_REGISTERED_MENU_ITEMS: Dict[str, Dict[str, Any]] = {k: dict(v) for k, v in CANONICAL_OPERATORS.items()}


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

    for view in ["mesh", "object", "uv"]:
        if not presets[view]:
            presets[view] = [dict(it) for it in CANONICAL_DEFAULT_PRESETS.get(view, [])]

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
    from ...i18n import tr
    layout.label(text=tr("MoziToolKit"))
    for op_id, label in valid_items:
        if label:
            # First check if the user-specified or default label has a translation in Operator or general context
            trans_label = tr(label, "Operator")
            if trans_label == label:
                trans_label = tr(label)
            layout.operator(op_id, text=trans_label)
        else:
            layout.operator(op_id)

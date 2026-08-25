"""
MoziToolKit Context Menu Configuration & Registry Manager (Facade).
Delegates configuration persistence to utils.config and menu registration to utils.system.menu_registry.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from ..config import (
    ConfigManager,
    get_config_manager,
    get_config_path,
    load_config,
    load_full_config,
    save_config,
    save_full_config,
    load_pack_stack_config,
    save_pack_stack_config,
    get_enabled_pack_entries,
    load_material_settings_config,
    save_material_settings_config,
    reset_config,
    reset_views_config,
    export_config,
    import_config,
    normalize_operator_id,
    is_valid_operator_id,
)
from .menu_registry import (
    register_operator_menu_item,
    register_menu_item,
    get_all_operators,
    get_default_presets,
    ALL_OPERATORS,
    DEFAULT_PRESETS,
    draw_dynamic_menu,
    sort_unadded_items,
)


def _normalize_views_data(views_data: dict) -> dict:
    """Helper to convert legacy operator IDs in views data to canonical IDs and filter invalid ones."""
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
                        canonical_op = normalize_operator_id(norm_item["operator"])
                        if is_valid_operator_id(canonical_op):
                            norm_item["operator"] = canonical_op
                            norm_items.append(norm_item)
                        else:
                            print(f"[MoziToolKit] Ignoring untrusted/unregistered menu operator: {norm_item.get('operator')}")
                    else:
                        norm_items.append(norm_item)
            normalized[view] = norm_items
        else:
            normalized[view] = items
    return normalized


def normalize_pack_entries_order(entries: list[dict]) -> list[dict]:
    """Sort pack entries into strict tiers: RESOURCE_PACK (0), MOD_JAR (1), VANILLA (2)."""
    if not entries:
        return []

    def tier_key(item):
        pt = item.get("pack_type", "RESOURCE_PACK") if isinstance(item, dict) else "RESOURCE_PACK"
        if pt == "RESOURCE_PACK":
            return 0
        elif pt == "MOD_JAR":
            return 1
        else:
            return 2

    return sorted(entries, key=tier_key)


__all__ = [
    "normalize_operator_id",
    "is_valid_operator_id",
    "_normalize_views_data",
    "normalize_pack_entries_order",
    "register_operator_menu_item",
    "register_menu_item",
    "get_all_operators",
    "get_default_presets",
    "ALL_OPERATORS",
    "DEFAULT_PRESETS",
    "draw_dynamic_menu",
    "sort_unadded_items",
    "get_config_path",
    "load_config",
    "load_full_config",
    "save_config",
    "save_full_config",
    "load_pack_stack_config",
    "save_pack_stack_config",
    "get_enabled_pack_entries",
    "load_material_settings_config",
    "save_material_settings_config",
    "reset_config",
    "reset_views_config",
    "export_config",
    "import_config",
    "get_config_manager",
]

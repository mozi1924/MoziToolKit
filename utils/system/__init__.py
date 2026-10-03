"""
System environment, preference utilities, and UI context menu registry subpackage.
"""

from .dependencies import (
    ensure_sys_paths,
    has_libmtk,
    get_prefs,
)

from .menu_config import (
    register_menu_item,
    register_operator_menu_item,
    normalize_operator_id,
    get_all_operators,
    get_default_presets,
    ALL_OPERATORS,
    DEFAULT_PRESETS,
    get_config_path,
    load_config,
    load_full_config,
    save_config,
    save_full_config,
    load_pack_stack_config,
    save_pack_stack_config,
    load_material_settings_config,
    save_material_settings_config,
    get_enabled_pack_entries,
    export_config,
    import_config,
    draw_dynamic_menu,
    sort_unadded_items,
)


__all__ = [
    "ensure_sys_paths",
    "has_libmtk",
    "get_prefs",
    "register_menu_item",
    "register_operator_menu_item",
    "normalize_operator_id",
    "get_all_operators",
    "get_default_presets",
    "ALL_OPERATORS",
    "DEFAULT_PRESETS",
    "get_config_path",
    "load_config",
    "load_full_config",
    "save_config",
    "save_full_config",
    "load_pack_stack_config",
    "save_pack_stack_config",
    "load_material_settings_config",
    "save_material_settings_config",
    "get_enabled_pack_entries",
    "reset_config",
    "export_config",
    "import_config",
    "draw_dynamic_menu",
    "sort_unadded_items",
]

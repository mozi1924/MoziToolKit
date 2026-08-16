"""
System environment, dependency management, and UI context menu registry subpackage.
"""

from .dependencies import (
    Dependency,
    DEPENDENCIES,
    ensure_sys_paths,
    get_blender_site_packages,
    get_python_executable,
    is_module_installed,
    get_installed_version,
    get_dependency_status,
    get_all_dependency_statuses,
    has_all_dependencies,
    has_pillow,
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
    save_config,
    reset_config,
    export_config,
    import_config,
    draw_dynamic_menu,
)

__all__ = [
    "Dependency",
    "DEPENDENCIES",
    "ensure_sys_paths",
    "get_blender_site_packages",
    "get_python_executable",
    "is_module_installed",
    "get_installed_version",
    "get_dependency_status",
    "get_all_dependency_statuses",
    "has_all_dependencies",
    "has_pillow",
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
    "save_config",
    "reset_config",
    "export_config",
    "import_config",
    "draw_dynamic_menu",
]

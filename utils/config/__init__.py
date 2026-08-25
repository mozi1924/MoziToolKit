"""
MoziToolKit Unified Configuration Management Subpackage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .backends import (
    ConfigBackend,
    JsonConfigBackend,
    BlenderPreferencesConfigBackend,
    MemoryConfigBackend,
)
from .models import (
    ConfigData,
    PackEntry,
    MaterialSettings,
    MenuItem,
    normalize_operator_id,
    is_valid_operator_id,
)
from .manager import ConfigManager


def get_config_manager() -> ConfigManager:
    """Return the central singleton ConfigManager instance."""
    return ConfigManager.get_instance()


def get_config_path() -> Path:
    """Return absolute path to current JSON configuration file."""
    mgr = get_config_manager()
    backend = mgr.get_backend()
    if isinstance(backend, JsonConfigBackend):
        return backend.get_config_path()
    return JsonConfigBackend().get_config_path()


def load_config() -> Dict[str, List[Dict[str, Any]]]:
    """Load and return context menu views configuration dict."""
    return get_config_manager().get_views()


def load_full_config() -> Dict[str, Any]:
    """Load and return full root configuration dictionary."""
    return get_config_manager().get_data().to_dict()


def save_config(views_data: Dict[str, Any]) -> bool:
    """Save context menu views configuration."""
    return get_config_manager().set_views(views_data, save=True)


def save_full_config(
    views_data: Optional[Dict[str, Any]] = None,
    pack_entries: Optional[List[Any]] = None,
    material_settings: Optional[Dict[str, Any]] = None,
) -> bool:
    """Atomically update and persist configuration sections."""
    return get_config_manager().save_full_config(
        views_data=views_data,
        pack_entries=pack_entries,
        material_settings=material_settings,
    )


def load_pack_stack_config() -> List[Dict[str, Any]]:
    """Load prioritized Resource Pack and Base JAR stack list."""
    return get_config_manager().get_resource_packs()


def save_pack_stack_config(pack_entries: List[Union[Dict[str, Any], PackEntry]]) -> bool:
    """Save Resource Pack and Base JAR stack list with 3-tier normalization."""
    return get_config_manager().set_resource_packs(pack_entries, save=True)


def get_enabled_pack_entries() -> List[Dict[str, Any]]:
    """Return all active/enabled resource pack and JAR entries."""
    return get_config_manager().get_enabled_pack_entries()


def load_material_settings_config() -> Dict[str, Any]:
    """Load material replacement options dict."""
    return get_config_manager().get_material_settings()


def save_material_settings_config(material_settings: Union[Dict[str, Any], MaterialSettings]) -> bool:
    """Save material replacement options dict."""
    return get_config_manager().set_material_settings(material_settings, save=True)


def reset_config() -> Dict[str, Any]:
    """Reset configuration to defaults and save."""
    return get_config_manager().reset().to_dict()


def export_config(filepath: Union[str, Path], views_data: Optional[Dict[str, Any]] = None) -> bool:
    """Export configuration to specified filepath."""
    if views_data is not None:
        get_config_manager().set_views(views_data, save=False)
    return get_config_manager().export_config(filepath)


def import_config(filepath: Union[str, Path]) -> Optional[Dict[str, Any]]:
    """Import configuration from specified filepath."""
    return get_config_manager().import_config(filepath)


__all__ = [
    "ConfigManager",
    "get_config_manager",
    "get_config_path",
    "ConfigBackend",
    "JsonConfigBackend",
    "BlenderPreferencesConfigBackend",
    "MemoryConfigBackend",
    "ConfigData",
    "PackEntry",
    "MaterialSettings",
    "MenuItem",
    "normalize_operator_id",
    "is_valid_operator_id",
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
    "export_config",
    "import_config",
]

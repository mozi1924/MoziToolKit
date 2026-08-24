"""
MoziToolKit Context Menu Configuration & Registry Manager.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional, Union

try:
    import bpy
except ImportError:
    bpy = None

# Central Registry Dictionary for Registered Menu Items
_REGISTERED_MENU_ITEMS = {}
_CONFIG_WRITE_LOCK = threading.RLock()


def normalize_operator_id(op_id: str) -> str:
    """
    Normalize legacy or category-prefixed operator IDs (e.g. 'object.mozi_adaptive_pixel_split')
    to canonical registered operator bl_idnames (e.g. 'mozi.adaptive_pixel_split').
    """
    if not op_id:
        return op_id
    if op_id.startswith("mozi."):
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
            return canonical
    return op_id


def register_operator_menu_item(op_id: str, label: str, views: list = None, enabled: bool = True):
    """
    Register an operator's menu metadata into the central Menu Manager.
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


def register_menu_item(views: list = None, label: str = None, enabled: bool = True):
    """
    Decorator to register a Blender Operator class into the MoziToolKit Context Menu Manager.
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


from collections.abc import Mapping


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


def get_config_path() -> Path:
    """Return absolute path to user data config JSON file."""
    try:
        config_dir = Path(bpy.utils.user_resource("CONFIG")) / "MoziToolKit"
    except Exception:
        config_dir = Path.home() / ".config" / "blender" / "MoziToolKit"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "context_menus.json"


def _atomic_write_json(filepath: Path, data: dict) -> None:
    """Durably replace a JSON file without ever exposing a partial document."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{filepath.stem}.", suffix=".tmp", dir=filepath.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=4, ensure_ascii=False)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_name, filepath)
        # Persist the rename itself where the platform supports directory fsync.
        try:
            dir_fd = os.open(filepath.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _load_json_object(filepath: Path) -> Optional[dict]:
    """Return a valid persisted configuration object, otherwise ``None``."""
    try:
        with open(filepath, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        # Every config written by MoziToolKit has these roots.  Rejecting an
        # interrupted/empty document keeps a later settings save from silently
        # replacing the user's stack with defaults.
        if isinstance(data, dict) and isinstance(data.get("views"), dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


def is_valid_operator_id(op_id: str) -> bool:
    """Validate that an operator ID is registered or belongs to MoziToolKit namespace."""
    if not op_id or not isinstance(op_id, str):
        return False
    if op_id in _REGISTERED_MENU_ITEMS:
        return True
    if op_id.startswith("mozi.") or op_id.startswith("mozi_"):
        return True
    return False


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

    save_config(defaults)
    return defaults


def load_full_config() -> dict:
    """Load full configuration root JSON object."""
    filepath = get_config_path()
    data = _load_json_object(filepath) if filepath.exists() else None
    if data is not None:
        return data

    # A one-generation backup makes a malformed or manually interrupted main
    # write recoverable instead of treating it as an empty configuration.
    backup_path = filepath.with_suffix(filepath.suffix + ".bak")
    backup = _load_json_object(backup_path) if backup_path.exists() else None
    if backup is not None:
        print(f"[MoziToolKit] Recovered configuration from backup: {backup_path}")
        return backup

    if filepath.exists():
        print(f"[MoziToolKit] Configuration is invalid; preserving it and using defaults: {filepath}")
    return {
        "version": 1,
        "views": get_default_presets(),
        "resource_packs": [],
        "material_settings": {
            "material_mode": "ATLAS",
            "biome_preset": "PLAINS",
            "pack_textures": True,
        }
    }


def normalize_pack_entries_order(entries: list[dict]) -> list[dict]:
    """Sort pack entries into strict tiers: RESOURCE_PACK (0), MOD_JAR (1), VANILLA (2), preserving relative order within tiers."""
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


def save_full_config(
    views_data: Optional[dict] = None,
    pack_entries: Optional[list[dict]] = None,
    material_settings: Optional[dict] = None,
) -> bool:
    """Atomically update and save configuration views, resource pack stack, and material settings to user JSON file."""
    filepath = get_config_path()
    try:
        # UI callbacks can arrive close together.  Keep read-modify-write
        # atomic within this Blender process so a material-settings update
        # cannot overwrite a just-saved resource-pack stack.
        with _CONFIG_WRITE_LOCK:
            full_data = load_full_config()
            full_data["version"] = 1
            if views_data is not None:
                full_data["views"] = _normalize_views_data(views_data)
            if pack_entries is not None:
                full_data["resource_packs"] = normalize_pack_entries_order(list(pack_entries))
            if material_settings is not None:
                full_data["material_settings"] = dict(material_settings)
            _atomic_write_json(filepath, full_data)
            _atomic_write_json(filepath.with_suffix(filepath.suffix + ".bak"), full_data)
        return True
    except Exception as e:
        print(f"[MoziToolKit] Error saving full config file {filepath}: {e}")
        return False


def save_config(views_data: dict) -> bool:
    """Save configuration views data to user JSON file while preserving resource_packs and material_settings."""
    return save_full_config(views_data=views_data)


def load_pack_stack_config() -> list[dict]:
    """Load configured resource pack / base JAR stack list from user JSON config."""
    full_data = load_full_config()
    packs = full_data.get("resource_packs", [])
    raw_list = list(packs) if isinstance(packs, list) else []
    return normalize_pack_entries_order(raw_list)


def save_pack_stack_config(pack_entries: list[dict]) -> bool:
    """Save resource pack stack entries to user JSON config while preserving views and material_settings."""
    return save_full_config(pack_entries=pack_entries)


def load_material_settings_config() -> dict:
    """Load configured material replacement settings from user JSON config."""
    full_data = load_full_config()
    settings = full_data.get("material_settings", {})
    default_settings = {
        "material_mode": "ATLAS",
        "biome_preset": "PLAINS",
        "pack_textures": True,
    }
    if isinstance(settings, dict):
        default_settings.update(settings)
    return default_settings


def save_material_settings_config(material_settings: dict) -> bool:
    """Save material replacement settings to user JSON config."""
    return save_full_config(material_settings=material_settings)


def get_enabled_pack_entries() -> list[dict]:
    """Return all active/enabled resource pack and JAR entries."""
    entries = load_pack_stack_config()
    return [e for e in entries if isinstance(e, dict) and e.get("enabled", True) and e.get("path")]


def reset_config() -> dict:
    """Reset configuration to default presets and save."""
    defaults = get_default_presets()
    save_config(defaults)
    return defaults


def export_config(filepath: str, views_data: dict) -> bool:
    """Export configuration to specified filepath."""
    try:
        normalized = _normalize_views_data(views_data)
        packs = load_pack_stack_config()
        data = {"version": 1, "views": normalized, "resource_packs": packs}
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
            if isinstance(data, dict):
                views = data.get("views", data)
                if isinstance(views, dict):
                    normalized = _normalize_views_data(views)
                    save_config(normalized)
                if "resource_packs" in data and isinstance(data["resource_packs"], list):
                    save_pack_stack_config(data["resource_packs"])
                return views
    except Exception as e:
        print(f"[MoziToolKit] Error importing config from {filepath}: {e}")
    return None


def draw_dynamic_menu(layout, view_name: str):
    """
    Unified drawer helper function to render configured right-click menu items.
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

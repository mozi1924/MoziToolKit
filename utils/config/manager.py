"""
Central Configuration Manager for MoziToolKit.
Provides unified, thread-safe, backend-agnostic configuration management.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .backends.base import ConfigBackend
from .backends.json_backend import JsonConfigBackend
from .backends.blender_backend import BlenderPreferencesConfigBackend
from .backends.memory_backend import MemoryConfigBackend
from .models import ConfigData, PackEntry, MaterialSettings, MenuItem, normalize_operator_id, get_default_menu_views

logger = logging.getLogger("MoziToolKit.Config")



class ConfigManager:
    """Thread-safe facade and controller managing MoziToolKit configurations."""

    _instance: Optional[ConfigManager] = None
    _singleton_lock = threading.RLock()

    def __init__(self, backend: Optional[ConfigBackend] = None):
        self._lock = threading.RLock()
        self._backend: ConfigBackend = backend or JsonConfigBackend()
        self._cache: Optional[ConfigData] = None
        self._is_syncing: bool = False

    def is_syncing(self) -> bool:
        """Check if synchronization between storage and Blender UI preferences is currently active."""
        return self._is_syncing

    @classmethod
    def get_instance(cls) -> ConfigManager:
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_instance(cls, backend: Optional[ConfigBackend] = None) -> ConfigManager:
        """Reset the singleton instance (useful for unit tests and sandbox teardown)."""
        with cls._singleton_lock:
            cls._instance = cls(backend=backend)
            return cls._instance

    # -------------------------------------------------------------------------
    # Backend Management
    # -------------------------------------------------------------------------

    def get_backend(self) -> ConfigBackend:
        with self._lock:
            return self._backend

    def set_backend(self, backend: ConfigBackend, migrate_data: bool = True) -> None:
        """Switch active configuration backend, optionally migrating in-memory data."""
        with self._lock:
            curr_data = self.get_data()
            self._backend = backend
            if migrate_data and curr_data is not None:
                curr_data.backend_type = backend.backend_name
                self._backend.save(curr_data)
                self._cache = curr_data
            else:
                self._cache = self._backend.load()

    def switch_backend_by_name(self, name: str, migrate_data: bool = True) -> ConfigBackend:
        """Switch backend by string identifier ('JSON', 'BLENDER_PREFS', 'MEMORY')."""
        with self._lock:
            name_upper = name.strip().upper()
            if name_upper == "JSON":
                new_backend = JsonConfigBackend()
            elif name_upper in {"BLENDER_PREFS", "BLENDER", "PREFERENCES"}:
                new_backend = BlenderPreferencesConfigBackend()
            elif name_upper in {"MEMORY", "TEST"}:
                new_backend = MemoryConfigBackend()
            else:
                new_backend = JsonConfigBackend()

            self.set_backend(new_backend, migrate_data=migrate_data)
            return new_backend

    # -------------------------------------------------------------------------
    # Core Data Access
    # -------------------------------------------------------------------------

    def get_data(self, force_reload: bool = False) -> ConfigData:
        """Get active configuration data (cached or loaded from backend)."""
        with self._lock:
            if self._cache is None or force_reload:
                self._cache = self._backend.load()
                self._cache.normalize()
            return self._cache

    def save(self) -> bool:
        """Persist currently cached configuration data to backend."""
        with self._lock:
            if self._cache is None:
                self._cache = self._backend.load()
            self._cache.normalize()
            return self._backend.save(self._cache)

    def reload(self) -> ConfigData:
        """Force reloading configuration from storage."""
        with self._lock:
            return self.get_data(force_reload=True)

    def reset(self) -> ConfigData:
        """Reset configuration to defaults and persist."""
        with self._lock:
            self._cache = self._backend.reset()
            self._cache.normalize()
            return self._cache

    # -------------------------------------------------------------------------
    # Context Menu Views
    # -------------------------------------------------------------------------

    def get_views(self) -> Dict[str, List[Dict[str, Any]]]:
        """Return dict of view categories ('mesh', 'object', 'uv') to list of menu item dicts."""
        data = self.get_data()
        return {
            view: [item.to_dict() for item in items]
            for view, items in data.views.items()
        }

    def set_views(self, views_data: Dict[str, Any], save: bool = True) -> bool:
        """Update context menu view categories with new items."""
        with self._lock:
            data = self.get_data()
            norm_views = {}
            for view_name in ["mesh", "object", "uv"]:
                v_list = views_data.get(view_name, [])
                items = []
                if isinstance(v_list, list):
                    for item in v_list:
                        if isinstance(item, MenuItem):
                            items.append(item)
                        elif isinstance(item, dict):
                            items.append(MenuItem.from_dict(item))
                norm_views[view_name] = items
            data.views = norm_views
            data.normalize()
            if save:
                return self.save()
            return True

    def reset_views(self, save: bool = True) -> Dict[str, List[Dict[str, Any]]]:
        """Reset only context menu views to default registered operator presets without touching resource packs or material settings."""
        with self._lock:
            data = self.get_data()
            data.views = get_default_menu_views()
            data.normalize()
            if save:
                self.save()
            return self.get_views()

    # -------------------------------------------------------------------------
    # Resource Pack Stack
    # -------------------------------------------------------------------------

    def get_resource_packs(self) -> List[Dict[str, Any]]:
        """Return sorted list of resource pack dicts."""
        data = self.get_data()
        return [p.to_dict() for p in data.resource_packs]

    def set_resource_packs(self, pack_entries: List[Union[Dict[str, Any], PackEntry]], save: bool = True) -> bool:
        """Update resource pack stack entries with automatic 3-tier ordering."""
        with self._lock:
            data = self.get_data()
            packs = []
            for p in pack_entries:
                if isinstance(p, PackEntry):
                    packs.append(p)
                elif isinstance(p, dict):
                    packs.append(PackEntry.from_dict(p))
            data.resource_packs = packs
            data.normalize()
            if save:
                return self.save()
            return True

    def get_enabled_pack_entries(self) -> List[Dict[str, Any]]:
        """Return all enabled resource pack and JAR entries that have non-empty paths."""
        packs = self.get_resource_packs()
        return [p for p in packs if p.get("enabled", True) and p.get("path")]

    # -------------------------------------------------------------------------
    # Material Settings
    # -------------------------------------------------------------------------

    def get_material_settings(self) -> Dict[str, Any]:
        """Return current material replacement settings dict."""
        data = self.get_data()
        return data.material_settings.to_dict()

    def set_material_settings(self, settings: Union[Dict[str, Any], MaterialSettings], save: bool = True) -> bool:
        """Update material replacement settings."""
        with self._lock:
            data = self.get_data()
            if isinstance(settings, MaterialSettings):
                data.material_settings = settings
            elif isinstance(settings, dict):
                data.material_settings = MaterialSettings.from_dict(settings)
            if save:
                return self.save()
            return True

    # -------------------------------------------------------------------------
    # Full Save Helper
    # -------------------------------------------------------------------------

    def save_full_config(
        self,
        views_data: Optional[Dict[str, Any]] = None,
        pack_entries: Optional[List[Any]] = None,
        material_settings: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Atomically update multiple sections and persist."""
        with self._lock:
            data = self.get_data()
            if views_data is not None:
                self.set_views(views_data, save=False)
            if pack_entries is not None:
                self.set_resource_packs(pack_entries, save=False)
            if material_settings is not None:
                self.set_material_settings(material_settings, save=False)
            return self.save()

    # -------------------------------------------------------------------------
    # Import / Export
    # -------------------------------------------------------------------------

    def export_config(self, filepath: Union[str, Path]) -> bool:
        """Export current configuration to JSON file."""
        data = self.get_data()
        return self._backend.export_to_file(Path(filepath), data)

    def import_config(self, filepath: Union[str, Path]) -> Optional[Dict[str, Any]]:
        """Import configuration from JSON file and persist."""
        with self._lock:
            imported = self._backend.import_from_file(Path(filepath))
            if imported is not None:
                self._cache = imported
                self.save()
                return self.get_views()
            return None

    # -------------------------------------------------------------------------
    # Safe Synchronization with Blender AddonPreferences
    # -------------------------------------------------------------------------

    def sync_to_preferences(self, prefs: Any, default_presets: Optional[Dict[str, Any]] = None) -> None:
        """
        Populate Blender AddonPreferences PropertyGroups safely from ConfigManager.
        Prevents re-ordering loops and marks prefs as initialized.
        """
        if prefs is None:
            return

        with self._lock:
            self._is_syncing = True
            try:
                data = self.get_data()

                # 1. Sync Resource Packs
                if hasattr(prefs, "resource_packs"):
                    if hasattr(prefs.resource_packs, "clear"):
                        prefs.resource_packs.clear()
                    if hasattr(prefs.resource_packs, "add"):
                        for p_data in data.resource_packs:
                            elem = prefs.resource_packs.add()
                            elem.name = p_data.name
                            elem.path = p_data.path
                            elem.enabled = p_data.enabled
                            elem.pack_type = p_data.pack_type
                    elif isinstance(prefs.resource_packs, list):
                        for p_data in data.resource_packs:
                            prefs.resource_packs.append(p_data.to_dict())

                # 2. Sync Material Settings
                if hasattr(prefs, "material_mode"):
                    prefs.material_mode = data.material_settings.material_mode
                if hasattr(prefs, "biome_preset"):
                    prefs.biome_preset = data.material_settings.biome_preset
                if hasattr(prefs, "pack_textures"):
                    prefs.pack_textures = data.material_settings.pack_textures

                # 3. Sync Views & Unadded items
                # Late import menu helpers to avoid circular dependencies
                try:
                    from ..system.menu_registry import ALL_OPERATORS, sort_unadded_items
                except Exception:
                    try:
                        from utils.system.menu_registry import ALL_OPERATORS, sort_unadded_items
                    except Exception:
                        ALL_OPERATORS = {}
                        sort_unadded_items = lambda coll: None

                for view in ["mesh", "object", "uv"]:
                    added_coll = getattr(prefs, f"added_{view}", None)
                    unadded_coll = getattr(prefs, f"unadded_{view}", None)
                    if added_coll is None or unadded_coll is None:
                        continue

                    if hasattr(added_coll, "clear"):
                        added_coll.clear()
                    if hasattr(unadded_coll, "clear"):
                        unadded_coll.clear()

                    added_op_ids = set()
                    view_items = data.views.get(view, [])
                    for item in view_items:
                        op_id = item.operator if isinstance(item, MenuItem) else normalize_operator_id(item.get("operator"))
                        if not op_id:
                            continue
                        added_op_ids.add(op_id)
                        default_label = ALL_OPERATORS.get(op_id, {}).get("default_label", op_id) if ALL_OPERATORS else op_id
                        item_label = item.label if isinstance(item, MenuItem) else item.get("label")
                        item_enabled = item.enabled if isinstance(item, MenuItem) else item.get("enabled", True)
                        
                        if hasattr(added_coll, "add"):
                            elem = added_coll.add()
                            elem.operator_id = op_id
                            elem.label = item_label or default_label
                            elem.enabled = item_enabled
                        elif isinstance(added_coll, list):
                            added_coll.append({"operator_id": op_id, "label": item_label or default_label, "enabled": item_enabled})

                    if ALL_OPERATORS:
                        for op_id, op_info in ALL_OPERATORS.items():
                            norm_op_id = normalize_operator_id(op_id)
                            if norm_op_id not in added_op_ids:
                                if hasattr(unadded_coll, "add"):
                                    elem = unadded_coll.add()
                                    elem.operator_id = norm_op_id
                                    elem.label = op_info.get("label", norm_op_id)
                                elif isinstance(unadded_coll, list):
                                    unadded_coll.append({"operator_id": norm_op_id, "label": op_info.get("label", norm_op_id)})

                        if hasattr(unadded_coll, "add"):
                            sort_unadded_items(unadded_coll)

                setattr(prefs, "is_initialized", True)
            finally:
                self._is_syncing = False

    def sync_from_preferences(self, prefs: Any, save: bool = True) -> bool:
        """
        Safely update ConfigManager data from Blender AddonPreferences PropertyGroups.
        
        ANTI-WIPE SAFETY GUARD:
        Refuses to overwrite existing saved resource packs or menus if `prefs` has not been
        initialized or is empty while persistent storage has active data.
        """
        if prefs is None:
            return False

        with self._lock:
            if self._is_syncing:
                return False

            is_init = getattr(prefs, "is_initialized", False)

            data = self.get_data()

            # Anti-wipe check: If prefs is not initialized and has 0 resource packs but storage has packs, abort!
            if not is_init and hasattr(prefs, "resource_packs") and len(prefs.resource_packs) == 0 and len(data.resource_packs) > 0:
                logger.warning("Anti-Wipe Guard prevented uninitialized AddonPreferences from overwriting configuration.")
                self.sync_to_preferences(prefs)
                return False


            # Extract views
            views_data = {}
            for view in ["mesh", "object", "uv"]:
                added_coll = getattr(prefs, f"added_{view}", None)
                if added_coll is not None:
                    items_list = []
                    for elem in added_coll:
                        items_list.append(
                            MenuItem(
                                operator=normalize_operator_id(getattr(elem, "operator_id", "")),
                                label=getattr(elem, "label", ""),
                                enabled=getattr(elem, "enabled", True),
                            )
                        )
                    views_data[view] = items_list

            # Extract resource packs
            packs_list = []
            if hasattr(prefs, "resource_packs"):
                for p_elem in prefs.resource_packs:
                    packs_list.append(
                        PackEntry(
                            name=getattr(p_elem, "name", "Resource Pack"),
                            path=getattr(p_elem, "path", ""),
                            enabled=getattr(p_elem, "enabled", True),
                            pack_type=getattr(p_elem, "pack_type", "RESOURCE_PACK"),
                        )
                    )

            # Extract material settings
            mat_settings = MaterialSettings(
                material_mode=getattr(prefs, "material_mode", "ATLAS"),
                biome_preset=getattr(prefs, "biome_preset", "PLAINS"),
                pack_textures=getattr(prefs, "pack_textures", True),
            )

            # Update cache
            if views_data:
                data.views = views_data
            if packs_list or is_init:
                data.resource_packs = packs_list
            data.material_settings = mat_settings
            data.normalize()

            if save:
                return self.save()
            return True

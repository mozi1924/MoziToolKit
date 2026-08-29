"""
Blender Native AddonPreferences Configuration Backend.
Persists configuration directly into Blender's user preferences (userpref.blend).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .base import ConfigBackend
from ..models import ConfigData, PackEntry, MaterialSettings, MenuItem

logger = logging.getLogger("MoziToolKit.Config.BlenderPrefs")


try:
    import bpy
except ImportError:
    bpy = None


def _get_active_addon_prefs():
    """Retrieve active MoziToolKit AddonPreferences from bpy.context."""
    if bpy is None or not hasattr(bpy, "context"):
        return None
    try:
        context = bpy.context
        if not hasattr(context, "preferences") or not context.preferences:
            return None
        addons = getattr(context.preferences, "addons", None)
        if not addons:
            return None

        pref_cls = getattr(bpy.types, "MOZI_AddonPreferences", None)
        for addon in addons.values():
            pref = getattr(addon, "preferences", None)
            if pref is not None:
                if pref_cls and isinstance(pref, pref_cls):
                    return pref
                if hasattr(pref, "resource_packs") or hasattr(pref, "added_mesh"):
                    return pref

        for name in ["bl_ext.user_default.MoziToolKit", "bl_ext.vscode_development.MoziToolKit", "MoziToolKit"]:
            addon = addons.get(name)
            if addon and getattr(addon, "preferences", None) is not None:
                return addon.preferences
    except Exception:
        pass
    return None


class BlenderPreferencesConfigBackend(ConfigBackend):
    """
    Persists configuration into Blender's native AddonPreferences and userpref.blend.
    """

    def __init__(self):
        self._cached_data: Optional[ConfigData] = None

    @property
    def backend_name(self) -> str:
        return "BLENDER_PREFS"

    def load(self) -> ConfigData:
        """Load configuration from Blender AddonPreferences."""
        prefs = _get_active_addon_prefs()
        if prefs is None:
            if self._cached_data is not None:
                return self._cached_data
            cfg = ConfigData()
            cfg.backend_type = "BLENDER_PREFS"
            return cfg

        # 1. Check if serialized full json is stored on preferences
        serialized = getattr(prefs, "_mozi_serialized_config", "")
        if serialized:
            try:
                data = json.loads(serialized)
                if isinstance(data, dict):
                    cfg = ConfigData.from_dict(data)
                    cfg.backend_type = "BLENDER_PREFS"
                    self._cached_data = cfg
                    return cfg
            except Exception:
                pass

        # 2. Extract from PropertyGroups
        views = {"mesh": [], "object": [], "uv": []}
        for view_name in ["mesh", "object", "uv"]:
            coll = getattr(prefs, f"added_{view_name}", None)
            if coll:
                for elem in coll:
                    views[view_name].append(
                        MenuItem(
                            operator=getattr(elem, "operator_id", ""),
                            label=getattr(elem, "label", ""),
                            enabled=getattr(elem, "enabled", True),
                        )
                    )

        packs = []
        if hasattr(prefs, "resource_packs"):
            for p in prefs.resource_packs:
                packs.append(
                    PackEntry(
                        name=getattr(p, "name", "Resource Pack"),
                        path=getattr(p, "path", ""),
                        enabled=getattr(p, "enabled", True),
                        pack_type=getattr(p, "pack_type", "RESOURCE_PACK"),
                    )
                )

        mat_settings = MaterialSettings(
            material_mode=getattr(prefs, "material_mode", "ATLAS"),
            biome_preset=getattr(prefs, "biome_preset", "PLAINS"),
            pack_textures=getattr(prefs, "pack_textures", True),
        )

        cfg = ConfigData(
            version=1,
            backend_type="BLENDER_PREFS",
            views=views,
            resource_packs=packs,
            material_settings=mat_settings,
        )
        cfg.normalize()
        self._cached_data = cfg
        return cfg

    def save(self, data: ConfigData) -> bool:
        """Save configuration into Blender AddonPreferences and save userpref."""
        self._cached_data = data
        prefs = _get_active_addon_prefs()
        if prefs is None:
            return True

        try:
            dict_data = data.to_dict()
            dict_data["backend_type"] = "BLENDER_PREFS"

            # Store serialized string
            try:
                setattr(prefs, "_mozi_serialized_config", json.dumps(dict_data))
            except Exception:
                pass

            # Sync material settings
            if hasattr(prefs, "material_mode"):
                prefs.material_mode = data.material_settings.material_mode
            if hasattr(prefs, "biome_preset"):
                prefs.biome_preset = data.material_settings.biome_preset
            if hasattr(prefs, "pack_textures"):
                prefs.pack_textures = data.material_settings.pack_textures

            # Auto-save Blender user preferences if supported
            if bpy and hasattr(bpy.ops, "wm") and hasattr(bpy.ops.wm, "save_userpref"):
                try:
                    if not getattr(bpy.app, "background", False):
                        bpy.ops.wm.save_userpref()
                except Exception:
                    pass

            return True
        except Exception as e:
            logger.error(f"Error saving to Blender preferences: {e}", exc_info=True)
            return False

    def reset(self) -> ConfigData:
        """Reset configuration to defaults."""
        default_cfg = ConfigData()
        default_cfg.backend_type = "BLENDER_PREFS"
        self.save(default_cfg)
        return default_cfg

    def export_to_file(self, filepath: Path, data: ConfigData) -> bool:
        try:
            p = Path(filepath)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data.to_dict(), f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Error exporting config to {filepath}: {e}", exc_info=True)
            return False

    def import_from_file(self, filepath: Path) -> Optional[ConfigData]:
        try:
            p = Path(filepath)
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg = ConfigData.from_dict(data)
                cfg.backend_type = "BLENDER_PREFS"
                return cfg
        except Exception as e:
            logger.error(f"Error importing config from {filepath}: {e}", exc_info=True)
        return None


"""
JSON File Configuration Backend with Atomic I/O and Backup Recovery.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from .base import ConfigBackend
from ..models import ConfigData

logger = logging.getLogger("MoziToolKit.Config.JSON")


try:
    import bpy
except ImportError:
    bpy = None


class JsonConfigBackend(ConfigBackend):
    """
    Persists configuration in a local JSON file with:
    - Environment sandbox support (`MOZI_CONFIG_DIR`)
    - Durably atomic writes using temporary files and directory fsync
    - Automated `.bak` generation and corrupted-file recovery
    """

    def __init__(self, custom_path: Optional[Path] = None):
        self._custom_path = Path(custom_path) if custom_path else None

    @property
    def backend_name(self) -> str:
        return "JSON"

    def get_config_path(self) -> Path:
        """Return path to JSON configuration file."""
        if self._custom_path:
            self._custom_path.parent.mkdir(parents=True, exist_ok=True)
            return self._custom_path

        env_dir = os.environ.get("MOZI_CONFIG_DIR")
        if env_dir:
            config_dir = Path(env_dir)
        else:
            try:
                config_dir = Path(bpy.utils.user_resource("CONFIG")) / "MoziToolKit"
            except Exception:
                config_dir = Path.home() / ".config" / "blender" / "MoziToolKit"

        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "context_menus.json"

    def _atomic_write_json(self, filepath: Path, data: dict) -> None:
        """Durably replace a JSON file without ever exposing a partial document."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{filepath.stem}.", suffix=".tmp", dir=filepath.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                json.dump(data, fp, indent=4, ensure_ascii=False)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp_name, filepath)
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

    def _load_json_dict(self, filepath: Path) -> Optional[dict]:
        """Return parsed dictionary from filepath, or None if file does not exist or is invalid."""
        if not filepath.exists():
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return None

    def load(self) -> ConfigData:
        """Load configuration from main file, falling back to .bak if damaged, or returning clean defaults."""
        filepath = self.get_config_path()

        # 1. Try reading primary config file
        data = self._load_json_dict(filepath)
        if data is not None and ("views" in data or "resource_packs" in data or "material_settings" in data):
            cfg = ConfigData.from_dict(data)
            cfg.backend_type = "JSON"
            return cfg

        # 2. Try recovering from backup file
        backup_path = filepath.with_suffix(filepath.suffix + ".bak")
        backup_data = self._load_json_dict(backup_path)
        if backup_data is not None and ("views" in backup_data or "resource_packs" in backup_data or "material_settings" in backup_data):
            logger.info(f"Recovered configuration from backup: {backup_path}")
            cfg = ConfigData.from_dict(backup_data)
            cfg.backend_type = "JSON"
            # Restore primary file from valid backup
            try:
                self._atomic_write_json(filepath, cfg.to_dict())
            except Exception:
                pass
            return cfg

        # 3. Return fresh default config
        default_cfg = ConfigData()
        default_cfg.backend_type = "JSON"
        return default_cfg

    def save(self, data: ConfigData) -> bool:
        """Atomically persist configuration and create .bak backup."""
        filepath = self.get_config_path()
        try:
            dict_data = data.to_dict()
            dict_data["backend_type"] = "JSON"
            self._atomic_write_json(filepath, dict_data)
            # Update backup
            backup_path = filepath.with_suffix(filepath.suffix + ".bak")
            self._atomic_write_json(backup_path, dict_data)
            return True
        except Exception as e:
            logger.error(f"Error saving JSON config to {filepath}: {e}", exc_info=True)
            return False

    def reset(self) -> ConfigData:
        """Reset configuration to defaults and save."""
        default_cfg = ConfigData()
        default_cfg.backend_type = "JSON"
        self.save(default_cfg)
        return default_cfg

    def export_to_file(self, filepath: Path, data: ConfigData) -> bool:
        """Export configuration to specified external JSON file path."""
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
        """Import configuration from specified external JSON file path."""
        try:
            p = Path(filepath)
            data = self._load_json_dict(p)
            if data is not None:
                cfg = ConfigData.from_dict(data)
                return cfg
        except Exception as e:
            logger.error(f"Error importing config from {filepath}: {e}", exc_info=True)
        return None


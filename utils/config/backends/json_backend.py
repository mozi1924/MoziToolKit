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

    def _migrate_legacy_config_if_needed(self, config_dir: Path) -> Path:
        """
        Migrate legacy context_menus.json to config.json if needed.

        Rules:
        - If config.json already exists: use config.json directly (no migration).
        - If context_menus.json exists and config.json does not exist:
          rewrite context_menus.json into config.json (with backup) and remove legacy file.
        - If neither exists: use config.json.
        """
        target_path = config_dir / "config.json"
        legacy_path = config_dir / "context_menus.json"

        # If config.json already exists, use it directly without migration.
        if target_path.exists():
            return target_path

        # If context_menus.json exists and config.json does not exist:
        if legacy_path.exists():
            try:
                data = self._load_json_dict(legacy_path)
                legacy_bak = legacy_path.with_suffix(legacy_path.suffix + ".bak")
                if data is None and legacy_bak.exists():
                    data = self._load_json_dict(legacy_bak)

                if data is not None:
                    # Write to target_path atomically
                    self._atomic_write_json(target_path, data)
                    # Also write target backup
                    target_bak = target_path.with_suffix(target_path.suffix + ".bak")
                    self._atomic_write_json(target_bak, data)
                    logger.info("Migrated legacy configuration from %s to %s", legacy_path, target_path)

                # Remove legacy files
                try:
                    legacy_path.unlink(missing_ok=True)
                except OSError as e:
                    logger.warning("Failed to remove legacy config file %s: %s", legacy_path, e)

                if legacy_bak.exists():
                    try:
                        legacy_bak.unlink(missing_ok=True)
                    except OSError:
                        pass
            except Exception as e:
                logger.error("Error during legacy config migration: %s", e, exc_info=True)

        return target_path

    def get_config_path(self) -> Path:
        """Return path to JSON configuration file, performing legacy migration if needed."""
        if self._custom_path:
            self._custom_path.parent.mkdir(parents=True, exist_ok=True)
            if self._custom_path.name == "context_menus.json":
                return self._migrate_legacy_config_if_needed(self._custom_path.parent)
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
        return self._migrate_legacy_config_if_needed(config_dir)

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
            if os.name == "posix":
                # POSIX only: fsync the directory so the rename is durable.
                # Windows cannot open a directory handle this way, and NTFS
                # journals the rename on its own.
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


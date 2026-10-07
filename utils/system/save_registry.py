"""
MoziToolKit Local Privacy Save Registry Manager.

Manages local Minecraft save directory mappings securely in the user's local
application config directory (CONFIG/MoziToolKit/save_registry.json), aligned
with right-click menu configuration (context_menus.json).

Guarantees that sensitive local filesystem paths (e.g. /Users/username/...)
are NEVER saved into portable .blend scene files, storing only an anonymous
UUID within the object custom properties.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Dict, Optional
import uuid

try:
    import bpy
except ImportError:
    bpy = None

logger = logging.getLogger("MoziToolKit.System.SaveRegistry")


class SaveRegistryManager:
    """
    Local privacy registry for Minecraft world save paths.
    Maps anonymous container UUIDs to local world folder paths.
    """

    CURRENT_VERSION = 1

    def __init__(self, registry_file: Optional[Path | str] = None):
        self._custom_path = Path(registry_file) if registry_file else None
        self._cache: Optional[Dict[str, Any]] = None

    def get_registry_path(self) -> Path:
        """Resolve the path to save_registry.json with robust fallbacks."""
        if self._custom_path:
            self._custom_path.parent.mkdir(parents=True, exist_ok=True)
            return self._custom_path

        env_dir = os.environ.get("MOZI_CONFIG_DIR")
        if env_dir:
            base_dir = Path(env_dir)
        else:
            try:
                if bpy and hasattr(bpy, "utils") and hasattr(bpy.utils, "user_resource"):
                    base_dir = Path(bpy.utils.user_resource("CONFIG")) / "MoziToolKit"
                else:
                    base_dir = Path.home() / ".config" / "blender" / "MoziToolKit"
            except Exception:
                base_dir = Path.home() / ".config" / "blender" / "MoziToolKit"

        base_dir.mkdir(parents=True, exist_ok=True)
        target_path = base_dir / "save_registry.json"

        # Migrate from legacy DATAFILES directory if needed
        try:
            if not target_path.exists() and bpy and hasattr(bpy, "utils") and hasattr(bpy.utils, "user_resource"):
                legacy_path = Path(bpy.utils.user_resource("DATAFILES")) / "MoziToolKit" / "save_registry.json"
                if legacy_path.exists():
                    import shutil
                    shutil.copy2(legacy_path, target_path)
        except Exception:
            pass

        return target_path

    def _atomic_write_json(self, filepath: Path, data: dict) -> None:
        """Atomically writes JSON to disk using a temporary file and fsync."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{filepath.stem}.", suffix=".tmp", dir=filepath.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                json.dump(data, fp, indent=2, ensure_ascii=False)
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

    def load(self, force_reload: bool = False) -> Dict[str, Any]:
        """Loads records from the local registry file."""
        if self._cache is not None and not force_reload:
            return self._cache

        filepath = self.get_registry_path()
        if not filepath.exists():
            data = {"version": self.CURRENT_VERSION, "records": {}}
            self._cache = data
            return data

        try:
            with open(filepath, "r", encoding="utf-8") as fp:
                content = json.load(fp)
                if isinstance(content, dict) and "records" in content:
                    self._cache = content
                    return content
                # Legacy or raw format
                data = {"version": self.CURRENT_VERSION, "records": content if isinstance(content, dict) else {}}
                self._cache = data
                return data
        except Exception as e:
            logger.warning(f"Failed to read save registry at {filepath}: {e}; initializing empty registry.")
            data = {"version": self.CURRENT_VERSION, "records": {}}
            self._cache = data
            return data

    def save(self) -> None:
        """Persists cached records atomically to disk."""
        if self._cache is None:
            return
        filepath = self.get_registry_path()
        try:
            self._atomic_write_json(filepath, self._cache)
        except Exception as e:
            logger.error(f"Failed writing save registry to {filepath}: {e}")
            raise

    def register_save(
        self,
        world_dir: str | Path,
        dimension: str = "overworld",
        level_name: str = "",
        save_uuid: Optional[str] = None,
    ) -> str:
        """
        Registers or updates a local world save folder mapping.
        Returns the unique anonymous save_uuid.
        """
        data = self.load()
        records: Dict[str, Any] = data.setdefault("records", {})
        norm_path = str(Path(world_dir).resolve())

        # If save_uuid is not specified, check if this path + dimension already exists
        if not save_uuid:
            for uid, info in records.items():
                if info.get("world_dir") == norm_path and info.get("dimension") == dimension:
                    now = time.time()
                    info["last_refreshed"] = now
                    if level_name:
                        info["level_name"] = level_name
                    self.save()
                    return uid

            save_uuid = uuid.uuid4().hex

        now = time.time()
        record = records.get(save_uuid, {})
        record.update({
            "world_dir": norm_path,
            "dimension": dimension,
            "level_name": level_name or record.get("level_name", Path(norm_path).name),
            "created_at": record.get("created_at", now),
            "last_refreshed": now,
        })
        records[save_uuid] = record
        self.save()
        return save_uuid

    def get_save_info(self, save_uuid: str) -> Optional[Dict[str, Any]]:
        """Retrieves metadata record for a given save UUID."""
        if not save_uuid:
            return None
        data = self.load()
        return data.get("records", {}).get(save_uuid)

    def get_world_dir(self, save_uuid: str) -> Optional[Path]:
        """Resolves local world directory Path for a given save UUID if registered."""
        info = self.get_save_info(save_uuid)
        if not info or not info.get("world_dir"):
            return None
        return Path(info["world_dir"])

    def is_path_valid(self, save_uuid: str) -> bool:
        """Checks if the save UUID is registered and the local folder exists."""
        world_dir = self.get_world_dir(save_uuid)
        return world_dir is not None and world_dir.exists() and world_dir.is_dir()

    def relink_save(self, save_uuid: str, new_world_dir: str | Path) -> bool:
        """
        Updates the local path association for an existing UUID.
        Useful when an imported scene is opened on another machine or when
        the save directory was moved locally.
        """
        if not save_uuid:
            return False
        data = self.load()
        records = data.setdefault("records", {})
        norm_path = str(Path(new_world_dir).resolve())
        now = time.time()

        if save_uuid in records:
            records[save_uuid]["world_dir"] = norm_path
            records[save_uuid]["last_refreshed"] = now
        else:
            records[save_uuid] = {
                "world_dir": norm_path,
                "dimension": "overworld",
                "level_name": Path(norm_path).name,
                "created_at": now,
                "last_refreshed": now,
            }

        self.save()
        return True

    def update_refreshed_time(self, save_uuid: str) -> None:
        """Updates last_refreshed timestamp for an existing UUID."""
        info = self.get_save_info(save_uuid)
        if info:
            info["last_refreshed"] = time.time()
            self.save()

    def remove_save(self, save_uuid: str) -> bool:
        """Removes a record by its UUID."""
        data = self.load()
        records = data.get("records", {})
        if save_uuid in records:
            del records[save_uuid]
            self.save()
            return True
        return False

    def clear(self) -> None:
        """Clears all records."""
        self._cache = {"version": self.CURRENT_VERSION, "records": {}}
        self.save()


_GLOBAL_REGISTRY: Optional[SaveRegistryManager] = None


def get_save_registry() -> SaveRegistryManager:
    """Returns the process-wide SaveRegistryManager singleton."""
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = SaveRegistryManager()
    return _GLOBAL_REGISTRY

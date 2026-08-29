"""
In-Memory Configuration Backend for Unit Testing and Transient Sandboxes.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Optional

from .base import ConfigBackend
from ..models import ConfigData

logger = logging.getLogger("MoziToolKit.Config.Memory")


class MemoryConfigBackend(ConfigBackend):
    """
    Pure in-memory configuration backend. Never reads or writes disk files.
    """

    def __init__(self, initial_data: Optional[ConfigData] = None):
        if initial_data is not None:
            self._data = copy.deepcopy(initial_data)
        else:
            self._data = ConfigData()
        self._data.backend_type = "MEMORY"

    @property
    def backend_name(self) -> str:
        return "MEMORY"

    def load(self) -> ConfigData:
        return copy.deepcopy(self._data)

    def save(self, data: ConfigData) -> bool:
        self._data = copy.deepcopy(data)
        self._data.backend_type = "MEMORY"
        return True

    def reset(self) -> ConfigData:
        self._data = ConfigData()
        self._data.backend_type = "MEMORY"
        return copy.deepcopy(self._data)

    def export_to_file(self, filepath: Path, data: ConfigData) -> bool:
        try:
            p = Path(filepath)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data.to_dict(), f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Error exporting memory config to {filepath}: {e}", exc_info=True)
            return False

    def import_from_file(self, filepath: Path) -> Optional[ConfigData]:
        try:
            p = Path(filepath)
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg = ConfigData.from_dict(data)
                cfg.backend_type = "MEMORY"
                return cfg
        except Exception as e:
            logger.error(f"Error importing memory config from {filepath}: {e}", exc_info=True)
        return None


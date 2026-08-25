"""
Abstract Base Class for MoziToolKit Configuration Backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ..models import ConfigData


class ConfigBackend(ABC):
    """Abstract interface defining required methods for configuration storage backends."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Human-readable name of the backend (e.g. 'JSON', 'BLENDER_PREFS', 'MEMORY')."""
        pass

    @abstractmethod
    def load(self) -> ConfigData:
        """Load and return current configuration data."""
        pass

    @abstractmethod
    def save(self, data: ConfigData) -> bool:
        """Save configuration data to backend storage. Return True if successful."""
        pass

    @abstractmethod
    def reset(self) -> ConfigData:
        """Reset configuration storage to defaults and return new ConfigData."""
        pass

    @abstractmethod
    def export_to_file(self, filepath: Path, data: ConfigData) -> bool:
        """Export given configuration data to an external JSON file."""
        pass

    @abstractmethod
    def import_from_file(self, filepath: Path) -> Optional[ConfigData]:
        """Import configuration data from an external JSON file."""
        pass

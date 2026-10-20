"""
MoziToolKit Utils: Physical Material Properties Configuration Manager.

Loads custom block/texture physical attributes (emission, thin wall, transmission,
and alpha sticker threshold) from JSON configuration files and registers them into
the Rust libmtk core.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union

try:
    from ...bridge.material import (
        register_material_properties as _bridge_register,
        reset_material_properties as _bridge_reset,
    )
except (ImportError, ValueError):
    from bridge.material import (
        register_material_properties as _bridge_register,
        reset_material_properties as _bridge_reset,
    )

logger = logging.getLogger("MoziToolKit.Utils.Materials.Config")


def get_default_material_properties_path() -> Path:
    """Return default configuration path in MoziToolKit/configs/material_properties.json."""
    return Path(__file__).resolve().parent.parent.parent / "configs" / "material_properties.json"


def load_material_properties_config(
    config: Optional[Union[str, Path, Dict[str, Any]]] = None,
    replace: bool = False,
) -> bool:
    """
    Load physical material properties (emission, thin wall, transmission, sticker threshold)
    from JSON file or dict and registers them into the Rust core registry via bridge.

    Args:
        config: Path to a JSON file, raw JSON string, or dict. If None, loads from `configs/material_properties.json`.
        replace: If True, completely replaces the Rust registry; if False, merges/overrides.
    """
    if config is None:
        cfg_path = get_default_material_properties_path()
        if not cfg_path.is_file():
            return False
        config = cfg_path

    if isinstance(config, (str, Path)):
        p = Path(config)
        if p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception as e:
                logger.error("Failed to read material properties JSON '%s': %s", p, e)
                return False
        else:
            if isinstance(config, str) and config.strip().startswith("{"):
                try:
                    payload = json.loads(config)
                except Exception as e:
                    logger.error("Failed to parse material properties JSON string: %s", e)
                    return False
            else:
                logger.error("Material properties file not found: %s", p)
                return False
    elif isinstance(config, dict):
        payload = config
    else:
        logger.error("Unsupported config type: %s", type(config))
        return False

    return _bridge_register(payload, replace=replace)


def reset_material_properties_config() -> bool:
    """Reset Rust core material properties to built-in vanilla defaults."""
    return _bridge_reset()


__all__ = [
    "get_default_material_properties_path",
    "load_material_properties_config",
    "reset_material_properties_config",
]

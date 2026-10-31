"""
Dynamic Skins Material and Image Builder for player heads and custom skulls.
(Re-exports from unified dynamic_entities module).
"""

from __future__ import annotations

from .dynamic_entities import (
    DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID,
    DEFAULT_DYNAMIC_SKINS_CHUNK_ID,
    DYNAMIC_CHUNK_END,
    DYNAMIC_CHUNK_START,
    DYNAMIC_ENTITIES_IMAGE_NAME,
    DYNAMIC_ENTITIES_MATERIAL_NAME,
    DYNAMIC_SKINS_IMAGE_NAME,
    DYNAMIC_SKINS_MATERIAL_NAME,
    build_dynamic_entities_material,
    build_dynamic_skins_material,
    dynamic_entities_image_name,
    dynamic_entities_material_name,
    dynamic_skins_image_name,
    dynamic_skins_material_name,
    update_dynamic_entities_image,
    update_dynamic_skins_image,
)

__all__ = [
    "DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID",
    "DEFAULT_DYNAMIC_SKINS_CHUNK_ID",
    "DYNAMIC_CHUNK_END",
    "DYNAMIC_CHUNK_START",
    "DYNAMIC_ENTITIES_IMAGE_NAME",
    "DYNAMIC_ENTITIES_MATERIAL_NAME",
    "DYNAMIC_SKINS_IMAGE_NAME",
    "DYNAMIC_SKINS_MATERIAL_NAME",
    "build_dynamic_entities_material",
    "build_dynamic_skins_material",
    "dynamic_entities_image_name",
    "dynamic_entities_material_name",
    "dynamic_skins_image_name",
    "dynamic_skins_material_name",
    "update_dynamic_entities_image",
    "update_dynamic_skins_image",
]

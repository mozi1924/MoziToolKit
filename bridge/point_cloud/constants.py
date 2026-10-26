"""
Constants and attribute name definitions for Voxel Point Cloud.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..mesh.attribute_schema import (
    ATTR_BIOME_IDX,
    ATTR_BIOME_PALETTE,
    ATTR_BLOCK_X,
    ATTR_BLOCK_Y,
    ATTR_BLOCK_Z,
    ATTR_ENTITY_IDX,
    ATTR_ENTITY_PALETTE,
    ATTR_LIGHT,
    ATTR_PALETTE,
    ATTR_STATE_IDX,
)
from ..mesh.constants import get_or_create_attribute

logger = logging.getLogger("MoziToolKit.Bridge.PointCloud.Constants")

MASK_MODIFIER_NAME = "MTK_Voxel_Mask"
VOXEL_VERTEX_GROUP = "MTK_Voxel_Storage"

# Canonical active attributes (imported directly from authoritative schema)
ATTR_BLOCK_STATE_IDX = ATTR_STATE_IDX
ATTR_BLOCK_ENTITY_IDX = ATTR_ENTITY_IDX
PROP_BLOCK_PALETTE = ATTR_PALETTE
PROP_BIOME_PALETTE = ATTR_BIOME_PALETTE
PROP_BLOCK_ENTITY_PALETTE = ATTR_ENTITY_PALETTE

# Legacy/retired attributes kept for backwards-compatibility checks
ATTR_BLOCK_STATE = "mtk_block_state"
ATTR_BIOME = "mtk_biome"


def ensure_attr(target_data: Any, name: str, attr_type: str, domain: str = "POINT") -> Optional[Any]:
    """Helper to safely acquire or create an attribute on a mesh or point cloud datablock."""
    return get_or_create_attribute(target_data, name, attr_type, domain)

"""
Constants and attribute name definitions for Voxel Point Cloud.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("MoziToolKit.Bridge.PointCloud.Constants")

MASK_MODIFIER_NAME = "MTK_Voxel_Mask"
VOXEL_VERTEX_GROUP = "MTK_Voxel_Storage"
ATTR_BLOCK_X = "mtk_block_x"
ATTR_BLOCK_Y = "mtk_block_y"
ATTR_BLOCK_Z = "mtk_block_z"
ATTR_BLOCK_STATE = "mtk_block_state"
ATTR_BLOCK_STATE_IDX = "mtk_state_idx"
ATTR_BIOME = "mtk_biome"
ATTR_BIOME_IDX = "mtk_biome_idx"
ATTR_LIGHT = "mtk_light"

PROP_BLOCK_PALETTE = "mtk_palette"
PROP_BIOME_PALETTE = "mtk_biome_palette"


def ensure_attr(target_data: Any, name: str, attr_type: str, domain: str = "POINT") -> Optional[Any]:
    """Helper to safely acquire or create an attribute on a mesh or point cloud datablock."""
    if not hasattr(target_data, "attributes"):
        return None
    attr = target_data.attributes.get(name)
    if attr is not None and (attr.data_type != attr_type or attr.domain != domain):
        try:
            target_data.attributes.remove(attr)
        except Exception:
            pass
        attr = None
    if attr is None:
        try:
            attr = target_data.attributes.new(name=name, type=attr_type, domain=domain)
        except Exception as e:
            logger.warning("Failed creating attribute %s: %s", name, e)
            return None
    return attr

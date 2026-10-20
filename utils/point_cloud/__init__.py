"""
MoziToolKit Utils: Voxel Point Cloud Scene & Hierarchy Management.

Provides Blender object hierarchy, Mask modifier gating, and selection utilities
for companion voxel point clouds.
"""

from __future__ import annotations

from .hierarchy import (
    MASK_MODIFIER_NAME,
    VOXEL_VERTEX_GROUP,
    ensure_voxel_child_cloud,
    get_associated_parent_mesh,
    get_associated_voxel_cloud,
    is_voxel_cloud_visible,
    set_voxel_cloud_visibility,
    set_voxel_mask_threshold,
    setup_voxel_mask_modifier,
)

__all__ = [
    "MASK_MODIFIER_NAME",
    "VOXEL_VERTEX_GROUP",
    "setup_voxel_mask_modifier",
    "set_voxel_mask_threshold",
    "set_voxel_cloud_visibility",
    "is_voxel_cloud_visible",
    "get_associated_voxel_cloud",
    "get_associated_parent_mesh",
    "ensure_voxel_child_cloud",
]

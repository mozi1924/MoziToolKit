"""
MoziToolKit Voxel Point Cloud Bridge Module.

Manages lossless persistent 3D voxel point clouds, bidirectional conversion
with Rust libmtk_py.VoxelPointCloud, native Mask Modifier hiding/showing
with configurable weight thresholds, and user-driven voxel carving/remeshing.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from ..dna import is_dna_enabled
from .constants import (
    ATTR_BIOME,
    ATTR_BIOME_IDX,
    ATTR_BLOCK_STATE,
    ATTR_BLOCK_STATE_IDX,
    ATTR_BLOCK_X,
    ATTR_BLOCK_Y,
    ATTR_BLOCK_Z,
    ATTR_LIGHT,
    MASK_MODIFIER_NAME,
    PROP_BIOME_PALETTE,
    PROP_BLOCK_PALETTE,
    VOXEL_VERTEX_GROUP,
    ensure_attr,
)
from .dna import inject_point_cloud_dna
from .extract import extract_voxel_point_cloud
from .hierarchy import (
    ensure_voxel_child_cloud,
    get_associated_parent_mesh,
    get_associated_voxel_cloud,
    is_voxel_cloud_visible,
    set_voxel_cloud_visibility,
    set_voxel_mask_threshold,
    setup_voxel_mask_modifier,
)
from .standard import inject_point_cloud_standard

logger = logging.getLogger("MoziToolKit.Bridge.PointCloud")


def inject_voxel_point_cloud(
    cloud_obj_or_mesh: Any,
    cloud_data: Any,
    update_mask: bool = True,
    initial_hidden: bool = True,
    fast_mode: bool = True,
    use_dna: bool = True,
) -> bool:
    """
    Injects a Rust VoxelPointCloud into a Blender Mesh or PointCloud datablock.

    Features a dual-channel execution model: prioritizes hardware-speed zero-copy
    DNA raw pointer ingestion, seamlessly falling back to standard BPy foreach_set.
    """
    if not HAS_BPY:
        return False

    is_pc = False
    if hasattr(cloud_obj_or_mesh, "data"):
        obj = cloud_obj_or_mesh
        target_data = cloud_obj_or_mesh.data
        if getattr(cloud_obj_or_mesh, "type", "") == "POINTCLOUD":
            is_pc = True
    else:
        obj = None
        target_data = cloud_obj_or_mesh
        if hasattr(target_data, "points") and hasattr(target_data, "resize"):
            is_pc = True

    pt_count = len(cloud_data) if hasattr(cloud_data, "__len__") else cloud_data.len()
    if pt_count == 0:
        if hasattr(target_data, "clear_geometry"):
            target_data.clear_geometry()
        elif hasattr(target_data, "resize"):
            target_data.resize(0)
        return True

    # 1. Allocate points
    if is_pc or hasattr(target_data, "resize"):
        target_data.resize(pt_count)
    elif hasattr(target_data, "clear_geometry") and hasattr(target_data.vertices, "add"):
        target_data.clear_geometry()
        target_data.vertices.add(pt_count)

    # 2. Pre-allocate standard attributes
    attr_x = ensure_attr(target_data, ATTR_BLOCK_X, "INT", "POINT")
    attr_y = ensure_attr(target_data, ATTR_BLOCK_Y, "INT", "POINT")
    attr_z = ensure_attr(target_data, ATTR_BLOCK_Z, "INT", "POINT")
    attr_state_idx = ensure_attr(target_data, ATTR_BLOCK_STATE_IDX, "INT", "POINT")
    attr_biome_idx = ensure_attr(target_data, ATTR_BIOME_IDX, "INT", "POINT")

    # 3. Direct Pointer Fast Path (Zero-Copy DNA)
    injected = False
    if fast_mode and use_dna and is_dna_enabled():
        try:
            injected = inject_point_cloud_dna(target_data, cloud_data, pt_count, obj=obj)
        except Exception as e:
            logger.debug("DNA direct point cloud copy fallback: %s", e)
            injected = False

    # 4. Standard Python API Fallback
    if not injected:
        inject_point_cloud_standard(
            target_data,
            cloud_data,
            pt_count,
            obj=obj,
            attr_x=attr_x,
            attr_y=attr_y,
            attr_z=attr_z,
            attr_state_idx=attr_state_idx,
            attr_biome_idx=attr_biome_idx,
        )

    # 5. Configure Mask Modifier
    if update_mask and obj is not None and getattr(obj, "type", "") == "MESH":
        setup_voxel_mask_modifier(obj, initial_hidden=initial_hidden)

    if hasattr(target_data, "update"):
        target_data.update()

    return True


__all__ = [
    "ATTR_BIOME",
    "ATTR_BIOME_IDX",
    "ATTR_BLOCK_STATE",
    "ATTR_BLOCK_STATE_IDX",
    "ATTR_BLOCK_X",
    "ATTR_BLOCK_Y",
    "ATTR_BLOCK_Z",
    "ATTR_LIGHT",
    "MASK_MODIFIER_NAME",
    "PROP_BIOME_PALETTE",
    "PROP_BLOCK_PALETTE",
    "VOXEL_VERTEX_GROUP",
    "ensure_voxel_child_cloud",
    "extract_voxel_point_cloud",
    "get_associated_parent_mesh",
    "get_associated_voxel_cloud",
    "inject_voxel_point_cloud",
    "is_voxel_cloud_visible",
    "set_voxel_cloud_visibility",
    "set_voxel_mask_threshold",
    "setup_voxel_mask_modifier",
]

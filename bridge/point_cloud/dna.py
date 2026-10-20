"""
Zero-Copy Direct Memory DNA Ingestion Channel for Voxel Point Cloud.

Bypasses Python array allocation and copies coordinates and palette indices directly
into Blender CustomData memory layers.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..dna import is_dna_available, resolve_point_cloud_ptrs
from ..engine import get_libmtk_dna
from .constants import PROP_BIOME_PALETTE, PROP_BLOCK_PALETTE

logger = logging.getLogger("MoziToolKit.Bridge.PointCloud.DNA")


def _byte_view(mv: Any) -> memoryview:
    return memoryview(mv).cast("B")


def inject_point_cloud_dna(
    target_data: Any,
    cloud_data: Any,
    pt_count: int,
    obj: Optional[Any] = None,
) -> bool:
    """
    Directly copies all voxel point cloud attributes via hardware-accelerated memory pointers.
    Returns True if successfully injected, False if pointers were invalid or copy failed.
    """
    blender_dna = get_libmtk_dna()
    if blender_dna is None or not is_dna_available():
        return False

    if pt_count == 0:
        return True

    # Resolve destination memory addresses using bridge.dna
    ptrs = resolve_point_cloud_ptrs(target_data, expected_count=pt_count)
    pos_ptr = ptrs.get("pos_ptr")
    bx_ptr = ptrs.get("block_x_ptr")
    by_ptr = ptrs.get("block_y_ptr")
    bz_ptr = ptrs.get("block_z_ptr")
    st_ptr = ptrs.get("state_idx_ptr")
    bm_ptr = ptrs.get("biome_idx_ptr")

    if not (pos_ptr and bx_ptr and by_ptr and bz_ptr and st_ptr and bm_ptr):
        return False

    light_ptr = ptrs.get("light_ptr")

    try:
        blender_dna.copy_f32(
            _byte_view(cloud_data.positions_memoryview()),
            pos_ptr,
            pt_count * 3,
            max_bytes=pt_count * 12,
        )
        blender_dna.copy_i32(
            _byte_view(cloud_data.block_x_memoryview()),
            bx_ptr,
            pt_count,
            max_bytes=pt_count * 4,
        )
        blender_dna.copy_i32(
            _byte_view(cloud_data.block_y_memoryview()),
            by_ptr,
            pt_count,
            max_bytes=pt_count * 4,
        )
        blender_dna.copy_i32(
            _byte_view(cloud_data.block_z_memoryview()),
            bz_ptr,
            pt_count,
            max_bytes=pt_count * 4,
        )
        blender_dna.copy_i32(
            _byte_view(cloud_data.state_indices_memoryview()),
            st_ptr,
            pt_count,
            max_bytes=pt_count * 4,
        )
        blender_dna.copy_i32(
            _byte_view(cloud_data.biome_indices_memoryview()),
            bm_ptr,
            pt_count,
            max_bytes=pt_count * 4,
        )
        if light_ptr:
            blender_dna.copy_u8(
                _byte_view(cloud_data.light_levels_memoryview()),
                light_ptr,
                pt_count,
                max_bytes=pt_count,
            )

        state_palette = cloud_data.get_state_palette()
        biome_palette = cloud_data.get_biome_palette()
        target_data[PROP_BLOCK_PALETTE] = state_palette
        target_data[PROP_BIOME_PALETTE] = biome_palette
        if obj is not None:
            obj[PROP_BLOCK_PALETTE] = state_palette
            obj[PROP_BIOME_PALETTE] = biome_palette
        return True
    except Exception as e:
        logger.debug("DNA direct copy point cloud failed: %s", e)
        return False

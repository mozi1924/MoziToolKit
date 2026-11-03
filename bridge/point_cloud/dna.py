"""
Zero-Copy Direct Memory DNA Ingestion Channel for Voxel Point Cloud.

Bypasses Python array allocation and copies coordinates and palette indices directly
into Blender CustomData memory layers.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..dna import (
    is_dna_available,
    is_dna_enabled,
    resolve_attribute_ptr,
    resolve_point_cloud_ptrs,
)
from ..engine import get_libmtk_dna
from .constants import (
    ATTR_BLOCK_ENTITY_IDX,
    PROP_BIOME_PALETTE,
    PROP_BLOCK_ENTITY_PALETTE,
    PROP_BLOCK_PALETTE,
)

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
    if blender_dna is None or not is_dna_enabled():
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

    # Check if point cloud contains biome data
    has_biomes = False
    biome_mv = None
    if hasattr(cloud_data, "biome_indices_memoryview"):
        try:
            biome_mv = cloud_data.biome_indices_memoryview()
            if len(biome_mv) == pt_count:
                has_biomes = True
        except Exception:
            pass

    # Core spatial coordinates and blockstate indices are required.
    # Biome pointer is only required when the point cloud actually provides biome data.
    if not (pos_ptr and bx_ptr and by_ptr and bz_ptr and st_ptr):
        return False
    if has_biomes and not bm_ptr:
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
        if has_biomes and bm_ptr and biome_mv is not None:
            blender_dna.copy_i32(
                _byte_view(biome_mv),
                bm_ptr,
                pt_count,
                max_bytes=pt_count * 4,
            )
        if light_ptr and hasattr(cloud_data, "light_levels_memoryview"):
            light_mv = cloud_data.light_levels_memoryview()
            if len(light_mv) == pt_count:
                blender_dna.copy_u8(
                    _byte_view(light_mv),
                    light_ptr,
                    pt_count,
                    max_bytes=pt_count,
                )

        state_palette = cloud_data.get_state_palette()
        if target_data.get(PROP_BLOCK_PALETTE) != state_palette:
            target_data[PROP_BLOCK_PALETTE] = state_palette

        if has_biomes:
            biome_palette = cloud_data.get_biome_palette()
            if target_data.get(PROP_BIOME_PALETTE) != biome_palette:
                target_data[PROP_BIOME_PALETTE] = biome_palette

        # Block entities palette & indices
        has_entities = False
        if hasattr(cloud_data, "has_entities"):
            has_entities = bool(cloud_data.has_entities())
        elif hasattr(cloud_data, "get_entity_palette"):
            has_entities = bool(cloud_data.get_entity_palette())

        if has_entities and hasattr(cloud_data, "entity_indices_memoryview"):
            ent_palette = cloud_data.get_entity_palette()
            if target_data.get(PROP_BLOCK_ENTITY_PALETTE) != ent_palette:
                target_data[PROP_BLOCK_ENTITY_PALETTE] = ent_palette
            ent_ptr = ptrs.get("entity_idx_ptr")
            if not ent_ptr:
                attr_ent = target_data.attributes.get(ATTR_BLOCK_ENTITY_IDX)
                if attr_ent is not None:
                    ent_ptr = resolve_attribute_ptr(attr_ent, min_elements=pt_count, required_align=4)

            if ent_ptr:
                blender_dna.copy_i32(
                    _byte_view(cloud_data.entity_indices_memoryview()),
                    ent_ptr,
                    pt_count,
                    max_bytes=pt_count * 4,
                )
            else:
                attr_ent = target_data.attributes.get(ATTR_BLOCK_ENTITY_IDX)
                if attr_ent is not None:
                    import numpy as np
                    ent_indices = np.frombuffer(cloud_data.entity_indices_memoryview(), dtype=np.int32)
                    attr_ent.data.foreach_set("value", np.ascontiguousarray(ent_indices))

        return True
    except Exception as e:
        logger.debug("DNA direct copy point cloud failed: %s", e)
        return False

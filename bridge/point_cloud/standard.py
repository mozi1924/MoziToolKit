"""
Standard Safe Python API Voxel Point Cloud Ingestion Channel.

Uses official Blender Python APIs (bpy.types.Attribute, foreach_set, NumPy buffers)
with zero pointer operations or ctypes, ensuring rock-solid stability across versions.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from .constants import (
    ATTR_BLOCK_X,
    ATTR_BLOCK_Y,
    ATTR_BLOCK_Z,
    ATTR_BIOME_IDX,
    ATTR_BLOCK_STATE_IDX,
    PROP_BIOME_PALETTE,
    PROP_BLOCK_PALETTE,
)

logger = logging.getLogger("MoziToolKit.Bridge.PointCloud.Standard")


def inject_point_cloud_standard(
    target_data: Any,
    cloud_data: Any,
    pt_count: int,
    obj: Optional[Any] = None,
    attr_x: Optional[Any] = None,
    attr_y: Optional[Any] = None,
    attr_z: Optional[Any] = None,
    attr_state_idx: Optional[Any] = None,
    attr_biome_idx: Optional[Any] = None,
) -> bool:
    """Injects point cloud attributes using standard Blender Python foreach_set operations."""
    pos_attr = target_data.attributes.get("position") if hasattr(target_data, "attributes") else None

    # 1. Positions injection
    pos_injected = False
    if hasattr(cloud_data, "positions_memoryview"):
        try:
            pos_mv = cloud_data.positions_memoryview()
            pos_arr = np.frombuffer(pos_mv, dtype=np.float32)
            if pos_attr is not None and len(pos_attr.data) == pt_count:
                pos_attr.data.foreach_set("vector", pos_arr)
            elif hasattr(target_data, "vertices"):
                target_data.vertices.foreach_set("co", pos_arr)
            elif hasattr(target_data, "points"):
                target_data.points.foreach_set("co", pos_arr)
            pos_injected = True
        except Exception as e:
            logger.debug("positions_memoryview injection fallback: %s", e)

    if not pos_injected and hasattr(cloud_data, "positions"):
        try:
            pos_arr = np.ascontiguousarray(cloud_data.positions, dtype=np.float32)
            if pos_attr is not None and len(pos_attr.data) == pt_count:
                pos_attr.data.foreach_set("vector", pos_arr)
            elif hasattr(target_data, "vertices"):
                target_data.vertices.foreach_set("co", pos_arr)
            elif hasattr(target_data, "points"):
                target_data.points.foreach_set("co", pos_arr)
        except Exception as e:
            logger.debug("Standard positions injection error: %s", e)

    # 2. Block X, Y, Z integer coordinates
    for name, mv_fn, fallback_attr, target_attr in [
        (ATTR_BLOCK_X, "block_x_memoryview", "block_x", attr_x),
        (ATTR_BLOCK_Y, "block_y_memoryview", "block_y", attr_y),
        (ATTR_BLOCK_Z, "block_z_memoryview", "block_z", attr_z),
    ]:
        if target_attr is not None:
            injected = False
            if hasattr(cloud_data, mv_fn):
                try:
                    mv = getattr(cloud_data, mv_fn)()
                    if hasattr(mv, "cast") and mv.format == "B":
                        mv = mv.cast("i")
                    target_attr.data.foreach_set("value", mv)
                    injected = True
                except Exception:
                    pass
            if not injected and hasattr(cloud_data, fallback_attr):
                try:
                    vals = getattr(cloud_data, fallback_attr)
                    arr = np.ascontiguousarray(vals, dtype=np.int32)
                    target_attr.data.foreach_set("value", arr)
                except Exception as e:
                    logger.debug("Standard %s injection error: %s", name, e)

    # 3. Block states palette & indices
    if attr_state_idx is not None:
        try:
            if hasattr(cloud_data, "build_state_palette_indices"):
                palette, indices = cloud_data.build_state_palette_indices()
                attr_state_idx.data.foreach_set("value", np.ascontiguousarray(indices, dtype=np.int32))
                target_data[PROP_BLOCK_PALETTE] = palette
                if obj is not None:
                    obj[PROP_BLOCK_PALETTE] = palette
            else:
                states = (
                    cloud_data.get_block_states()
                    if hasattr(cloud_data, "get_block_states")
                    else getattr(cloud_data, "block_states", [])
                )
                if len(states) == pt_count:
                    palette = list(dict.fromkeys(states))
                    state_map = {st: idx for idx, st in enumerate(palette)}
                    idx_arr = np.fromiter((state_map[st] for st in states), dtype=np.int32, count=pt_count)
                    attr_state_idx.data.foreach_set("value", idx_arr)
                    target_data[PROP_BLOCK_PALETTE] = palette
                    if obj is not None:
                        obj[PROP_BLOCK_PALETTE] = palette
        except Exception as e:
            logger.debug("Standard block state palette injection error: %s", e)

    # 4. Biome palette & indices
    if attr_biome_idx is not None:
        try:
            if hasattr(cloud_data, "build_biome_palette_indices"):
                b_palette, b_indices = cloud_data.build_biome_palette_indices()
                attr_biome_idx.data.foreach_set("value", np.ascontiguousarray(b_indices, dtype=np.int32))
                target_data[PROP_BIOME_PALETTE] = b_palette
                if obj is not None:
                    obj[PROP_BIOME_PALETTE] = b_palette
            else:
                biomes = (
                    cloud_data.get_biomes()
                    if hasattr(cloud_data, "get_biomes")
                    else getattr(cloud_data, "biomes", [])
                )
                if len(biomes) == pt_count:
                    b_palette = list(dict.fromkeys(biomes))
                    b_map = {bm: idx for idx, bm in enumerate(b_palette)}
                    b_idx_arr = np.fromiter((b_map[bm] for bm in biomes), dtype=np.int32, count=pt_count)
                    attr_biome_idx.data.foreach_set("value", b_idx_arr)
                    target_data[PROP_BIOME_PALETTE] = b_palette
                    if obj is not None:
                        obj[PROP_BIOME_PALETTE] = b_palette
        except Exception as e:
            logger.debug("Standard biome palette injection error: %s", e)

    return True

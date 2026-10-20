"""
Standard Safe Python API Voxel Point Cloud Ingestion Channel.

Uses official Blender Python APIs (bpy.types.Attribute, foreach_set, NumPy buffers)
with zero pointer operations or ctypes, ensuring rock-solid stability across versions.
"""

from __future__ import annotations

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
    pos_arr = np.frombuffer(cloud_data.positions_memoryview(), dtype=np.float32)
    if pos_attr is not None and len(pos_attr.data) == pt_count:
        pos_attr.data.foreach_set("vector", pos_arr)
    elif hasattr(target_data, "vertices"):
        target_data.vertices.foreach_set("co", pos_arr)
    elif hasattr(target_data, "points"):
        target_data.points.foreach_set("co", pos_arr)

    # 2. Block X, Y, Z integer coordinates
    for mv_fn, target_attr in (
        ("block_x_memoryview", attr_x),
        ("block_y_memoryview", attr_y),
        ("block_z_memoryview", attr_z),
    ):
        if target_attr is None:
            continue
        mv = getattr(cloud_data, mv_fn)()
        if hasattr(mv, "cast") and mv.format == "B":
            mv = mv.cast("i")
        target_attr.data.foreach_set("value", mv)

    # 3. Block states palette & indices
    if attr_state_idx is not None:
        palette, indices = cloud_data.build_state_palette_indices()
        attr_state_idx.data.foreach_set(
            "value", np.ascontiguousarray(indices, dtype=np.int32)
        )
        target_data[PROP_BLOCK_PALETTE] = palette
        if obj is not None:
            obj[PROP_BLOCK_PALETTE] = palette

    # 4. Biome palette & indices
    if attr_biome_idx is not None:
        b_palette, b_indices = cloud_data.build_biome_palette_indices()
        attr_biome_idx.data.foreach_set(
            "value", np.ascontiguousarray(b_indices, dtype=np.int32)
        )
        target_data[PROP_BIOME_PALETTE] = b_palette
        if obj is not None:
            obj[PROP_BIOME_PALETTE] = b_palette

    return True

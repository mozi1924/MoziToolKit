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
    PROP_BLOCK_ENTITY_PALETTE,
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
    attr_entity_idx: Optional[Any] = None,
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
        palette = cloud_data.get_state_palette()
        indices = np.frombuffer(cloud_data.state_indices_memoryview(), dtype=np.int32)
        attr_state_idx.data.foreach_set("value", np.ascontiguousarray(indices))
        target_data[PROP_BLOCK_PALETTE] = palette
        if obj is not None:
            obj[PROP_BLOCK_PALETTE] = palette

    # 4. Biome palette & indices
    if attr_biome_idx is not None:
        b_palette = cloud_data.get_biome_palette()
        b_indices = np.frombuffer(cloud_data.biome_indices_memoryview(), dtype=np.int32)
        attr_biome_idx.data.foreach_set("value", np.ascontiguousarray(b_indices))
        target_data[PROP_BIOME_PALETTE] = b_palette
        if obj is not None:
            obj[PROP_BIOME_PALETTE] = b_palette

    # 5. Block entities palette & indices
    has_entities = False
    if hasattr(cloud_data, "has_entities"):
        has_entities = bool(cloud_data.has_entities())
    elif hasattr(cloud_data, "get_entity_palette"):
        has_entities = bool(cloud_data.get_entity_palette())

    if has_entities and attr_entity_idx is not None and hasattr(cloud_data, "entity_indices_memoryview"):
        ent_palette = cloud_data.get_entity_palette()
        ent_indices = np.frombuffer(cloud_data.entity_indices_memoryview(), dtype=np.int32)
        attr_entity_idx.data.foreach_set("value", np.ascontiguousarray(ent_indices))
        target_data[PROP_BLOCK_ENTITY_PALETTE] = ent_palette
        if obj is not None:
            obj[PROP_BLOCK_ENTITY_PALETTE] = ent_palette
    elif not has_entities:
        if PROP_BLOCK_ENTITY_PALETTE in target_data:
            try:
                del target_data[PROP_BLOCK_ENTITY_PALETTE]
            except Exception:
                pass
        if obj is not None and PROP_BLOCK_ENTITY_PALETTE in obj:
            try:
                del obj[PROP_BLOCK_ENTITY_PALETTE]
            except Exception:
                pass

    return True

"""
Extraction of Voxel Point Cloud from Blender Mesh into Rust VoxelPointCloud.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from ..engine import require_libmtk
from .constants import (
    ATTR_BIOME_IDX,
    ATTR_BLOCK_STATE_IDX,
    ATTR_BLOCK_X,
    ATTR_BLOCK_Y,
    ATTR_BLOCK_Z,
    PROP_BIOME_PALETTE,
    PROP_BLOCK_PALETTE,
)

logger = logging.getLogger("MoziToolKit.Bridge.PointCloud.Extract")


def extract_voxel_point_cloud(cloud_obj_or_mesh: Any) -> Optional[Any]:
    """
    Extracts a live Rust VoxelPointCloud from a Blender Point Mesh.
    Captures user modifications (deleted vertices, carved cavities) with zero overhead.
    """
    mtk = require_libmtk("extract_voxel_point_cloud")

    if hasattr(cloud_obj_or_mesh, "data") and getattr(cloud_obj_or_mesh, "type", "") == "MESH":
        obj = cloud_obj_or_mesh
        mesh = cloud_obj_or_mesh.data
    else:
        obj = None
        mesh = cloud_obj_or_mesh

    v_count = len(getattr(mesh, "vertices", []))
    if v_count == 0:
        return mtk.VoxelPointCloud.new() if hasattr(mtk, "VoxelPointCloud") else None

    if not hasattr(mesh, "attributes"):
        return None

    attr_x = mesh.attributes.get(ATTR_BLOCK_X)
    attr_y = mesh.attributes.get(ATTR_BLOCK_Y)
    attr_z = mesh.attributes.get(ATTR_BLOCK_Z)
    attr_state_idx = mesh.attributes.get(ATTR_BLOCK_STATE_IDX)

    palette = None
    if obj is not None and PROP_BLOCK_PALETTE in obj:
        try:
            palette = list(obj[PROP_BLOCK_PALETTE])
        except Exception:
            pass
    if palette is None and PROP_BLOCK_PALETTE in mesh:
        try:
            palette = list(mesh[PROP_BLOCK_PALETTE])
        except Exception:
            pass

    if not (attr_x and attr_y and attr_z and attr_state_idx is not None and palette is not None):
        logger.warning(
            "Mesh lacks required voxel point cloud attributes (%s, %s, %s, %s + palette)",
            ATTR_BLOCK_X, ATTR_BLOCK_Y, ATTR_BLOCK_Z, ATTR_BLOCK_STATE_IDX,
        )
        return None
    if len(attr_state_idx.data) != v_count:
        logger.warning("Voxel point cloud state index attribute length does not match vertices")
        return None

    # Extract 3D positions
    pos_arr = np.empty(v_count * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", pos_arr)

    # Extract integer block coordinates
    bx_arr = np.empty(v_count, dtype=np.int32)
    by_arr = np.empty(v_count, dtype=np.int32)
    bz_arr = np.empty(v_count, dtype=np.int32)
    attr_x.data.foreach_get("value", bx_arr)
    attr_y.data.foreach_get("value", by_arr)
    attr_z.data.foreach_get("value", bz_arr)

    # Extract biomes palette
    attr_biome_idx = mesh.attributes.get(ATTR_BIOME_IDX)
    b_palette = None
    if obj is not None and PROP_BIOME_PALETTE in obj:
        try:
            b_palette = list(obj[PROP_BIOME_PALETTE])
        except Exception:
            pass
    if b_palette is None and PROP_BIOME_PALETTE in mesh:
        try:
            b_palette = list(mesh[PROP_BIOME_PALETTE])
        except Exception:
            pass

    # Extract bounds if stored on object
    bounds = None
    if obj is not None and "mtk_bounds" in obj:
        try:
            raw_b = obj["mtk_bounds"]
            if len(raw_b) == 6:
                bounds = [int(x) for x in raw_b]
        except Exception:
            pass

    # Palette-indexed ingestion: never materialize per-point Python strings.
    idx_arr = np.empty(v_count, dtype=np.int32)
    attr_state_idx.data.foreach_get("value", idx_arr)

    b_idx_arr = None
    if attr_biome_idx is not None and b_palette is not None and len(attr_biome_idx.data) == v_count:
        b_idx_arr = np.empty(v_count, dtype=np.int32)
        attr_biome_idx.data.foreach_get("value", b_idx_arr)

    return mtk.VoxelPointCloud.from_indexed_arrays(
        pos_arr,
        bx_arr,
        by_arr,
        bz_arr,
        idx_arr,
        palette,
        b_idx_arr,
        b_palette,
        None,
        bounds,
    )

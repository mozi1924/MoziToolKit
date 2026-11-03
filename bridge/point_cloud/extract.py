"""
Extraction of Voxel Point Cloud from Blender Mesh into Rust VoxelPointCloud.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from ..dna import is_dna_available, is_dna_enabled, resolve_point_cloud_ptrs
from ..engine import get_libmtk_dna, require_libmtk
from .constants import (
    ATTR_BIOME_IDX,
    ATTR_BLOCK_ENTITY_IDX,
    ATTR_BLOCK_STATE_IDX,
    ATTR_BLOCK_X,
    ATTR_BLOCK_Y,
    ATTR_BLOCK_Z,
    PROP_BIOME_PALETTE,
    PROP_BLOCK_ENTITY_PALETTE,
    PROP_BLOCK_PALETTE,
)

logger = logging.getLogger("MoziToolKit.Bridge.PointCloud.Extract")


def extract_voxel_point_cloud_dna(cloud_obj_or_mesh: Any) -> Optional[Any]:
    """
    Extracts a live Rust VoxelPointCloud using zero-copy DNA direct memory reads.
    Returns None if pointers are unavailable, triggering seamless safe-path fallback.
    """
    blender_dna = get_libmtk_dna()
    if blender_dna is None or not is_dna_enabled():
        return None

    mtk = require_libmtk("extract_voxel_point_cloud_dna")

    if hasattr(cloud_obj_or_mesh, "data") and getattr(cloud_obj_or_mesh, "type", "") in ("MESH", "POINTCLOUD"):
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

    palette = None
    if PROP_BLOCK_PALETTE in mesh:
        try:
            palette = list(mesh[PROP_BLOCK_PALETTE])
        except Exception:
            pass
    elif obj is not None and PROP_BLOCK_PALETTE in obj:
        try:
            palette = list(obj[PROP_BLOCK_PALETTE])
        except Exception:
            pass

    if palette is None:
        return None

    ptrs = resolve_point_cloud_ptrs(mesh, expected_count=v_count)
    pos_ptr = ptrs.get("pos_ptr")
    bx_ptr = ptrs.get("block_x_ptr")
    by_ptr = ptrs.get("block_y_ptr")
    bz_ptr = ptrs.get("block_z_ptr")
    state_idx_ptr = ptrs.get("state_idx_ptr")

    if not (pos_ptr and bx_ptr and by_ptr and bz_ptr and state_idx_ptr):
        return None

    # Biome palette (mesh-first authoritative lookup)
    b_palette = None
    if PROP_BIOME_PALETTE in mesh:
        try:
            b_palette = list(mesh[PROP_BIOME_PALETTE])
        except Exception:
            pass
    elif obj is not None and PROP_BIOME_PALETTE in obj:
        try:
            b_palette = list(obj[PROP_BIOME_PALETTE])
        except Exception:
            pass

    # Bounds
    bounds = None
    if obj is not None and "mtk_bounds" in obj:
        try:
            raw_b = obj["mtk_bounds"]
            if len(raw_b) == 6:
                bounds = [int(x) for x in raw_b]
        except Exception:
            pass

    # Block entity palette (mesh-first authoritative lookup)
    ent_palette = None
    if PROP_BLOCK_ENTITY_PALETTE in mesh:
        try:
            ent_palette = list(mesh[PROP_BLOCK_ENTITY_PALETTE])
        except Exception:
            pass
    elif obj is not None and PROP_BLOCK_ENTITY_PALETTE in obj:
        try:
            ent_palette = list(obj[PROP_BLOCK_ENTITY_PALETTE])
        except Exception:
            pass

    try:
        pos_mv = blender_dna.as_memoryview_f32(pos_ptr, v_count * 3)
        bx_mv = blender_dna.as_memoryview_i32(bx_ptr, v_count)
        by_mv = blender_dna.as_memoryview_i32(by_ptr, v_count)
        bz_mv = blender_dna.as_memoryview_i32(bz_ptr, v_count)
        state_idx_mv = blender_dna.as_memoryview_i32(state_idx_ptr, v_count)

        biome_idx_ptr = ptrs.get("biome_idx_ptr")
        b_idx_mv = None
        if biome_idx_ptr and b_palette:
            b_idx_mv = blender_dna.as_memoryview_i32(biome_idx_ptr, v_count)

        entity_idx_ptr = ptrs.get("entity_idx_ptr")
        ent_idx_mv = None
        if entity_idx_ptr and ent_palette:
            ent_idx_mv = blender_dna.as_memoryview_i32(entity_idx_ptr, v_count)

        return mtk.VoxelPointCloud.from_indexed_arrays(
            pos_mv,
            bx_mv,
            by_mv,
            bz_mv,
            state_idx_mv,
            palette,
            b_idx_mv,
            b_palette,
            None,
            bounds,
            ent_idx_mv,
            ent_palette,
        )
    except Exception as e:
        logger.debug("extract_voxel_point_cloud_dna failed, falling back: %s", e)
        return None


def extract_voxel_point_cloud(
    cloud_obj_or_mesh: Any,
    use_dna: bool = True,
) -> Optional[Any]:
    """
    Extracts a live Rust VoxelPointCloud from a Blender Point Mesh.
    Captures user modifications (deleted vertices, carved cavities) with zero overhead.

    Dual-channel architecture: prioritizes DNA memoryview reads, seamlessly falling
    back to standard foreach_get when DNA is disabled or pointers are invalid.
    """
    if use_dna and is_dna_enabled():
        dna_cloud = extract_voxel_point_cloud_dna(cloud_obj_or_mesh)
        if dna_cloud is not None:
            return dna_cloud

    mtk = require_libmtk("extract_voxel_point_cloud")

    if hasattr(cloud_obj_or_mesh, "data") and getattr(cloud_obj_or_mesh, "type", "") in ("MESH", "POINTCLOUD"):
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
    if PROP_BLOCK_PALETTE in mesh:
        try:
            palette = list(mesh[PROP_BLOCK_PALETTE])
        except Exception:
            pass
    elif obj is not None and PROP_BLOCK_PALETTE in obj:
        try:
            palette = list(obj[PROP_BLOCK_PALETTE])
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

    # Extract biomes palette (mesh-first authoritative lookup)
    attr_biome_idx = mesh.attributes.get(ATTR_BIOME_IDX)
    b_palette = None
    if PROP_BIOME_PALETTE in mesh:
        try:
            b_palette = list(mesh[PROP_BIOME_PALETTE])
        except Exception:
            pass
    elif obj is not None and PROP_BIOME_PALETTE in obj:
        try:
            b_palette = list(obj[PROP_BIOME_PALETTE])
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

    # Extract block entity palette & indices if present (mesh-first authoritative lookup)
    attr_entity_idx = mesh.attributes.get(ATTR_BLOCK_ENTITY_IDX)
    ent_palette = None
    if PROP_BLOCK_ENTITY_PALETTE in mesh:
        try:
            ent_palette = list(mesh[PROP_BLOCK_ENTITY_PALETTE])
        except Exception:
            pass
    elif obj is not None and PROP_BLOCK_ENTITY_PALETTE in obj:
        try:
            ent_palette = list(obj[PROP_BLOCK_ENTITY_PALETTE])
        except Exception:
            pass

    ent_idx_arr = None
    if attr_entity_idx is not None and ent_palette and len(attr_entity_idx.data) == v_count:
        ent_idx_arr = np.empty(v_count, dtype=np.int32)
        attr_entity_idx.data.foreach_get("value", ent_idx_arr)

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
        ent_idx_arr,
        ent_palette,
    )

"""
High-Throughput Zero-Copy Blender DNA Direct Pointer Ingestion Channel.

Resolves CustomData memory pointers through bridge.dna and writes directly
into host memory using libmtk_py.unstable.blender_dna.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from ..dna import (
    is_dna_available,
    resolve_colors_ptr,
    resolve_corner_verts_ptr,
    resolve_loop_uvs_ptr,
    resolve_materials_ptr,
    resolve_positions_ptr,
)
from ..engine import get_libmtk_dna

logger = logging.getLogger("MoziToolKit.Bridge.Mesh.DNA")


def inject_topology_dna(
    mesh: Any,
    mesh_data: Any,
    v_count: int,
    is_quad: bool,
    total_indices: int,
    shade_smooth: bool = False,
) -> bool:
    """
    Directly allocates and injects topology arrays via hardware-level raw memory writes.
    Returns True if successfully injected, or False if direct copy failed.
    """
    blender_dna = get_libmtk_dna()
    if blender_dna is None or not is_dna_available():
        return False

    if not (hasattr(mesh.vertices, "add") and hasattr(mesh.loops, "add") and hasattr(mesh.polygons, "add")):
        return False

    mesh.clear_geometry()
    mesh.vertices.add(v_count)

    # 1. Direct copy vertex positions
    pos_ptr = resolve_positions_ptr(mesh, expected_count=v_count)
    if pos_ptr is None:
        return False

    try:
        if hasattr(blender_dna, "copy_positions_to_ptr"):
            blender_dna.copy_positions_to_ptr(mesh_data, pos_ptr, max_bytes=v_count * 12)
        elif hasattr(mesh_data, "direct_copy_positions_to_ptr"):
            mesh_data.direct_copy_positions_to_ptr(pos_ptr, max_bytes=v_count * 12)
        else:
            return False
    except Exception as e:
        logger.debug("DNA direct position copy failed: %s", e)
        return False

    # 2. Direct copy loops & corner vertices
    poly_count = (total_indices // 6) if is_quad else (total_indices // 3)
    stride = 4 if is_quad else 3
    total_loops = poly_count * stride
    mesh.loops.add(total_loops)

    cvert_ptr = resolve_corner_verts_ptr(mesh, expected_count=total_loops)
    if cvert_ptr is None:
        return False

    try:
        if is_quad:
            if hasattr(blender_dna, "copy_quad_indices_to_ptr"):
                blender_dna.copy_quad_indices_to_ptr(mesh_data, cvert_ptr, max_bytes=total_loops * 4)
            elif hasattr(mesh_data, "direct_copy_quad_indices_to_ptr"):
                mesh_data.direct_copy_quad_indices_to_ptr(cvert_ptr, max_bytes=total_loops * 4)
            else:
                return False
        else:
            if hasattr(blender_dna, "copy_indices_to_ptr"):
                blender_dna.copy_indices_to_ptr(mesh_data, cvert_ptr, max_bytes=total_loops * 4)
            elif hasattr(mesh_data, "direct_copy_indices_to_ptr"):
                mesh_data.direct_copy_indices_to_ptr(cvert_ptr, max_bytes=total_loops * 4)
            else:
                return False
    except Exception as e:
        logger.debug("DNA direct corner vert copy failed: %s", e)
        return False

    # 3. Direct setup polygons
    mesh.polygons.add(poly_count)
    if not shade_smooth:
        mesh.polygons.foreach_set("use_smooth", b"\x00" * poly_count)

    mesh.polygons.foreach_set("loop_start", np.arange(0, total_loops, stride, dtype=np.int32))
    mesh.polygons.foreach_set("loop_total", np.full(poly_count, stride, dtype=np.int32))
    return True


def inject_vertex_positions_dna(mesh: Any, mesh_data: Any) -> bool:
    """Injects vertex positions via direct memory pointer write."""
    blender_dna = get_libmtk_dna()
    if blender_dna is None or not is_dna_available():
        return False

    v_count = getattr(mesh_data, "vertex_count", 0)
    if v_count == 0:
        return True

    pos_ptr = resolve_positions_ptr(mesh, expected_count=v_count)
    if pos_ptr is None:
        return False

    try:
        if hasattr(blender_dna, "copy_positions_to_ptr"):
            blender_dna.copy_positions_to_ptr(mesh_data, pos_ptr, max_bytes=v_count * 12)
            return True
        elif hasattr(mesh_data, "direct_copy_positions_to_ptr"):
            mesh_data.direct_copy_positions_to_ptr(pos_ptr, max_bytes=v_count * 12)
            return True
    except Exception as e:
        logger.debug("DNA direct copy positions failed: %s", e)

    return False


def inject_vertex_normals_dna(mesh: Any, mesh_data: Any) -> bool:
    """Injects vertex normals via direct memory pointer write."""
    blender_dna = get_libmtk_dna()
    if blender_dna is None or not is_dna_available():
        return False

    v_count = getattr(mesh_data, "vertex_count", 0)
    if v_count == 0 or not hasattr(mesh, "attributes"):
        return False

    norm_attr = mesh.attributes.get("normal")
    if norm_attr is None or len(norm_attr.data) != v_count:
        return False

    p0 = getattr(norm_attr.data[0], "as_pointer", None)
    if p0 is None:
        return False

    try:
        norm_ptr = p0()
        if norm_ptr == 0:
            return False
        if hasattr(blender_dna, "copy_normals_to_ptr"):
            blender_dna.copy_normals_to_ptr(mesh_data, norm_ptr, max_bytes=v_count * 12)
            return True
        elif hasattr(mesh_data, "direct_copy_normals_to_ptr"):
            mesh_data.direct_copy_normals_to_ptr(norm_ptr, max_bytes=v_count * 12)
            return True
    except Exception as e:
        logger.debug("DNA direct copy normals failed: %s", e)

    return False


def inject_uvs_dna(mesh: Any, mesh_data: Any, uv_layer_name: Optional[str] = None) -> bool:
    """Injects loop UVs via direct memory pointer write."""
    blender_dna = get_libmtk_dna()
    if blender_dna is None or not is_dna_available():
        return False

    num_loops = len(getattr(mesh, "loops", []))
    if num_loops == 0:
        return False

    uv_ptr = resolve_loop_uvs_ptr(mesh, uv_name=uv_layer_name, expected_count=num_loops)
    if uv_ptr is None:
        return False

    try:
        if hasattr(blender_dna, "copy_loop_uvs_to_ptr"):
            blender_dna.copy_loop_uvs_to_ptr(mesh_data, uv_ptr, max_bytes=num_loops * 8)
            return True
        elif hasattr(mesh_data, "direct_copy_loop_uvs_to_ptr"):
            mesh_data.direct_copy_loop_uvs_to_ptr(uv_ptr, max_bytes=num_loops * 8)
            return True
    except Exception as e:
        logger.debug("DNA direct copy UVs failed: %s", e)

    return False


def inject_face_materials_dna(mesh: Any, mesh_data: Any) -> bool:
    """
    Polygon material indices are intentionally handled in Phase 2 standard API
    (inject_face_materials_standard) for 100% crash immunity and material slot binding.
    """
    return False


def inject_color_attributes_dna(mesh: Any, mesh_data: Any) -> bool:
    """Injects vertex/loop color attributes via direct memory pointer write."""
    blender_dna = get_libmtk_dna()
    if blender_dna is None or not is_dna_available():
        return False

    col_ptr = resolve_colors_ptr(mesh)
    if col_ptr is None:
        return False

    try:
        col_mv = mesh_data.colors_memoryview() if hasattr(mesh_data, "colors_memoryview") else None
        if col_mv is None:
            return False

        if hasattr(blender_dna, "copy_colors_to_ptr"):
            blender_dna.copy_colors_to_ptr(mesh_data, col_ptr, max_bytes=len(col_mv))
            return True
        elif hasattr(mesh_data, "direct_copy_colors_to_ptr"):
            mesh_data.direct_copy_colors_to_ptr(col_ptr, max_bytes=len(col_mv))
            return True
    except Exception as e:
        logger.debug("DNA direct copy colors failed: %s", e)

    return False

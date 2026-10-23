"""
High-Throughput Zero-Copy Blender DNA Direct Pointer Ingestion Channel.

Resolves CustomData memory pointers through bridge.dna and writes directly
into host memory using the standalone `libmtk_blender_dna` adapter.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from ..dna import (
    is_dna_available,
    resolve_attribute_ptr,
    resolve_colors_ptr,
    resolve_corner_verts_ptr,
    resolve_loop_uvs_ptr,
    resolve_positions_ptr,
)
from ..engine import get_libmtk_dna
from .standard import clean_zombie_attributes

logger = logging.getLogger("MoziToolKit.Bridge.Mesh.DNA")


def _byte_view(mv: Any) -> Any:
    """Normalizes a typed/raw core memoryview or array without unnecessary re-casting."""
    if isinstance(mv, memoryview):
        return mv
    return memoryview(mv)


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

    poly_count = (total_indices // 6) if is_quad else (total_indices // 3)
    stride = 4 if is_quad else 3
    total_loops = poly_count * stride

    clean_zombie_attributes(mesh)
    mesh.clear_geometry()
    clean_zombie_attributes(mesh)

    # Atomic allocation of geometry counts
    mesh.vertices.add(v_count)
    mesh.loops.add(total_loops)
    mesh.polygons.add(poly_count)

    # 1. Direct copy vertex positions (DNA fast path, fallback to foreach_set)
    pos_ptr = resolve_positions_ptr(mesh, expected_count=v_count)
    pos_copied = False
    if pos_ptr is not None:
        try:
            blender_dna.copy_f32(
                _byte_view(mesh_data.positions_memoryview()),
                pos_ptr,
                v_count * 3,
                max_bytes=v_count * 12,
            )
            pos_copied = True
        except Exception as e:
            logger.debug("DNA direct position copy failed: %s", e)

    if not pos_copied:
        pos_mv = mesh_data.positions_memoryview()
        if hasattr(pos_mv, "cast") and pos_mv.format == "B":
            pos_mv = pos_mv.cast("f")
        mesh.vertices.foreach_set("co", pos_mv)

    # 2. Direct copy loops & corner vertices (DNA fast path, fallback to foreach_set)
    cvert_ptr = resolve_corner_verts_ptr(mesh, expected_count=total_loops)
    cvert_copied = False
    if cvert_ptr is not None:
        try:
            src = mesh_data.quad_indices_memoryview() if is_quad else mesh_data.indices_memoryview()
            if src is not None:
                blender_dna.copy_u32(
                    _byte_view(src), cvert_ptr, total_loops, max_bytes=total_loops * 4
                )
                cvert_copied = True
        except Exception as e:
            logger.debug("DNA direct corner vert copy failed: %s", e)

    if not cvert_copied:
        src = mesh_data.quad_indices_memoryview() if is_quad else mesh_data.indices_memoryview()
        if hasattr(src, "cast") and src.format == "B":
            src = src.cast("i")
        mesh.loops.foreach_set("vertex_index", src)

    # 3. Direct setup polygons
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
        blender_dna.copy_f32(
            _byte_view(mesh_data.positions_memoryview()),
            pos_ptr,
            v_count * 3,
            max_bytes=v_count * 12,
        )
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
        blender_dna.copy_f32(
            _byte_view(mesh_data.normals_memoryview()),
            norm_ptr,
            v_count * 3,
            max_bytes=v_count * 12,
        )
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

    target_name = uv_layer_name
    if not target_name:
        active_layer = getattr(mesh.uv_layers, "active", None) if hasattr(mesh, "uv_layers") else None
        target_name = active_layer.name if active_layer else (mesh.uv_layers[0].name if hasattr(mesh, "uv_layers") and len(mesh.uv_layers) > 0 else "UVMap")

    uv_attr = mesh.attributes.get(target_name) if hasattr(mesh, "attributes") else None
    if uv_attr is not None and len(uv_attr.data) != num_loops:
        try:
            mesh.attributes.remove(uv_attr)
        except Exception:
            pass
        uv_attr = None

    if uv_attr is None and hasattr(mesh, "uv_layers") and hasattr(mesh.uv_layers, "new"):
        try:
            mesh.uv_layers.new(name=target_name)
        except Exception:
            pass

    uv_ptr = resolve_loop_uvs_ptr(mesh, uv_name=target_name, expected_count=num_loops)
    if uv_ptr is None:
        return False

    try:
        blender_dna.copy_f32(
            _byte_view(mesh_data.loop_uvs_memoryview()),
            uv_ptr,
            num_loops * 2,
            max_bytes=num_loops * 8,
        )
        return True
    except Exception as e:
        logger.debug("DNA direct copy UVs failed: %s", e)

    return False


def inject_color_attributes_dna(mesh: Any, mesh_data: Any) -> bool:
    """Injects vertex/loop color attributes via direct memory pointer write."""
    blender_dna = get_libmtk_dna()
    if blender_dna is None or not is_dna_available():
        return False

    col_mv = mesh_data.colors_memoryview() if hasattr(mesh_data, "colors_memoryview") else None
    if col_mv is None:
        return False

    total_bytes = getattr(col_mv, "nbytes", len(col_mv) * getattr(col_mv, "itemsize", 1))
    num_color_elems = total_bytes // (4 * 4)
    if num_color_elems == len(getattr(mesh, "loops", [])):
        domain = "CORNER"
    elif num_color_elems == len(getattr(mesh, "vertices", [])):
        domain = "POINT"
    else:
        return False

    col_attr = mesh.color_attributes.get("color") if hasattr(mesh, "color_attributes") else None
    if col_attr is not None and (getattr(col_attr, "domain", "") != domain or len(col_attr.data) != num_color_elems):
        try:
            mesh.color_attributes.remove(col_attr)
        except Exception:
            pass
        col_attr = None

    if col_attr is None and hasattr(mesh, "color_attributes") and hasattr(mesh.color_attributes, "new"):
        try:
            mesh.color_attributes.new(name="color", type="FLOAT_COLOR", domain=domain)
        except Exception:
            pass

    col_ptr = resolve_colors_ptr(mesh, expected_count=num_color_elems)
    if col_ptr is None:
        return False

    try:
        blender_dna.copy_f32(
            _byte_view(col_mv), col_ptr, num_color_elems * 4, max_bytes=total_bytes
        )
        return True
    except Exception as e:
        logger.debug("DNA direct copy colors failed: %s", e)

    return False


def inject_custom_attribute_dna(
    b_attr: Any,
    mv: Any,
    b_type: str,
    elem_count: int,
) -> bool:
    """
    Directly injects generic CustomData attribute memory layers via libmtk_blender_dna.
    Returns True if successfully written, or False if standard fallback is required.
    """
    blender_dna = get_libmtk_dna()
    if blender_dna is None or not is_dna_available():
        return False

    if elem_count == 0:
        return True

    if mv is None:
        return False

    if b_type in ("FLOAT", "FLOAT2", "FLOAT_VECTOR", "FLOAT_COLOR"):
        align = 4
        stride = 1
        if b_type == "FLOAT2":
            stride = 2
        elif b_type == "FLOAT_VECTOR":
            stride = 3
        elif b_type == "FLOAT_COLOR":
            stride = 4
        total_count = elem_count * stride
        attr_ptr = resolve_attribute_ptr(b_attr, min_elements=elem_count, required_align=align)
        if attr_ptr is None:
            return False
        try:
            blender_dna.copy_f32(
                _byte_view(mv),
                attr_ptr,
                total_count,
                max_bytes=total_count * 4,
            )
            return True
        except Exception as e:
            logger.debug(
                "DNA direct copy float attribute %s failed: %s",
                getattr(b_attr, "name", ""),
                e,
            )
            return False

    elif b_type in ("INT", "INT32"):
        attr_ptr = resolve_attribute_ptr(b_attr, min_elements=elem_count, required_align=4)
        if attr_ptr is None:
            return False
        try:
            blender_dna.copy_i32(
                _byte_view(mv),
                attr_ptr,
                elem_count,
                max_bytes=elem_count * 4,
            )
            return True
        except Exception as e:
            logger.debug(
                "DNA direct copy int attribute %s failed: %s",
                getattr(b_attr, "name", ""),
                e,
            )
            return False

    elif b_type in ("INT8", "BOOLEAN", "BYTE_COLOR"):
        stride = 4 if b_type == "BYTE_COLOR" else 1
        total_count = elem_count * stride
        attr_ptr = resolve_attribute_ptr(b_attr, min_elements=elem_count, required_align=1)
        if attr_ptr is None:
            return False
        try:
            blender_dna.copy_u8(
                _byte_view(mv),
                attr_ptr,
                total_count,
                max_bytes=total_count,
            )
            return True
        except Exception as e:
            logger.debug(
                "DNA direct copy byte attribute %s failed: %s",
                getattr(b_attr, "name", ""),
                e,
            )
            return False

    return False


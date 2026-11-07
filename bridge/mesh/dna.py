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
    is_dna_enabled,
    resolve_attribute_ptr,
    resolve_colors_ptr,
    resolve_corner_verts_ptr,
    resolve_loop_uvs_ptr,
    resolve_materials_ptr,
    resolve_polygons_offset_ptr,
    resolve_positions_ptr,
)
from ..engine import get_libmtk_dna
from .standard import clean_zombie_attributes

logger = logging.getLogger("MoziToolKit.Bridge.Mesh.DNA")

_POLYGON_OFFSETS_CACHE: Dict[Tuple[int, int], np.ndarray] = {}


def _get_polygon_offsets(total_loops: int, stride: int) -> np.ndarray:
    key = (total_loops, stride)
    cached = _POLYGON_OFFSETS_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_POLYGON_OFFSETS_CACHE) > 32:
        _POLYGON_OFFSETS_CACHE.clear()
    arr = np.arange(0, total_loops + stride, stride, dtype=np.int32)
    _POLYGON_OFFSETS_CACHE[key] = arr
    return arr


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
    if blender_dna is None or not is_dna_enabled():
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
        mesh.loops.foreach_set("vertex_index", src)

    # 3. Direct setup polygons
    if not shade_smooth:
        mesh.polygons.foreach_set("use_smooth", b"\x00" * poly_count)

    offset_ptr = resolve_polygons_offset_ptr(mesh, expected_count=poly_count)
    offset_copied = False
    if offset_ptr is not None:
        try:
            offsets = _get_polygon_offsets(total_loops, stride)
            blender_dna.copy_i32(
                _byte_view(offsets),
                offset_ptr,
                poly_count + 1,
                max_bytes=(poly_count + 1) * 4,
            )
            offset_copied = True
        except Exception as e:
            logger.debug("DNA direct polygon offset copy failed: %s", e)

    if not offset_copied:
        offsets = _get_polygon_offsets(total_loops, stride)
        mesh.polygons.foreach_set("loop_start", offsets[:poly_count])
        mesh.polygons.foreach_set("loop_total", np.full(poly_count, stride, dtype=np.int32))

    return True


def inject_vertex_positions_dna(mesh: Any, mesh_data: Any) -> bool:
    """Injects vertex positions via direct memory pointer write."""
    blender_dna = get_libmtk_dna()
    if blender_dna is None or not is_dna_enabled():
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
    """
    Direct vertex normals injection stub.

    In Blender 4.2+, point-domain normals are evaluated dynamically by the
    evaluation graph and not stored as a writable CustomData layer. Custom
    normals must be written via split corner normals or standard channels.
    Returns False immediately to trigger official safe-path handling with zero overhead.
    """
    _ = (mesh, mesh_data)
    return False


def inject_face_materials_dna(mesh: Any, mesh_data: Any) -> bool:
    """
    Directly injects polygon material indices via hardware-accelerated memory write.
    Returns True if successfully written, or False if safe-path fallback is required.
    """
    blender_dna = get_libmtk_dna()
    if blender_dna is None or not is_dna_enabled():
        return False

    num_polys = len(getattr(mesh, "polygons", []))
    if num_polys == 0:
        return True

    mats_mv = getattr(mesh_data, "face_materials_memoryview", lambda: None)()
    if mats_mv is None:
        used = getattr(mesh_data, "used_materials", lambda: None)()
        if used and len(used) == 1 and used[0] != 0:
            val = int(used[0])
            mats_mv = np.full(num_polys, val, dtype=np.int32)
        else:
            return False

    if len(mats_mv) != num_polys:
        # Triangulated quad expansion or count mismatch: fall back to standard
        return False

    # Blender material_index is 32-bit integer; MeshData.face_materials is uint16.
    if getattr(mats_mv, "itemsize", 4) != 4 or getattr(mats_mv, "format", "") != "i":
        mats_mv = np.asarray(mats_mv, dtype=np.int32)

    # Ensure material_index attribute exists on mesh
    mat_attr = mesh.attributes.get("material_index") if hasattr(mesh, "attributes") else None
    if mat_attr is None and hasattr(mesh, "attributes") and hasattr(mesh.attributes, "new"):
        try:
            mat_attr = mesh.attributes.new(name="material_index", type="INT", domain="FACE")
        except Exception as e:
            logger.debug("Failed creating material_index attribute: %s", e)

    mat_ptr = resolve_materials_ptr(mesh, expected_count=num_polys)
    if mat_ptr is None:
        return False

    try:
        blender_dna.copy_i32(
            _byte_view(mats_mv),
            mat_ptr,
            num_polys,
            max_bytes=num_polys * 4,
        )
        return True
    except Exception as e:
        logger.debug("DNA direct copy face materials failed: %s", e)
        return False


def inject_uvs_dna(mesh: Any, mesh_data: Any, uv_layer_name: Optional[str] = None) -> bool:
    """Injects loop UVs via direct memory pointer write."""
    blender_dna = get_libmtk_dna()
    if blender_dna is None or not is_dna_enabled():
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
    if blender_dna is None or not is_dna_enabled():
        return False

    col_mv = mesh_data.colors_memoryview() if hasattr(mesh_data, "colors_memoryview") else None
    if col_mv is None:
        if hasattr(mesh, "color_attributes"):
            col_attr = mesh.color_attributes.get("color")
            if col_attr is None and hasattr(mesh.color_attributes, "new") and len(getattr(mesh, "loops", [])) > 0:
                try:
                    col_attr = mesh.color_attributes.new(name="color", type="FLOAT_COLOR", domain="CORNER")
                except Exception:
                    pass
            if col_attr is not None and hasattr(mesh.color_attributes, "active_color"):
                try:
                    mesh.color_attributes.active_color = col_attr
                except Exception:
                    pass
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
        if hasattr(mesh, "color_attributes"):
            active_attr = mesh.color_attributes.get("color")
            if active_attr is not None and hasattr(mesh.color_attributes, "active_color"):
                try:
                    mesh.color_attributes.active_color = active_attr
                except Exception:
                    pass
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
    if blender_dna is None or not is_dna_enabled():
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


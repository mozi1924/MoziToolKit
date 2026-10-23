"""
Standard Safe Blender Python API Mesh Ingestion Channel.

Uses 100% official Blender Python APIs (bpy.types.Attribute, foreach_set, NumPy buffers)
with zero pointer operations or ctypes, guaranteeing safe cross-version stability.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from .constants import safe_get_attribute

logger = logging.getLogger("MoziToolKit.Bridge.Mesh.Standard")


def clean_zombie_attributes(mesh: Any) -> None:
    """Purges non-builtin custom attributes after clear_geometry so they don't linger with 0 length."""
    if not hasattr(mesh, "attributes"):
        return
    builtin_names = {
        "position", ".corner_vert", ".corner_edge", ".edge_verts",
        ".select_vert", ".select_edge", ".select_poly", "sharp_face",
    }
    for attr in list(mesh.attributes):
        if attr.name not in builtin_names:
            try:
                mesh.attributes.remove(attr)
            except Exception:
                pass


def inject_topology_standard(
    mesh: Any,
    mesh_data: Any,
    v_count: int,
    is_quad: bool,
    total_indices: int,
    shade_smooth: bool = False,
) -> bool:
    """Rebuilds mesh topology using standard Blender BPy APIs (vertices.add, foreach_set)."""
    if not (hasattr(mesh.vertices, "add") and hasattr(mesh.loops, "add") and hasattr(mesh.polygons, "add")):
        return False

    mesh.clear_geometry()
    clean_zombie_attributes(mesh)

    poly_count = (total_indices // 6) if is_quad else (total_indices // 3)
    stride = 4 if is_quad else 3
    total_loops = poly_count * stride

    # 1. Batch allocate counts atomically
    mesh.vertices.add(v_count)
    mesh.loops.add(total_loops)
    mesh.polygons.add(poly_count)

    # 2. Vertex positions
    pos_mv = mesh_data.positions_memoryview()
    if hasattr(pos_mv, "cast") and pos_mv.format == "B":
        pos_mv = pos_mv.cast("f")

    try:
        mesh.vertices.foreach_set("co", pos_mv)
    except Exception:
        pos_attr = safe_get_attribute(mesh, "position")
        if pos_attr is not None and len(pos_attr.data) == v_count:
            pos_arr = np.frombuffer(pos_mv, dtype=np.float32)
            pos_attr.data.foreach_set("vector", pos_arr)

    # 3. Loops & Corner Vertices
    if is_quad:
        quad_mv = mesh_data.quad_indices_memoryview()
        if quad_mv is None:
            raise RuntimeError("Quad mesh is missing quad_indices")
        if hasattr(quad_mv, "cast") and quad_mv.format == "B":
            quad_mv = quad_mv.cast("i")
        loop_indices = quad_mv
    else:
        indices_mv = mesh_data.indices_memoryview()
        if hasattr(indices_mv, "cast") and indices_mv.format == "B":
            indices_mv = indices_mv.cast("i")
        loop_indices = indices_mv

    try:
        mesh.loops.foreach_set("vertex_index", loop_indices)
    except Exception:
        cvert_attr = safe_get_attribute(mesh, ".corner_vert")
        if cvert_attr is not None and len(cvert_attr.data) == total_loops:
            arr = np.frombuffer(loop_indices, dtype=np.int32)
            cvert_attr.data.foreach_set("value", arr)

    # 4. Polygons
    if not shade_smooth:
        mesh.polygons.foreach_set("use_smooth", b"\x00" * poly_count)

    mesh.polygons.foreach_set("loop_start", np.arange(0, total_loops, stride, dtype=np.int32))
    mesh.polygons.foreach_set("loop_total", np.full(poly_count, stride, dtype=np.int32))
    return True


def inject_vertex_positions_standard(mesh: Any, mesh_data: Any) -> None:
    """Standard injection for vertex positions."""
    pos_attr = safe_get_attribute(mesh, "position")
    if pos_attr is not None and len(pos_attr.data) > 0:
        try:
            pos_arr = np.frombuffer(mesh_data.positions_memoryview(), dtype=np.float32)
            pos_attr.data.foreach_set("vector", pos_arr)
            return
        except Exception:
            pass

    try:
        pos_mv = mesh_data.positions_memoryview()
        if hasattr(pos_mv, "cast") and pos_mv.format == "B":
            pos_mv = pos_mv.cast("f")
        mesh.vertices.foreach_set("co", pos_mv)
    except Exception:
        pass


def inject_vertex_normals_standard(mesh: Any, mesh_data: Any) -> None:
    """Standard injection for vertex normals."""
    norm_attr = safe_get_attribute(mesh, "normal")
    if norm_attr is not None and len(norm_attr.data) > 0:
        try:
            norm_arr = np.frombuffer(mesh_data.normals_memoryview(), dtype=np.float32)
            norm_attr.data.foreach_set("vector", norm_arr)
            return
        except Exception:
            pass

    try:
        norm_mv = mesh_data.normals_memoryview()
        if hasattr(norm_mv, "cast") and norm_mv.format == "B":
            norm_mv = norm_mv.cast("f")
        mesh.vertices.foreach_set("normal", norm_mv)
    except Exception:
        pass


def inject_uvs_standard(mesh: Any, mesh_data: Any, uv_layer_name: Optional[str] = None) -> None:
    """Standard injection for loop UVs."""
    if not hasattr(mesh, "uv_layers") or len(getattr(mesh, "loops", [])) == 0:
        return

    num_loops = len(mesh.loops)
    target_name = uv_layer_name
    if not target_name:
        active_layer = getattr(mesh.uv_layers, "active", None)
        target_name = active_layer.name if active_layer else (mesh.uv_layers[0].name if len(mesh.uv_layers) > 0 else "UVMap")

    uv_layer = mesh.uv_layers.get(target_name) if hasattr(mesh.uv_layers, "get") else None
    if uv_layer is None and hasattr(mesh.uv_layers, "new"):
        try:
            uv_layer = mesh.uv_layers.new(name=target_name)
        except Exception:
            pass

    target_setter = getattr(getattr(uv_layer, "data", None), "foreach_set", None)
    attr_key = "uv"
    if target_setter is None:
        uv_attr = safe_get_attribute(mesh, target_name)
        if uv_attr is not None and hasattr(getattr(uv_attr, "data", None), "foreach_set"):
            target_setter = uv_attr.data.foreach_set
            attr_key = "vector"

    if target_setter is None:
        return

    # Priority 1: Fast loop UVs memoryview
    loop_uv_mv = getattr(mesh_data, "loop_uvs_memoryview", lambda: None)()
    if loop_uv_mv is not None and len(loop_uv_mv) == num_loops * 2 * 4:
        try:
            loop_uv_arr = np.frombuffer(loop_uv_mv, dtype=np.float32)
            target_setter(attr_key, loop_uv_arr)
            return
        except Exception as e:
            logger.debug("Standard loop_uvs foreach_set failed: %s", e)

    # Priority 2: Standard UV flat array
    uv_mv = getattr(mesh_data, "uvs_memoryview", lambda: None)()
    if uv_mv is None:
        return

    uv_np = np.frombuffer(uv_mv, dtype=np.float32)
    if uv_np is not None:
        if len(uv_np) == num_loops * 2:
            target_setter(attr_key, uv_np)
        else:
            # Per-vertex UVs expansion into loop domain
            loop_vert_indices = np.empty(num_loops, dtype=np.int32)
            if hasattr(mesh.loops, "foreach_get"):
                mesh.loops.foreach_get("vertex_index", loop_vert_indices)
            else:
                cvert_attr = safe_get_attribute(mesh, ".corner_vert")
                if cvert_attr is not None and len(cvert_attr.data) == num_loops:
                    cvert_attr.data.foreach_get("value", loop_vert_indices)

            uv_table = uv_np.reshape(-1, 2)
            loop_uvs = np.ascontiguousarray(uv_table[loop_vert_indices].ravel(), dtype=np.float32)
            target_setter(attr_key, loop_uvs)


def inject_color_attributes_standard(mesh: Any, mesh_data: Any) -> None:
    """Standard injection for vertex/corner colors."""
    if not hasattr(mesh, "color_attributes") or not hasattr(mesh.color_attributes, "get"):
        return
    try:
        col_mv = mesh_data.colors_memoryview()
        if col_mv is None:
            return

        num_color_elems = len(col_mv) // (4 * 4)
        if num_color_elems == len(mesh.loops):
            domain = "CORNER"
        elif num_color_elems == len(mesh.vertices):
            domain = "POINT"
        else:
            return

        color_attr = mesh.color_attributes.get("color")
        if color_attr is not None and (color_attr.domain != domain or len(color_attr.data) != num_color_elems):
            if hasattr(mesh.color_attributes, "remove"):
                try:
                    mesh.color_attributes.remove(color_attr)
                except Exception:
                    pass
            color_attr = None

        if color_attr is None and hasattr(mesh.color_attributes, "new"):
            try:
                color_attr = mesh.color_attributes.new(name="color", type="FLOAT_COLOR", domain=domain)
            except Exception:
                return

        if color_attr is not None and hasattr(color_attr.data, "foreach_set"):
            col_arr = np.frombuffer(col_mv, dtype=np.float32)
            color_attr.data.foreach_set("color", col_arr)
    except Exception as e:
        logger.debug("Standard color attribute injection error: %s", e)


def inject_face_materials_standard(mesh: Any, mesh_data: Any) -> None:
    """Standard injection for polygon material indices in a single authoritative pass."""
    num_polys = len(getattr(mesh, "polygons", []))
    if num_polys == 0:
        return

    mats_mv = getattr(mesh_data, "face_materials_memoryview", lambda: None)()
    if mats_mv is None:
        used = getattr(mesh_data, "used_materials", lambda: None)()
        if used and len(used) == 1 and used[0] != 0:
            import numpy as np
            mesh.polygons.foreach_set("material_index", np.full(num_polys, int(used[0]), dtype=np.int32))
        return

    # Direct single-pass write to polygon material indices
    try:
        if hasattr(mats_mv, "cast") and mats_mv.format == "B":
            mats_mv = mats_mv.cast("H")
        if len(mats_mv) == num_polys:
            mesh.polygons.foreach_set("material_index", mats_mv)
            return
    except Exception:
        pass

    try:
        mats_arr = np.frombuffer(mats_mv, dtype=np.uint16).astype(np.int32)
        if len(mats_arr) == num_polys:
            mesh.polygons.foreach_set("material_index", mats_arr)
    except Exception as e:
        logger.debug("Standard material_index foreach_set error: %s", e)


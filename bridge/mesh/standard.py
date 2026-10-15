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
    """Purges non-builtin custom attributes before or after clear_geometry so they don't linger with 0 length."""
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
    if hasattr(mesh.vertices, "add") and hasattr(mesh.loops, "add") and hasattr(mesh.polygons, "add"):
        clean_zombie_attributes(mesh)
        mesh.clear_geometry()
        clean_zombie_attributes(mesh)
        mesh.vertices.add(v_count)

        # 1. Vertex positions
        pos_injected = False
        pos_attr = safe_get_attribute(mesh, "position")
        if pos_attr is not None and len(pos_attr.data) == v_count:
            try:
                pos_mv = mesh_data.positions_memoryview() if hasattr(mesh_data, "positions_memoryview") else None
                if pos_mv is not None:
                    pos_arr = np.frombuffer(pos_mv, dtype=np.float32)
                else:
                    pos_arr = np.ascontiguousarray(mesh_data.get_flat_positions(), dtype=np.float32)
                pos_attr.data.foreach_set("vector", pos_arr)
                pos_injected = True
            except Exception as e:
                logger.debug("Standard position attr injection fallback: %s", e)

        if not pos_injected:
            try:
                pos_mv = mesh_data.positions_memoryview() if hasattr(mesh_data, "positions_memoryview") else None
                if pos_mv is not None:
                    if hasattr(pos_mv, "cast") and pos_mv.format == "B":
                        pos_mv = pos_mv.cast("f")
                    mesh.vertices.foreach_set("co", pos_mv)
                else:
                    mesh.vertices.foreach_set(
                        "co", np.ascontiguousarray(mesh_data.get_flat_positions(), dtype=np.float32)
                    )
            except Exception as e:
                logger.debug("Standard vertex.co foreach_set failed: %s", e)

        # 2. Loops & Corner Vertices
        poly_count = (total_indices // 6) if is_quad else (total_indices // 3)
        stride = 4 if is_quad else 3
        total_loops = poly_count * stride
        mesh.loops.add(total_loops)

        loop_injected = False
        cvert_attr = safe_get_attribute(mesh, ".corner_vert")
        if cvert_attr is not None and len(cvert_attr.data) == total_loops:
            try:
                if is_quad:
                    quad_mv = mesh_data.quad_indices_memoryview() if hasattr(mesh_data, "quad_indices_memoryview") else None
                    arr = np.frombuffer(quad_mv, dtype=np.int32) if quad_mv is not None else np.ascontiguousarray(mesh_data.get_quad_indices(), dtype=np.int32)
                else:
                    idx_mv = mesh_data.indices_memoryview() if hasattr(mesh_data, "indices_memoryview") else None
                    arr = np.frombuffer(idx_mv, dtype=np.int32) if idx_mv is not None else np.ascontiguousarray(mesh_data.get_indices(), dtype=np.int32)
                cvert_attr.data.foreach_set("value", arr)
                loop_injected = True
            except Exception as e:
                logger.debug("Standard .corner_vert foreach_set failed: %s", e)

        if not loop_injected:
            try:
                if is_quad:
                    quad_mv = mesh_data.quad_indices_memoryview() if hasattr(mesh_data, "quad_indices_memoryview") else None
                    if quad_mv is not None:
                        if hasattr(quad_mv, "cast") and quad_mv.format == "B":
                            quad_mv = quad_mv.cast("i")
                        mesh.loops.foreach_set("vertex_index", quad_mv)
                    else:
                        mesh.loops.foreach_set(
                            "vertex_index", np.ascontiguousarray(mesh_data.get_quad_indices(), dtype=np.int32)
                        )
                else:
                    indices_mv = mesh_data.indices_memoryview() if hasattr(mesh_data, "indices_memoryview") else None
                    if indices_mv is not None:
                        if hasattr(indices_mv, "cast") and indices_mv.format == "B":
                            indices_mv = indices_mv.cast("i")
                        mesh.loops.foreach_set("vertex_index", indices_mv)
                    else:
                        mesh.loops.foreach_set(
                            "vertex_index", np.ascontiguousarray(mesh_data.get_indices(), dtype=np.int32)
                        )
            except Exception as e:
                logger.debug("Standard loops.vertex_index foreach_set failed: %s", e)

        # 3. Polygons
        mesh.polygons.add(poly_count)
        if not shade_smooth:
            mesh.polygons.foreach_set("use_smooth", b"\x00" * poly_count)

        mesh.polygons.foreach_set("loop_start", np.arange(0, total_loops, stride, dtype=np.int32))
        mesh.polygons.foreach_set("loop_total", np.full(poly_count, stride, dtype=np.int32))
        return True

    elif hasattr(mesh, "from_pydata"):
        pos_list = mesh_data.get_flat_positions()
        verts = [(pos_list[i * 3], pos_list[i * 3 + 1], pos_list[i * 3 + 2]) for i in range(v_count)]
        if is_quad:
            quad_count = total_indices // 6
            quad_indices = mesh_data.get_quad_indices()
            quads = [
                (quad_indices[q * 4], quad_indices[q * 4 + 1], quad_indices[q * 4 + 2], quad_indices[q * 4 + 3])
                for q in range(quad_count)
            ]
            mesh.clear_geometry()
            mesh.from_pydata(verts, [], quads)
        else:
            tri_indices = mesh_data.get_indices()
            tris = [(tri_indices[i], tri_indices[i + 1], tri_indices[i + 2]) for i in range(0, len(tri_indices), 3)]
            mesh.clear_geometry()
            mesh.from_pydata(verts, [], tris)
        return True

    return False


def inject_vertex_positions_standard(mesh: Any, mesh_data: Any) -> None:
    """Standard injection for vertex positions."""
    pos_attr = safe_get_attribute(mesh, "position")
    if pos_attr is not None and len(pos_attr.data) > 0:
        try:
            pos_mv = mesh_data.positions_memoryview() if hasattr(mesh_data, "positions_memoryview") else None
            if pos_mv is not None:
                pos_arr = np.frombuffer(pos_mv, dtype=np.float32)
            else:
                pos_arr = np.ascontiguousarray(mesh_data.get_flat_positions(), dtype=np.float32)
            pos_attr.data.foreach_set("vector", pos_arr)
            return
        except Exception:
            pass

    try:
        pos_mv = mesh_data.positions_memoryview() if hasattr(mesh_data, "positions_memoryview") else None
        if pos_mv is not None:
            if hasattr(pos_mv, "cast") and pos_mv.format == "B":
                pos_mv = pos_mv.cast("f")
            mesh.vertices.foreach_set("co", pos_mv)
        else:
            mesh.vertices.foreach_set(
                "co", np.ascontiguousarray(mesh_data.get_flat_positions(), dtype=np.float32)
            )
    except Exception:
        pass


def inject_vertex_normals_standard(mesh: Any, mesh_data: Any) -> None:
    """Standard injection for vertex normals."""
    norm_attr = safe_get_attribute(mesh, "normal")
    if norm_attr is not None and len(norm_attr.data) > 0:
        try:
            norm_mv = mesh_data.normals_memoryview() if hasattr(mesh_data, "normals_memoryview") else None
            if norm_mv is not None:
                norm_arr = np.frombuffer(norm_mv, dtype=np.float32)
            else:
                norm_arr = np.ascontiguousarray(mesh_data.get_flat_normals(), dtype=np.float32)
            norm_attr.data.foreach_set("vector", norm_arr)
            return
        except Exception:
            pass

    try:
        norm_mv = mesh_data.normals_memoryview() if hasattr(mesh_data, "normals_memoryview") else None
        if norm_mv is not None:
            if hasattr(norm_mv, "cast") and norm_mv.format == "B":
                norm_mv = norm_mv.cast("f")
            mesh.vertices.foreach_set("normal", norm_mv)
        else:
            mesh.vertices.foreach_set(
                "normal", np.ascontiguousarray(mesh_data.get_flat_normals(), dtype=np.float32)
            )
    except Exception:
        pass


def inject_uvs_standard(mesh: Any, mesh_data: Any, uv_layer_name: Optional[str] = None) -> None:
    """Standard injection for loop UVs."""
    if not hasattr(mesh, "uv_layers") or len(mesh.loops) == 0:
        return

    num_loops = len(mesh.loops)
    target_name = uv_layer_name
    if not target_name:
        active_layer = getattr(mesh.uv_layers, "active", None)
        target_name = active_layer.name if active_layer else (mesh.uv_layers[0].name if len(mesh.uv_layers) > 0 else "UVMap")

    uv_attr = safe_get_attribute(mesh, target_name)
    if uv_attr is not None and len(uv_attr.data) != num_loops:
        try:
            mesh.attributes.remove(uv_attr)
        except Exception:
            pass
        uv_attr = None

    uv_layer = mesh.uv_layers.get(target_name) if hasattr(mesh.uv_layers, "get") else None
    if uv_layer is None and hasattr(mesh.uv_layers, "new"):
        try:
            uv_layer = mesh.uv_layers.new(name=target_name)
        except Exception:
            pass
    if uv_attr is None:
        uv_attr = safe_get_attribute(mesh, target_name)

    if uv_layer is None and uv_attr is None:
        return

    # Priority 1: Fast loop UVs memoryview
    if hasattr(mesh_data, "loop_uvs_memoryview"):
        try:
            loop_uv_mv = mesh_data.loop_uvs_memoryview()
            if len(loop_uv_mv) == num_loops * 2 * 4:
                loop_uv_arr = np.frombuffer(loop_uv_mv, dtype=np.float32)
                if uv_attr is not None and len(uv_attr.data) == num_loops:
                    uv_attr.data.foreach_set("vector", loop_uv_arr)
                    return
                elif hasattr(uv_layer, "data") and hasattr(uv_layer.data, "foreach_set"):
                    uv_layer.data.foreach_set("uv", loop_uv_arr)
                    return
        except Exception:
            pass

    # Priority 2: Standard UV flat array
    uv_mv = mesh_data.uvs_memoryview() if hasattr(mesh_data, "uvs_memoryview") else None
    if uv_mv is not None:
        uv_np = np.frombuffer(uv_mv, dtype=np.float32)
    else:
        uv_flat = mesh_data.get_flat_uvs() if hasattr(mesh_data, "get_flat_uvs") else None
        uv_np = np.ascontiguousarray(uv_flat, dtype=np.float32) if uv_flat else None

    if uv_np is not None:
        if len(uv_np) == num_loops * 2:
            if uv_attr is not None and len(uv_attr.data) == num_loops:
                uv_attr.data.foreach_set("vector", uv_np)
            elif hasattr(uv_layer, "data") and hasattr(uv_layer.data, "foreach_set"):
                uv_layer.data.foreach_set("uv", uv_np)
        else:
            # Per-vertex UVs expansion into loop domain
            loop_vert_indices = np.empty(num_loops, dtype=np.int32)
            cvert_attr = safe_get_attribute(mesh, ".corner_vert")
            if cvert_attr is not None and len(cvert_attr.data) == num_loops:
                cvert_attr.data.foreach_get("value", loop_vert_indices)
            elif hasattr(mesh.loops, "foreach_get"):
                mesh.loops.foreach_get("vertex_index", loop_vert_indices)

            uv_table = uv_np.reshape(-1, 2)
            loop_uvs = np.ascontiguousarray(uv_table[loop_vert_indices].ravel(), dtype=np.float32)
            if uv_attr is not None and len(uv_attr.data) == num_loops:
                uv_attr.data.foreach_set("vector", loop_uvs)
            elif hasattr(uv_layer, "data") and hasattr(uv_layer.data, "foreach_set"):
                uv_layer.data.foreach_set("uv", loop_uvs)


def inject_color_attributes_standard(mesh: Any, mesh_data: Any) -> None:
    """Standard injection for vertex/corner colors."""
    if not hasattr(mesh, "color_attributes") or not hasattr(mesh.color_attributes, "get"):
        return
    try:
        col_mv = mesh_data.colors_memoryview() if hasattr(mesh_data, "colors_memoryview") else None
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
    """Standard injection for polygon material indices."""
    num_polys = len(getattr(mesh, "polygons", []))
    if num_polys == 0:
        return

    # 1. If an existing material_index attribute is present, populate it
    mat_attr = safe_get_attribute(mesh, "material_index")
    if mat_attr is not None and len(mat_attr.data) == num_polys and hasattr(mesh_data, "face_materials_memoryview"):
        try:
            mats_mv = mesh_data.face_materials_memoryview()
            if len(mats_mv) == num_polys * 2:
                mats_arr = np.frombuffer(mats_mv, dtype=np.uint16).astype(np.int32)
                mat_attr.data.foreach_set("value", mats_arr)
        except Exception:
            pass

    # 2. Directly set built-in polygon material indices (never create illegal duplicate attribute)
    try:
        mats_mv = mesh_data.face_materials_memoryview() if hasattr(mesh_data, "face_materials_memoryview") else None
        if mats_mv is not None:
            if hasattr(mats_mv, "cast") and mats_mv.format == "B":
                mats_mv = mats_mv.cast("H")
            if len(mats_mv) == num_polys:
                mesh.polygons.foreach_set("material_index", mats_mv)
                return

        face_mats = mesh_data.get_face_materials() if hasattr(mesh_data, "get_face_materials") else None
        if face_mats and len(face_mats) == num_polys:
            mat_arr = np.ascontiguousarray(face_mats, dtype=np.uint16)
            mesh.polygons.foreach_set("material_index", mat_arr)
    except Exception as e:
        logger.debug("Standard material_index foreach_set error: %s", e)


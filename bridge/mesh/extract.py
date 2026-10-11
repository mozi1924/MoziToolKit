"""
Mesh topology and attribute extraction from Blender Mesh into PyMeshData.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple

import numpy as np

from ..engine import require_libmtk
from .attributes import resolve_source_texture_keys
from .constants import (
    BLENDER_TO_MTK_DOMAIN,
    BLENDER_TO_MTK_TYPE,
    get_mesh,
    safe_get_attribute,
)

logger = logging.getLogger("MoziToolKit.Bridge.Mesh.Extract")


def _extract_topology_quads(
    mesh: Any,
    num_polys: int,
    num_verts: int,
    num_loops: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Extract contiguous vertex positions, normals, quad indices, and face materials."""
    pos_arr = np.empty(num_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", pos_arr)

    norm_arr = np.empty(num_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("normal", norm_arr)

    loop_v_indices = np.empty(num_loops, dtype=np.uint32)
    mesh.loops.foreach_get("vertex_index", loop_v_indices)

    face_mats = np.empty(num_polys, dtype=np.uint16)
    mesh.polygons.foreach_get("material_index", face_mats)

    np_pos = pos_arr.reshape((num_verts, 3))
    np_norms = norm_arr.reshape((num_verts, 3))

    corner_pos = np.ascontiguousarray(np_pos[loop_v_indices].ravel(), dtype=np.float32)
    corner_norms = np.ascontiguousarray(np_norms[loop_v_indices].ravel(), dtype=np.float32)

    base_v = (np.arange(num_polys, dtype=np.uint32) * 4)[:, None]
    quad_pattern = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)[None, :]
    indices = np.ascontiguousarray((base_v + quad_pattern).ravel(), dtype=np.uint32)

    return corner_pos, corner_norms, indices, face_mats


def _extract_topology_tris(
    mesh: Any,
    num_polys: int,
    num_verts: int,
    triangulate_if_needed: bool,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Extract arbitrary or triangulated mesh positions, normals, triangle indices, and face materials."""
    if hasattr(mesh, "calc_loop_triangles") and triangulate_if_needed:
        mesh.calc_loop_triangles()

    if hasattr(mesh, "loop_triangles") and len(mesh.loop_triangles) > 0:
        num_tris = len(mesh.loop_triangles)
        tri_indices = np.empty(num_tris * 3, dtype=np.uint32)
        mesh.loop_triangles.foreach_get("vertices", tri_indices)

        face_mats_arr = np.empty(num_tris, dtype=np.uint16)
        mesh.loop_triangles.foreach_get("material_index", face_mats_arr)
    else:
        tri_indices_list: List[int] = []
        face_mats_list: List[int] = []
        poly_mats = np.empty(num_polys, dtype=np.uint16)
        mesh.polygons.foreach_get("material_index", poly_mats)
        for poly_idx, poly in enumerate(mesh.polygons):
            vs = poly.vertices
            mat_idx = int(poly_mats[poly_idx])
            for i in range(1, len(vs) - 1):
                tri_indices_list.extend([vs[0], vs[i], vs[i + 1]])
                face_mats_list.append(mat_idx)
        tri_indices = np.array(tri_indices_list, dtype=np.uint32)
        face_mats_arr = np.array(face_mats_list, dtype=np.uint16)

    pos_arr = np.empty(num_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", pos_arr)

    norm_arr = np.empty(num_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("normal", norm_arr)

    return pos_arr, norm_arr, tri_indices, face_mats_arr


def _extract_uvs_quads(
    uv_layer: Optional[Any],
    num_polys: int,
    num_loops: int,
) -> np.ndarray:
    """Extract UV coordinates for quad topology."""
    total_corners = num_polys * 4
    if uv_layer and len(uv_layer.data) >= num_loops:
        uvs = np.empty(num_loops * 2, dtype=np.float32)
        uv_layer.data.foreach_get("uv", uvs)
        return uvs
    return np.zeros(total_corners * 2, dtype=np.float32)


def _extract_uvs_tris(
    mesh: Any,
    uv_layer: Optional[Any],
    num_verts: int,
) -> np.ndarray:
    """Extract UV coordinates for arbitrary/triangulated topology."""
    uv_arr = np.zeros(num_verts * 2, dtype=np.float32)
    if uv_layer is not None and len(mesh.loops) > 0:
        num_loops = len(mesh.loops)
        loop_uvs = np.empty(num_loops * 2, dtype=np.float32)
        uv_layer.data.foreach_get("uv", loop_uvs)
        loop_vert_indices = np.empty(num_loops, dtype=np.uint32)
        mesh.loops.foreach_get("vertex_index", loop_vert_indices)

        np_loop_uvs = loop_uvs.reshape(-1, 2)
        np_uv_arr = uv_arr.reshape(-1, 2)
        np_uv_arr[loop_vert_indices] = np_loop_uvs
        return np_uv_arr.ravel()
    return uv_arr


def _extract_custom_attributes(mesh: Any, mesh_data: Any) -> None:
    """Safely extracts custom attributes with RNA error suppression."""
    if not hasattr(mesh, "attributes"):
        return

    handled_source_keys = False
    for attr in mesh.attributes:
        try:
            attr_name = attr.name
            if attr_name in ("position", "normal") or attr_name.startswith("."):
                continue

            if attr_name in ("mtk_source_texture_key", "mtk_source_texture_idx"):
                if not handled_source_keys:
                    domain_str = BLENDER_TO_MTK_DOMAIN.get(attr.domain, "face")
                    resolved = resolve_source_texture_keys(mesh)
                    if resolved:
                        mesh_data.add_string_attribute("mtk_source_texture_key", domain_str, resolved)
                    handled_source_keys = True
                continue

            domain_str = BLENDER_TO_MTK_DOMAIN.get(attr.domain, "point")
            type_info = BLENDER_TO_MTK_TYPE.get(attr.data_type)
            if type_info is None:
                continue

            mtk_dtype, num_comp, typecode, value_key = type_info

            if attr.data_type == "STRING":
                str_vals = [elem.value for elem in attr.data]
                mesh_data.add_string_attribute(attr_name, domain_str, str_vals)
            else:
                elem_count = len(attr.data)
                if elem_count == 0:
                    continue
                if attr.data_type in ("FLOAT_COLOR", "BYTE_COLOR"):
                    buf = np.empty(elem_count * 4, dtype=np.float32)
                    attr.data.foreach_get("color", buf)
                    mesh_data.add_attribute_from_buffer(attr_name, domain_str, "float4", buf)
                elif attr.data_type in ("BOOLEAN", "INT8", "INT", "INT32"):
                    buf = np.empty(elem_count, dtype=np.int32)
                    attr.data.foreach_get("value", buf)
                    mesh_data.add_attribute_from_buffer(attr_name, domain_str, "int32", buf)
                else:
                    total_vals = elem_count * num_comp
                    np_dtype = np.float32 if typecode == "f" else np.int32
                    buf = np.empty(total_vals, dtype=np_dtype)
                    attr.data.foreach_get(value_key, buf)
                    mesh_data.add_attribute_from_buffer(attr_name, domain_str, mtk_dtype, buf)
        except Exception as e:
            logger.debug("Failed extracting attribute %s: %s", attr.name, e)


def extract_mesh_data(
    mesh_or_obj: Any,
    uv_layer_name: Optional[str] = None,
    include_attributes: bool = True,
    triangulate_if_needed: bool = False,
) -> Any:
    """
    Extracts contiguous geometry and custom attributes from a Blender Mesh into PyMeshData.
    Preserves Quad face topology and per-corner Loop UVs.
    """
    mtk = require_libmtk("extract_mesh_data")
    if not hasattr(mtk, "MeshData"):
        raise RuntimeError("Native libmtk does not provide MeshData.")

    mesh = get_mesh(mesh_or_obj)
    num_polys = len(getattr(mesh, "polygons", []))
    num_verts = len(getattr(mesh, "vertices", []))
    if num_polys == 0 or num_verts == 0:
        return mtk.MeshData()

    uv_layer = None
    if hasattr(mesh, "uv_layers") and len(mesh.uv_layers) > 0:
        if uv_layer_name:
            uv_layer = mesh.uv_layers.get(uv_layer_name)
        if uv_layer is None:
            uv_layer = mesh.uv_layers.active or mesh.uv_layers[0]

    is_all_quads = False
    if hasattr(mesh.polygons, "foreach_get"):
        try:
            poly_totals = np.empty(num_polys, dtype=np.int32)
            mesh.polygons.foreach_get("loop_total", poly_totals)
            is_all_quads = bool(np.all(poly_totals == 4))
        except Exception:
            is_all_quads = all(getattr(p, "loop_total", len(getattr(p, "vertices", []))) == 4 for p in mesh.polygons)
    else:
        is_all_quads = all(getattr(p, "loop_total", len(getattr(p, "vertices", []))) == 4 for p in mesh.polygons)

    if is_all_quads and not triangulate_if_needed:
        positions, normals, indices, face_mats = _extract_topology_quads(
            mesh, num_polys, num_verts, len(mesh.loops)
        )
        uvs = _extract_uvs_quads(uv_layer, num_polys, len(mesh.loops))
    else:
        positions, normals, indices, face_mats = _extract_topology_tris(
            mesh, num_polys, num_verts, triangulate_if_needed
        )
        uvs = _extract_uvs_tris(mesh, uv_layer, num_verts)

    mesh_data = mtk.MeshData.from_raw_buffers(
        positions=positions,
        uvs=uvs,
        indices=indices,
        normals=normals,
        face_materials=face_mats,
    )

    if include_attributes:
        _extract_custom_attributes(mesh, mesh_data)

    return mesh_data

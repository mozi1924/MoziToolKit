"""
Mesh topology and attribute extraction from Blender Mesh into PyMeshData.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from ..engine import require_libmtk
from .attribute_schema import ATTR_SOURCE_TEXTURE_IDX, ATTR_SOURCE_TEXTURE_KEY
from .attributes import resolve_source_texture_keys, resolve_source_texture_keys_paletted
from .constants import (
    BLENDER_TO_MTK_DOMAIN,
    BLENDER_TO_MTK_TYPE,
    get_mesh,
)

logger = logging.getLogger("MoziToolKit.Bridge.Mesh.Extract")


def extract_mesh_data(
    mesh_or_obj: Any,
    uv_layer_name: Optional[str] = None,
    include_attributes: bool = True,
    triangulate_if_needed: bool = False,
) -> Any:
    """
    Extracts shared-vertex polygon topology and per-loop UVs from a Blender Mesh.

    ``from_flat_polygons`` keeps the original vertex buffer (no 4x corner
    duplication) and stores UVs per loop, so seams survive roundtrips.
    """
    _ = triangulate_if_needed  # n-gons are triangulated by from_flat_polygons
    mtk = require_libmtk("extract_mesh_data")
    if not hasattr(mtk, "MeshData"):
        raise RuntimeError("Native libmtk does not provide MeshData.")

    mesh = get_mesh(mesh_or_obj)
    num_polys = len(getattr(mesh, "polygons", []))
    num_verts = len(getattr(mesh, "vertices", []))
    num_loops = len(getattr(mesh, "loops", []))
    if num_polys == 0 or num_verts == 0 or num_loops == 0:
        return mtk.MeshData()

    uv_layer = None
    if hasattr(mesh, "uv_layers") and len(mesh.uv_layers) > 0:
        if uv_layer_name:
            uv_layer = mesh.uv_layers.get(uv_layer_name)
        if uv_layer is None:
            uv_layer = mesh.uv_layers.active or mesh.uv_layers[0]

    positions = np.empty(num_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", positions)

    normals = np.empty(num_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("normal", normals)

    loop_vertices = np.empty(num_loops, dtype=np.uint32)
    mesh.loops.foreach_get("vertex_index", loop_vertices)

    loop_uvs = np.zeros(num_loops * 2, dtype=np.float32)
    if uv_layer is not None and len(uv_layer.data) >= num_loops:
        uv_layer.data.foreach_get("uv", loop_uvs)

    loop_totals = np.empty(num_polys, dtype=np.int32)
    mesh.polygons.foreach_get("loop_total", loop_totals)
    loop_starts = np.empty(num_polys, dtype=np.int32)
    try:
        mesh.polygons.foreach_get("loop_start", loop_starts)
    except Exception:
        loop_starts = np.concatenate(
            (np.zeros(1, dtype=np.int32), np.cumsum(loop_totals[:-1], dtype=np.int32))
        )

    face_materials = np.empty(num_polys, dtype=np.int32)
    mesh.polygons.foreach_get("material_index", face_materials)

    mesh_data = mtk.MeshData.from_flat_polygons(
        positions=positions,
        loop_vertices=loop_vertices,
        loop_uvs=loop_uvs,
        face_loop_starts=loop_starts.astype(np.uint32),
        face_loop_totals=loop_totals.astype(np.uint32),
        normals=normals,
        face_materials=face_materials.astype(np.uint32),
    )

    if include_attributes:
        _extract_custom_attributes(mesh, mesh_data)

    return mesh_data


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

            if attr_name in (ATTR_SOURCE_TEXTURE_KEY, ATTR_SOURCE_TEXTURE_IDX):
                if not handled_source_keys:
                    handled_source_keys = True
                    palette, indices = resolve_source_texture_keys_paletted(mesh)
                    if (
                        palette
                        and indices is not None
                        and len(indices) == len(mesh.polygons)
                        and hasattr(mesh_data, "add_string_attribute_from_palette")
                    ):
                        # Compact path: expand the palette inside Rust instead of
                        # building one Python string object per face.
                        mesh_data.add_string_attribute_from_palette(
                            ATTR_SOURCE_TEXTURE_KEY, "face", palette, indices
                        )
                    else:
                        domain_str = BLENDER_TO_MTK_DOMAIN.get(attr.domain, "face")
                        resolved = resolve_source_texture_keys(mesh)
                        if resolved:
                            mesh_data.add_string_attribute(
                                ATTR_SOURCE_TEXTURE_KEY, domain_str, resolved
                            )
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

"""
Mesh topology and attribute extraction from Blender Mesh into PyMeshData.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from ..dna import (
    is_dna_available,
    is_dna_enabled,
    resolve_attribute_ptr,
    resolve_corner_verts_ptr,
    resolve_loop_uvs_ptr,
    resolve_materials_ptr,
    resolve_polygons_offset_ptr,
    resolve_positions_ptr,
)
from ..engine import get_libmtk_dna, require_libmtk
from .attribute_schema import ATTR_SOURCE_TEXTURE_IDX, ATTR_SOURCE_TEXTURE_KEY, ATTR_SOURCE_TEXTURES
from .attributes import resolve_source_texture_keys_paletted
from .constants import (
    BLENDER_TO_MTK_DOMAIN,
    BLENDER_TO_MTK_TYPE,
    get_mesh,
)

logger = logging.getLogger("MoziToolKit.Bridge.Mesh.Extract")


def extract_mesh_data_dna(
    mesh: Any,
    uv_layer_name: Optional[str] = None,
    include_attributes: bool = True,
) -> Optional[Any]:
    """
    Extracts shared-vertex polygon topology and attributes via direct DNA memory views.

    Bypasses CPython RNA iterators and NumPy heap allocations by constructing zero-copy
    memoryviews directly referencing Blender C++ arrays. Returns None if pointers are
    unavailable, triggering seamless fallback to official safe-path foreach_get.
    """
    blender_dna = get_libmtk_dna()
    if blender_dna is None or not is_dna_enabled():
        return None

    mtk = require_libmtk("extract_mesh_data_dna")
    if not hasattr(mtk, "MeshData"):
        return None

    try:
        num_polys = len(getattr(mesh, "polygons", []))
        num_verts = len(getattr(mesh, "vertices", []))
        num_loops = len(getattr(mesh, "loops", []))
        if num_polys == 0 or num_verts == 0 or num_loops == 0:
            return mtk.MeshData()

        pos_ptr = resolve_positions_ptr(mesh, expected_count=num_verts)
        loop_vert_ptr = resolve_corner_verts_ptr(mesh, expected_count=num_loops)
        offset_ptr = resolve_polygons_offset_ptr(mesh, expected_count=num_polys)

        if pos_ptr is None or loop_vert_ptr is None or offset_ptr is None:
            return None

        uv_layer = None
        target_uv_name = uv_layer_name
        if hasattr(mesh, "uv_layers") and len(mesh.uv_layers) > 0:
            if target_uv_name:
                uv_layer = mesh.uv_layers.get(target_uv_name)
            if uv_layer is None:
                uv_layer = mesh.uv_layers.active or mesh.uv_layers[0]
                target_uv_name = uv_layer.name

        loop_uv_ptr = None
        if uv_layer is not None and len(uv_layer.data) >= num_loops:
            loop_uv_ptr = resolve_loop_uvs_ptr(mesh, uv_name=target_uv_name, expected_count=num_loops)

        mat_ptr = resolve_materials_ptr(mesh, expected_count=num_polys)

        positions_mv = blender_dna.as_memoryview_f32(pos_ptr, num_verts * 3)
        loop_verts_mv = blender_dna.as_memoryview_u32(loop_vert_ptr, num_loops)
        offsets_mv = blender_dna.as_memoryview_i32(offset_ptr, num_polys + 1)

        if loop_uv_ptr is not None:
            loop_uvs_mv = blender_dna.as_memoryview_f32(loop_uv_ptr, num_loops * 2)
        else:
            loop_uvs_mv = np.zeros(num_loops * 2, dtype=np.float32)

        face_mats_mv = None
        if mat_ptr is not None:
            face_mats_mv = blender_dna.as_memoryview_i32(mat_ptr, num_polys)

        mesh_data = mtk.MeshData.from_polygon_offsets(
            positions=positions_mv,
            loop_vertices=loop_verts_mv,
            loop_uvs=loop_uvs_mv,
            face_offsets=offsets_mv,
            normals=None,
            face_materials=face_mats_mv,
        )

        if include_attributes:
            _extract_custom_attributes(mesh, mesh_data, use_dna=True)

        return mesh_data
    except Exception as e:
        logger.debug("extract_mesh_data_dna failed, falling back to safe path: %s", e)
        return None


def extract_mesh_data(
    mesh_or_obj: Any,
    uv_layer_name: Optional[str] = None,
    include_attributes: bool = True,
    triangulate_if_needed: bool = False,
    use_dna: bool = True,
) -> Any:
    """
    Extracts shared-vertex polygon topology and per-loop UVs from a Blender Mesh.

    Dual-channel architecture: prioritizes fast DNA direct read, seamlessly falling
    back to official Bpy foreach_get when DNA is disabled or pointers are invalid.
    """
    _ = triangulate_if_needed  # n-gons are triangulated by from_flat_polygons
    mesh = get_mesh(mesh_or_obj)

    if use_dna and is_dna_enabled():
        dna_mesh = extract_mesh_data_dna(
            mesh, uv_layer_name=uv_layer_name, include_attributes=include_attributes
        )
        if dna_mesh is not None:
            return dna_mesh

    # Official Safe-Path: standard foreach_get
    mtk = require_libmtk("extract_mesh_data")
    if not hasattr(mtk, "MeshData"):
        raise RuntimeError("Native libmtk does not provide MeshData.")

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
        _extract_custom_attributes(mesh, mesh_data, use_dna=False)

    return mesh_data


def _extract_custom_attributes(mesh: Any, mesh_data: Any, use_dna: bool = False) -> None:
    """Safely extracts custom attributes with RNA error suppression and DNA acceleration."""
    if not hasattr(mesh, "attributes"):
        return

    blender_dna = get_libmtk_dna() if (use_dna and is_dna_enabled()) else None

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
                    ):
                        # Provenance travels as `palette + indices` (Golden Rule 8) so
                        # no per-face Python strings are ever materialized. The retired
                        # `mtk_source_texture_key` string layer is never re-emitted.
                        mesh_data.add_string_attribute(
                            ATTR_SOURCE_TEXTURES, "mesh", list(palette)
                        )
                        mesh_data.add_attribute_from_buffer(
                            ATTR_SOURCE_TEXTURE_IDX,
                            "face",
                            "int32",
                            np.ascontiguousarray(indices, dtype=np.int32),
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

                dna_injected = False
                if blender_dna is not None:
                    attr_ptr = resolve_attribute_ptr(attr, min_elements=elem_count)
                    if attr_ptr is not None:
                        try:
                            if attr.data_type == "FLOAT_COLOR":
                                mv = blender_dna.as_memoryview_f32(attr_ptr, elem_count * 4)
                                mesh_data.add_attribute_from_buffer(attr_name, domain_str, "float4", mv)
                                dna_injected = True
                            elif attr.data_type == "BYTE_COLOR":
                                mv = blender_dna.as_memoryview_u8(attr_ptr, elem_count * 4)
                                mesh_data.add_attribute_from_buffer(attr_name, domain_str, "float4", mv)
                                dna_injected = True
                            elif attr.data_type in ("BOOLEAN", "INT8"):
                                mv = blender_dna.as_memoryview_u8(attr_ptr, elem_count)
                                mesh_data.add_attribute_from_buffer(attr_name, domain_str, "int32", mv)
                                dna_injected = True
                            elif attr.data_type in ("INT", "INT32"):
                                mv = blender_dna.as_memoryview_i32(attr_ptr, elem_count)
                                mesh_data.add_attribute_from_buffer(attr_name, domain_str, "int32", mv)
                                dna_injected = True
                            elif typecode == "f":
                                total_vals = elem_count * num_comp
                                mv = blender_dna.as_memoryview_f32(attr_ptr, total_vals)
                                mesh_data.add_attribute_from_buffer(attr_name, domain_str, mtk_dtype, mv)
                                dna_injected = True
                        except Exception as e:
                            logger.debug("DNA attribute extraction failed for %s, falling back: %s", attr_name, e)

                if not dna_injected:
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

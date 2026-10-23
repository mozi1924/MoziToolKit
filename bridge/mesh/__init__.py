"""
MoziToolKit Mesh Bridge Module.

High-throughput geometry and attribute marshalling between Blender Mesh (bpy.types.Mesh)
and libmtk (Rust PyMeshData), featuring strict separation between standard Python APIs
and hardware-accelerated direct DNA raw memory writes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..dna import is_dna_enabled
from ..engine import get_libmtk
from .attributes import (
    inject_attribute,
    inject_custom_attributes,
    inject_face_attribute_float,
    inject_face_attribute_float4,
    inject_face_attribute_int,
    inject_face_attribute_string,
    inject_face_attribute_vector,
    inject_face_source_texture_keys,
    inject_face_source_texture_palette,
    resolve_source_texture_keys,
    resolve_source_texture_keys_paletted,
)
from .constants import (
    BLENDER_TO_MTK_DOMAIN,
    BLENDER_TO_MTK_TYPE,
    MTK_TO_BLENDER_DOMAIN,
    MTK_TO_BLENDER_TYPE,
    _get_mesh,
    get_mesh,
)
from .dna import (
    inject_color_attributes_dna,
    inject_topology_dna,
    inject_uvs_dna,
    inject_vertex_normals_dna,
    inject_vertex_positions_dna,
)
from .extract import extract_mesh_data
from .topology import analyze_mesh_hard_edges
from .standard import (
    inject_color_attributes_standard,
    inject_face_materials_standard,
    inject_topology_standard,
    inject_uvs_standard,
    inject_vertex_normals_standard,
    inject_vertex_positions_standard,
)

logger = logging.getLogger("MoziToolKit.Bridge.Mesh")


def __getattr__(name: str) -> Any:
    mtk = get_libmtk()
    if name == "mtk_py":
        return mtk
    if name == "MeshData":
        return getattr(mtk, "MeshData", Any) if mtk else Any
    if name == "AttributeDomain":
        return getattr(mtk, "AttributeDomain", Any) if mtk else Any
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def inject_mesh_data(
    mesh_data: Any,
    mesh_or_obj: Any,
    uv_layer_name: Optional[str] = None,
    update_topology: bool = False,
    update_normals: bool = False,
    inject_attributes: bool = True,
    shade_smooth: bool = False,
    skip_string_attributes: bool = False,
    use_dna: bool = True,
) -> None:
    """
    Injects processed geometry and custom attributes from PyMeshData into a Blender Mesh.

    Automatically dispatches between the high-throughput DNA raw memory channel
    and the 100% stable standard BPy channel with graceful fallback.
    """
    if hasattr(mesh_or_obj, "vertex_count") and not hasattr(mesh_data, "vertex_count"):
        mesh_data, mesh_or_obj = mesh_or_obj, mesh_data

    mesh = get_mesh(mesh_or_obj)
    v_count = getattr(mesh_data, "vertex_count", 0)
    if v_count == 0:
        return

    topology_updated = False
    needs_topology = update_topology or len(getattr(mesh, "vertices", [])) != v_count

    if needs_topology:
        face_count = getattr(mesh_data, "face_count", 0)
        tri_count = getattr(mesh_data, "triangle_count", 0)
        total_indices = tri_count * 3
        is_quad = (
            total_indices > 0
            and total_indices % 6 == 0
            and face_count == total_indices // 6
        )

        # 1. Try DNA fast path if enabled
        if use_dna and is_dna_enabled():
            try:
                topology_updated = inject_topology_dna(
                    mesh, mesh_data, v_count, is_quad, total_indices, shade_smooth=shade_smooth
                )
            except Exception as e:
                logger.debug("DNA direct topology injection fallback: %s", e)
                topology_updated = False

        # 2. Fallback to standard Python API
        if not topology_updated:
            topology_updated = inject_topology_standard(
                mesh, mesh_data, v_count, is_quad, total_indices, shade_smooth=shade_smooth
            )

    # Vertex positions injection if topology was not recreated
    if not topology_updated:
        pos_injected = False
        if use_dna and is_dna_enabled():
            try:
                pos_injected = inject_vertex_positions_dna(mesh, mesh_data)
            except Exception as e:
                logger.debug("DNA direct positions injection fallback: %s", e)
        if not pos_injected:
            inject_vertex_positions_standard(mesh, mesh_data)

    # Normals injection
    if update_normals:
        norm_injected = False
        if use_dna and is_dna_enabled():
            try:
                norm_injected = inject_vertex_normals_dna(mesh, mesh_data)
            except Exception as e:
                logger.debug("DNA direct normals injection fallback: %s", e)
        if not norm_injected:
            inject_vertex_normals_standard(mesh, mesh_data)

    # UVs injection
    uv_injected = False
    if use_dna and is_dna_enabled():
        try:
            uv_injected = inject_uvs_dna(mesh, mesh_data, uv_layer_name=uv_layer_name)
        except Exception as e:
            logger.debug("DNA direct UV injection fallback: %s", e)
    if not uv_injected:
        inject_uvs_standard(mesh, mesh_data, uv_layer_name=uv_layer_name)

    # Color attributes injection
    col_injected = False
    if use_dna and is_dna_enabled():
        try:
            col_injected = inject_color_attributes_dna(mesh, mesh_data)
        except Exception as e:
            logger.debug("DNA direct color injection fallback: %s", e)
    if not col_injected:
        inject_color_attributes_standard(mesh, mesh_data)

    # Face materials: always use the standard RNA path. Blender stores material
    # indices as a narrow integer inside its polygon struct; DNA-direct writes
    # would need a version-specific layout contract for no measurable gain.
    inject_face_materials_standard(mesh, mesh_data)

    # Extra custom attributes
    if inject_attributes:
        inject_custom_attributes(
            mesh,
            mesh_data,
            skip_string_attributes=skip_string_attributes,
            use_dna=use_dna,
        )

    mesh.update(calc_edges=topology_updated)


__all__ = [
    "BLENDER_TO_MTK_DOMAIN",
    "BLENDER_TO_MTK_TYPE",
    "MTK_TO_BLENDER_DOMAIN",
    "MTK_TO_BLENDER_TYPE",
    "_get_mesh",
    "analyze_mesh_hard_edges",
    "extract_mesh_data",
    "inject_attribute",
    "inject_custom_attributes",
    "inject_face_attribute_float",
    "inject_face_attribute_float4",
    "inject_face_attribute_int",
    "inject_face_attribute_string",
    "inject_face_attribute_vector",
    "inject_face_source_texture_keys",
    "inject_face_source_texture_palette",
    "inject_mesh_data",
    "resolve_source_texture_keys",
    "resolve_source_texture_keys_paletted",
]

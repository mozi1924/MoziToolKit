"""
MoziToolKit Mesh Bridge Module.

Zero-copy high-throughput geometry and attribute marshalling between
Blender Mesh (bpy.types.Mesh) and libmtk (Rust PyMeshData).
"""

from __future__ import annotations

import array
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import mtk_py
    MeshData = mtk_py.MeshData
    AttributeDomain = mtk_py.AttributeDomain
except ImportError:
    # Graceful fallback for type annotations or documentation builds
    MeshData = Any  # type: ignore
    AttributeDomain = Any  # type: ignore


# Mapping from Blender Attribute Domain to libmtk Domain
BLENDER_TO_MTK_DOMAIN: Dict[str, str] = {
    "POINT": "point",
    "CORNER": "corner",
    "FACE": "face",
    "EDGE": "point",  # Edge attributes mapped to point domain if needed
}

# Mapping from libmtk Domain to Blender Attribute Domain
MTK_TO_BLENDER_DOMAIN: Dict[str, str] = {
    "point": "POINT",
    "corner": "CORNER",
    "face": "FACE",
    "mesh": "POINT",  # Constant/Global attributes fallback
}

# Mapping from Blender Attribute DataType to (libmtk_dtype, num_components, array_typecode, value_attr)
BLENDER_TO_MTK_TYPE: Dict[str, Tuple[str, int, str, str]] = {
    "FLOAT": ("float", 1, "f", "value"),
    "FLOAT_VECTOR": ("float3", 3, "f", "vector"),
    "FLOAT_VECTOR2": ("float2", 2, "f", "vector"),
    "FLOAT_COLOR": ("float4", 4, "f", "color"),
    "BYTE_COLOR": ("uint8", 4, "B", "color"),
    "INT": ("int32", 1, "i", "value"),
    "INT8": ("int8", 1, "b", "value"),
    "INT32": ("int32", 1, "i", "value"),
    "BOOLEAN": ("bool", 1, "b", "value"),
    "STRING": ("string", 1, "", "value"),
}

# Mapping from libmtk DataType name to (blender_data_type, value_attr, array_typecode)
MTK_TO_BLENDER_TYPE: Dict[str, Tuple[str, str, str]] = {
    "Float": ("FLOAT", "value", "f"),
    "Float2": ("FLOAT_VECTOR2", "vector", "f"),
    "Float3": ("FLOAT_VECTOR", "vector", "f"),
    "Float4": ("FLOAT_COLOR", "color", "f"),
    "Int8": ("INT8", "value", "b"),
    "Int16": ("INT", "value", "h"),
    "Int32": ("INT", "value", "i"),
    "UInt8": ("INT", "value", "B"),
    "UInt16": ("INT", "value", "H"),
    "UInt32": ("INT", "value", "I"),
    "Bool": ("BOOLEAN", "value", "b"),
    "String": ("STRING", "value", ""),
}


def _get_mesh(mesh_or_obj: Any) -> Any:
    """Helper to resolve bpy.types.Mesh from either Mesh or Object."""
    if hasattr(mesh_or_obj, "type") and mesh_or_obj.type == "MESH":
        return mesh_or_obj.data
    return mesh_or_obj


def extract_mesh_data(
    mesh_or_obj: Any,
    uv_layer_name: Optional[str] = None,
    include_attributes: bool = True,
    triangulate_if_needed: bool = True,
) -> Any:
    """
    Extracts contiguous geometry and custom attributes from a Blender Mesh into PyMeshData.

    Uses zero-copy `foreach_get` memory buffer extraction for ultra-fast performance.

    Args:
        mesh_or_obj: A `bpy.types.Mesh` or `bpy.types.Object` of type 'MESH'.
        uv_layer_name: Optional UV layer name. Defaults to active UV layer.
        include_attributes: If True, extracts custom attributes into PyMeshData.
        triangulate_if_needed: If True, calculates loop triangles for non-triangulated meshes.

    Returns:
        PyMeshData: A populated libmtk MeshData buffer ready for SIMD/Rust processing.
    """
    if mtk_py is None or not hasattr(mtk_py, "MeshData"):
        raise RuntimeError("mtk_py is not installed or available.")

    mesh = _get_mesh(mesh_or_obj)
    num_verts = len(mesh.vertices)
    if num_verts == 0:
        return mtk_py.MeshData()

    # 1. Extract Vertex Positions
    pos_arr = array.array("f", [0.0]) * (num_verts * 3)
    mesh.vertices.foreach_get("co", pos_arr)

    # 2. Extract Vertex Normals
    norm_arr = array.array("f", [0.0]) * (num_verts * 3)
    mesh.vertices.foreach_get("normal", norm_arr)

    # 3. Extract Triangle Indices & UVs
    num_loops = len(mesh.loops)
    
    # Check UV layer
    uv_layer = None
    if hasattr(mesh, "uv_layers") and len(mesh.uv_layers) > 0:
        if uv_layer_name:
            uv_layer = mesh.uv_layers.get(uv_layer_name)
        if uv_layer is None:
            uv_layer = mesh.uv_layers.active or mesh.uv_layers[0]

    # Extract polygon triangle indices
    # Blender 2.80+ provides loop_triangles
    if hasattr(mesh, "calc_loop_triangles") and triangulate_if_needed:
        mesh.calc_loop_triangles()

    if hasattr(mesh, "loop_triangles") and len(mesh.loop_triangles) > 0:
        num_tris = len(mesh.loop_triangles)
        tri_indices = array.array("I", [0]) * (num_tris * 3)
        mesh.loop_triangles.foreach_get("vertices", tri_indices)

        face_mats = array.array("H", [0]) * num_tris
        mesh.loop_triangles.foreach_get("material_index", face_mats)
    else:
        # Fallback to polygons
        num_polys = len(mesh.polygons)
        poly_mat_arr = array.array("H", [0]) * num_polys
        mesh.polygons.foreach_get("material_index", poly_mat_arr)
        
        # Triangulate simple polygons
        tri_indices_list: List[int] = []
        face_mats_list: List[int] = []
        for poly_idx, poly in enumerate(mesh.polygons):
            vs = poly.vertices
            mat_idx = poly_mat_arr[poly_idx]
            for i in range(1, len(vs) - 1):
                tri_indices_list.extend([vs[0], vs[i], vs[i + 1]])
                face_mats_list.append(mat_idx)
        tri_indices = array.array("I", tri_indices_list)
        face_mats = array.array("H", face_mats_list)

    # Extract UVs
    # In libmtk, UVs are per-vertex coordinates (v_count * 2) or corner mapped.
    # When vertex-shared UVs are needed, we extract per-vertex or corner UVs.
    uv_arr = array.array("f", [0.0]) * (num_verts * 2)
    if uv_layer is not None and num_loops > 0:
        loop_uvs = array.array("f", [0.0]) * (num_loops * 2)
        uv_layer.data.foreach_get("uv", loop_uvs)
        
        loop_vert_indices = array.array("I", [0]) * num_loops
        mesh.loops.foreach_get("vertex_index", loop_vert_indices)
        
        # Map loop UVs to vertex UV buffer
        for loop_idx, v_idx in enumerate(loop_vert_indices):
            uv_arr[v_idx * 2] = loop_uvs[loop_idx * 2]
            uv_arr[v_idx * 2 + 1] = loop_uvs[loop_idx * 2 + 1]

    # Construct PyMeshData
    mesh_data = mtk_py.MeshData.from_raw_buffers(
        positions=list(pos_arr),
        uvs=list(uv_arr),
        indices=list(tri_indices),
        normals=list(norm_arr),
        face_materials=list(face_mats),
    )

    # 4. Extract Custom Attributes
    if include_attributes and hasattr(mesh, "attributes"):
        for attr in mesh.attributes:
            attr_name = attr.name
            # Skip built-in coordinate/normal attributes already processed
            if attr_name in ("position", "normal") or attr_name.startswith("."):
                continue

            domain_str = BLENDER_TO_MTK_DOMAIN.get(attr.domain, "point")
            type_info = BLENDER_TO_MTK_TYPE.get(attr.data_type)

            if type_info is None:
                continue

            mtk_dtype, num_comp, typecode, value_key = type_info

            if attr.data_type == "STRING":
                # String attributes are non-buffer
                str_vals = [elem.value for elem in attr.data]
                mesh_data.add_string_attribute(attr_name, domain_str, str_vals)
            else:
                elem_count = len(attr.data)
                total_vals = elem_count * num_comp
                buf = array.array(typecode, [0] * total_vals if typecode in ("b", "i", "B", "h", "H", "I") else [0.0] * total_vals)
                attr.data.foreach_get(value_key, buf)
                mesh_data.add_attribute_from_buffer(attr_name, domain_str, mtk_dtype, buf)

    return mesh_data


def inject_mesh_data(
    mesh_data: Any,
    mesh_or_obj: Any,
    uv_layer_name: Optional[str] = None,
    update_topology: bool = False,
    update_normals: bool = False,
    inject_attributes: bool = True,
) -> None:
    """
    Injects processed geometry and custom attributes from PyMeshData back into a Blender Mesh.

    Utilizes zero-copy MemoryView buffers and `foreach_set` for ultra-fast updates.

    Args:
        mesh_data: The libmtk `PyMeshData` containing modified vertices/UVs/attributes.
        mesh_or_obj: A `bpy.types.Mesh` or `bpy.types.Object` of type 'MESH'.
        uv_layer_name: Optional UV layer name to write. Defaults to active or "UVMap".
        update_topology: If True, resets and rebuilds topology from mesh_data indices.
        update_normals: If True, updates vertex normals.
        inject_attributes: If True, synchronizes custom attributes into `mesh.attributes`.
    """
    mesh = _get_mesh(mesh_or_obj)
    v_count = mesh_data.vertex_count

    if v_count == 0:
        return

    # 1. Update Topology if requested
    if update_topology or len(mesh.vertices) != v_count:
        mesh.clear_geometry()
        # Flat indices for triangles
        tri_indices = mesh_data.get_indices()
        tris = [
            (tri_indices[i], tri_indices[i + 1], tri_indices[i + 2])
            for i in range(0, len(tri_indices), 3)
        ]
        # Rebuild vertices from flat positions
        pos_list = mesh_data.get_flat_positions()
        verts = [
            (pos_list[i * 3], pos_list[i * 3 + 1], pos_list[i * 3 + 2])
            for i in range(v_count)
        ]
        mesh.from_pydata(verts, [], tris)

    # 2. Fast Vertex Positions Injection via MemoryView
    try:
        pos_mv = mesh_data.positions_memoryview()
        mesh.vertices.foreach_set("co", pos_mv)
    except Exception:
        # Fallback to flat list
        mesh.vertices.foreach_set("co", mesh_data.get_flat_positions())

    # 3. Vertex Normals Injection
    if update_normals:
        try:
            norm_mv = mesh_data.normals_memoryview()
            mesh.vertices.foreach_set("normal", norm_mv)
        except Exception:
            mesh.vertices.foreach_set("normal", mesh_data.get_flat_normals())

    # 4. UV Injection (Corner / Loop Domain)
    if hasattr(mesh, "uv_layers"):
        uv_layer = None
        if uv_layer_name:
            uv_layer = mesh.uv_layers.get(uv_layer_name)
        if uv_layer is None:
            uv_layer = mesh.uv_layers.active or (
                mesh.uv_layers[0] if len(mesh.uv_layers) > 0 else mesh.uv_layers.new(name=uv_layer_name or "UVMap")
            )

        if uv_layer is not None and len(mesh.loops) > 0:
            num_loops = len(mesh.loops)
            loop_vert_indices = array.array("I", [0]) * num_loops
            mesh.loops.foreach_get("vertex_index", loop_vert_indices)

            uv_flat = mesh_data.get_flat_uvs()
            loop_uv_arr = array.array("f", [0.0]) * (num_loops * 2)
            for loop_idx, v_idx in enumerate(loop_vert_indices):
                if v_idx * 2 + 1 < len(uv_flat):
                    loop_uv_arr[loop_idx * 2] = uv_flat[v_idx * 2]
                    loop_uv_arr[loop_idx * 2 + 1] = uv_flat[v_idx * 2 + 1]

            uv_layer.data.foreach_set("uv", loop_uv_arr)

    # 5. Material Indices Injection
    if hasattr(mesh, "polygons") and len(mesh.polygons) > 0:
        face_mats = mesh_data.get_face_materials()
        if len(face_mats) == len(mesh.polygons):
            mat_arr = array.array("H", face_mats)
            mesh.polygons.foreach_set("material_index", mat_arr)

    # 6. Generic Custom Attribute Injection
    if inject_attributes and hasattr(mesh, "attributes"):
        for attr_name in mesh_data.attribute_names():
            info = mesh_data.attribute_info(attr_name)
            if info is None:
                continue

            domain_str, dtype_name, elem_count = info
            b_domain = MTK_TO_BLENDER_DOMAIN.get(domain_str.lower(), "POINT")
            type_tuple = MTK_TO_BLENDER_TYPE.get(dtype_name)

            if type_tuple is None:
                continue

            b_type, value_key, typecode = type_tuple

            # Check or create attribute in Blender mesh
            b_attr = mesh.attributes.get(attr_name)
            if b_attr is None:
                try:
                    b_attr = mesh.attributes.new(name=attr_name, type=b_type, domain=b_domain)
                except Exception:
                    continue

            if dtype_name == "String":
                str_vals = mesh_data.get_string_attribute(attr_name)
                if str_vals and len(str_vals) == len(b_attr.data):
                    for i, val in enumerate(str_vals):
                        b_attr.data[i].value = val
            else:
                mv = mesh_data.attribute_memoryview(attr_name)
                if mv is not None:
                    try:
                        b_attr.data.foreach_set(value_key, mv)
                    except Exception:
                        pass

    mesh.update()

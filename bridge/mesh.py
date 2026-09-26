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
    import libmtk_py as mtk_py
    MeshData = getattr(mtk_py, "MeshData", Any)
    AttributeDomain = getattr(mtk_py, "AttributeDomain", Any)
except (ImportError, AttributeError):
    try:
        import mtk_py
        MeshData = getattr(mtk_py, "MeshData", Any)
        AttributeDomain = getattr(mtk_py, "AttributeDomain", Any)
    except (ImportError, AttributeError):
        # Graceful fallback for type annotations or documentation builds
        mtk_py = None
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
    "float": ("FLOAT", "value", "f"),
    "float2": ("FLOAT_VECTOR2", "vector", "f"),
    "float3": ("FLOAT_VECTOR", "vector", "f"),
    "float4": ("FLOAT_COLOR", "color", "f"),
    "int8": ("INT8", "value", "b"),
    "int16": ("INT", "value", "h"),
    "int32": ("INT", "value", "i"),
    "uint8": ("INT", "value", "B"),
    "uint16": ("INT", "value", "H"),
    "uint32": ("INT", "value", "I"),
    "bool": ("BOOLEAN", "value", "b"),
    "string": ("STRING", "value", ""),
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
    triangulate_if_needed: bool = False,
) -> Any:
    """
    Extracts contiguous geometry and custom attributes from a Blender Mesh into PyMeshData.

    Preserves Quad face topology and per-corner Loop UVs without destroying UV seams.

    Args:
        mesh_or_obj: A `bpy.types.Mesh` or `bpy.types.Object` of type 'MESH'.
        uv_layer_name: Optional UV layer name. Defaults to active UV layer.
        include_attributes: If True, extracts custom attributes into PyMeshData.
        triangulate_if_needed: If True and mesh is not quads/tris, triangulates polygons.

    Returns:
        PyMeshData: A populated libmtk MeshData buffer ready for SIMD/Rust processing.
    """
    if mtk_py is None or not hasattr(mtk_py, "MeshData"):
        raise RuntimeError("mtk_py is not installed or available.")

    mesh = _get_mesh(mesh_or_obj)
    num_polys = len(mesh.polygons)
    num_verts = len(mesh.vertices)
    if num_polys == 0 or num_verts == 0:
        return mtk_py.MeshData()

    # Check UV layer
    uv_layer = None
    if hasattr(mesh, "uv_layers") and len(mesh.uv_layers) > 0:
        if uv_layer_name:
            uv_layer = mesh.uv_layers.get(uv_layer_name)
        if uv_layer is None:
            uv_layer = mesh.uv_layers.active or mesh.uv_layers[0]

    # Check if mesh consists primarily of Quads
    is_all_quads = all(p.loop_total == 4 for p in mesh.polygons)

    if is_all_quads and not triangulate_if_needed:
        # Extract Quad Mesh data with dedicated 4-vertex corners per face
        # to ensure 100% preservation of UV seams and corner attributes
        positions: List[float] = []
        normals: List[float] = []
        uvs: List[float] = []
        indices: List[int] = []
        face_mats: List[int] = []

        # Read base mesh vertices & normals
        raw_pos = array.array("f", [0.0]) * (num_verts * 3)
        mesh.vertices.foreach_get("co", raw_pos)

        raw_norms = array.array("f", [0.0]) * (num_verts * 3)
        mesh.vertices.foreach_get("normal", raw_norms)

        num_loops = len(mesh.loops)
        raw_loop_uvs = array.array("f", [0.0]) * (num_loops * 2) if uv_layer else None
        if raw_loop_uvs and uv_layer:
            uv_layer.data.foreach_get("uv", raw_loop_uvs)

        raw_loop_v_indices = array.array("I", [0]) * num_loops
        mesh.loops.foreach_get("vertex_index", raw_loop_v_indices)

        poly_mats = array.array("H", [0]) * num_polys
        mesh.polygons.foreach_get("material_index", poly_mats)

        for poly_idx, poly in enumerate(mesh.polygons):
            base_v = len(positions) // 3
            mat_idx = poly_mats[poly_idx]
            l_start = poly.loop_start

            for k in range(4):
                l_idx = l_start + k
                v_idx = raw_loop_v_indices[l_idx]

                positions.extend([
                    raw_pos[v_idx * 3],
                    raw_pos[v_idx * 3 + 1],
                    raw_pos[v_idx * 3 + 2],
                ])
                normals.extend([
                    raw_norms[v_idx * 3],
                    raw_norms[v_idx * 3 + 1],
                    raw_norms[v_idx * 3 + 2],
                ])

                if raw_loop_uvs:
                    uvs.extend([
                        raw_loop_uvs[l_idx * 2],
                        raw_loop_uvs[l_idx * 2 + 1],
                    ])
                else:
                    uvs.extend([0.0, 0.0])

            # Two triangles for the quad (0, 1, 2) and (0, 2, 3)
            indices.extend([
                base_v, base_v + 1, base_v + 2,
                base_v, base_v + 2, base_v + 3,
            ])
            face_mats.append(mat_idx)

        mesh_data = mtk_py.MeshData.from_raw_buffers(
            positions=positions,
            uvs=uvs,
            indices=indices,
            normals=normals,
            face_materials=face_mats,
        )
    else:
        # Triangulated / arbitrary polygon extraction
        if hasattr(mesh, "calc_loop_triangles") and triangulate_if_needed:
            mesh.calc_loop_triangles()

        if hasattr(mesh, "loop_triangles") and len(mesh.loop_triangles) > 0:
            num_tris = len(mesh.loop_triangles)
            tri_indices = array.array("I", [0]) * (num_tris * 3)
            mesh.loop_triangles.foreach_get("vertices", tri_indices)

            face_mats_arr = array.array("H", [0]) * num_tris
            mesh.loop_triangles.foreach_get("material_index", face_mats_arr)
        else:
            tri_indices_list: List[int] = []
            face_mats_list: List[int] = []
            poly_mats = array.array("H", [0]) * num_polys
            mesh.polygons.foreach_get("material_index", poly_mats)
            for poly_idx, poly in enumerate(mesh.polygons):
                vs = poly.vertices
                mat_idx = poly_mats[poly_idx]
                for i in range(1, len(vs) - 1):
                    tri_indices_list.extend([vs[0], vs[i], vs[i + 1]])
                    face_mats_list.append(mat_idx)
            tri_indices = array.array("I", tri_indices_list)
            face_mats_arr = array.array("H", face_mats_list)

        pos_arr = array.array("f", [0.0]) * (num_verts * 3)
        mesh.vertices.foreach_get("co", pos_arr)

        norm_arr = array.array("f", [0.0]) * (num_verts * 3)
        mesh.vertices.foreach_get("normal", norm_arr)

        uv_arr = array.array("f", [0.0]) * (num_verts * 2)
        if uv_layer is not None and len(mesh.loops) > 0:
            num_loops = len(mesh.loops)
            loop_uvs = array.array("f", [0.0]) * (num_loops * 2)
            uv_layer.data.foreach_get("uv", loop_uvs)
            loop_vert_indices = array.array("I", [0]) * num_loops
            mesh.loops.foreach_get("vertex_index", loop_vert_indices)
            for loop_idx, v_idx in enumerate(loop_vert_indices):
                uv_arr[v_idx * 2] = loop_uvs[loop_idx * 2]
                uv_arr[v_idx * 2 + 1] = loop_uvs[loop_idx * 2 + 1]

        mesh_data = mtk_py.MeshData.from_raw_buffers(
            positions=list(pos_arr),
            uvs=list(uv_arr),
            indices=list(tri_indices),
            normals=list(norm_arr),
            face_materials=list(face_mats_arr),
        )

    # 4. Safely Extract Custom Attributes with error suppression
    if include_attributes and hasattr(mesh, "attributes"):
        for attr in mesh.attributes:
            try:
                attr_name = attr.name
                if attr_name in ("position", "normal") or attr_name.startswith("."):
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
                        buf = array.array("f", [0.0] * (elem_count * 4))
                        attr.data.foreach_get("color", buf)
                        mesh_data.add_attribute_from_buffer(attr_name, domain_str, "float4", buf)
                    elif attr.data_type in ("BOOLEAN", "INT8", "INT", "INT32"):
                        buf = array.array("i", [0] * elem_count)
                        attr.data.foreach_get("value", buf)
                        mesh_data.add_attribute_from_buffer(attr_name, domain_str, "int32", buf)
                    else:
                        total_vals = elem_count * num_comp
                        buf = array.array(typecode, [0.0] * total_vals if typecode == "f" else [0] * total_vals)
                        attr.data.foreach_get(value_key, buf)
                        mesh_data.add_attribute_from_buffer(attr_name, domain_str, mtk_dtype, buf)
            except Exception:
                # Silently skip attributes that do not support RNA foreach_get
                continue

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

    Preserves Quad face topology when available.

    Args:
        mesh_data: The libmtk `PyMeshData` containing modified vertices/UVs/attributes.
        mesh_or_obj: A `bpy.types.Mesh` or `bpy.types.Object` of type 'MESH'.
        uv_layer_name: Optional UV layer name to write. Defaults to active or "UVMap".
        update_topology: If True, resets and rebuilds topology from mesh_data indices.
        update_normals: If True, updates vertex normals.
        inject_attributes: If True, synchronizes custom attributes into `mesh.attributes`.
    """
    # Defensive guard: automatically handle inverted (mesh_or_obj, mesh_data) argument order
    if hasattr(mesh_or_obj, "vertex_count") and not hasattr(mesh_data, "vertex_count"):
        mesh_data, mesh_or_obj = mesh_or_obj, mesh_data

    mesh = _get_mesh(mesh_or_obj)
    v_count = getattr(mesh_data, "vertex_count", 0)

    if v_count == 0:
        return

    # 1. Update Topology if requested
    if update_topology or len(mesh.vertices) != v_count:
        pos_list = mesh_data.get_flat_positions()
        verts = [
            (pos_list[i * 3], pos_list[i * 3 + 1], pos_list[i * 3 + 2])
            for i in range(v_count)
        ]

        # Use Quad faces if available (in libmtk, 6 indices per quad and 1 face_material per quad)
        face_mats = (
            mesh_data.get_face_materials()
            if hasattr(mesh_data, "get_face_materials")
            else []
        )
        tri_count = getattr(mesh_data, "triangle_count", 0)
        total_indices = tri_count * 3
        is_quad = (
            total_indices > 0
            and total_indices % 6 == 0
            and len(face_mats) == total_indices // 6
        )

        if is_quad:
            quad_count = total_indices // 6
            quad_indices = mesh_data.get_quad_indices()
            quads = [
                (
                    quad_indices[q * 4],
                    quad_indices[q * 4 + 1],
                    quad_indices[q * 4 + 2],
                    quad_indices[q * 4 + 3],
                )
                for q in range(quad_count)
            ]
            mesh.clear_geometry()
            mesh.from_pydata(verts, [], quads)
        else:
            tri_indices = mesh_data.get_indices()
            tris = [
                (tri_indices[i], tri_indices[i + 1], tri_indices[i + 2])
                for i in range(0, len(tri_indices), 3)
            ]
            mesh.clear_geometry()
            mesh.from_pydata(verts, [], tris)

        mesh.update(calc_edges=True)

    # 2. Fast Vertex Positions Injection via MemoryView
    try:
        pos_mv = mesh_data.positions_memoryview()
        if hasattr(pos_mv, "cast") and pos_mv.format == "B":
            pos_mv = pos_mv.cast("f")
        mesh.vertices.foreach_set("co", pos_mv)
    except Exception:
        mesh.vertices.foreach_set("co", mesh_data.get_flat_positions())

    # 3. Vertex Normals Injection
    if update_normals:
        try:
            norm_mv = mesh_data.normals_memoryview()
            if hasattr(norm_mv, "cast") and norm_mv.format == "B":
                norm_mv = norm_mv.cast("f")
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

    # 5. Vertex Colors Injection (AO / Tint)
    if hasattr(mesh, "color_attributes"):
        try:
            col_mv = mesh_data.colors_memoryview() if hasattr(mesh_data, "colors_memoryview") else None
            if col_mv is not None:
                if hasattr(col_mv, "cast") and col_mv.format == "B":
                    col_mv = col_mv.cast("f")
                color_attr = mesh.color_attributes.get("color")
                if color_attr is None:
                    color_attr = mesh.color_attributes.new(
                        name="color",
                        type="FLOAT_COLOR",
                        domain="POINT",
                    )
                color_attr.data.foreach_set("color", col_mv)
        except Exception:
            pass

    # 6. Material Indices Injection
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

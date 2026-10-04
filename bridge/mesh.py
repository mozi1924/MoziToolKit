"""
MoziToolKit Mesh Bridge Module.

Zero-copy high-throughput geometry and attribute marshalling between
Blender Mesh (bpy.types.Mesh) and libmtk (Rust PyMeshData).
"""

from __future__ import annotations

import array
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("MoziToolKit.Bridge.Mesh")

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
        mtk_py = None
        MeshData = Any  # type: ignore
        AttributeDomain = Any  # type: ignore

BLENDER_TO_MTK_DOMAIN: Dict[str, str] = {
    "POINT": "point",
    "CORNER": "corner",
    "FACE": "face",
    "EDGE": "point",
}

MTK_TO_BLENDER_DOMAIN: Dict[str, str] = {
    "point": "POINT",
    "corner": "CORNER",
    "face": "FACE",
    "mesh": "POINT",
}

BLENDER_TO_MTK_TYPE: Dict[str, Tuple[str, int, str, str]] = {
    "FLOAT": ("float", 1, "f", "value"),
    "FLOAT_VECTOR": ("float3", 3, "f", "vector"),
    "FLOAT_VECTOR2": ("float2", 2, "f", "vector"),
    "FLOAT2": ("float2", 2, "f", "vector"),
    "FLOAT_COLOR": ("float4", 4, "f", "color"),
    "BYTE_COLOR": ("uint8", 4, "B", "color"),
    "INT": ("int32", 1, "i", "value"),
    "INT8": ("int8", 1, "b", "value"),
    "INT32": ("int32", 1, "i", "value"),
    "BOOLEAN": ("bool", 1, "b", "value"),
    "STRING": ("string", 1, "", "value"),
}

MTK_TO_BLENDER_TYPE: Dict[str, Tuple[str, str, str]] = {
    "float": ("FLOAT", "value", "f"),
    "float2": ("FLOAT2", "vector", "f"),
    "float3": ("FLOAT_VECTOR", "vector", "f"),
    "float4": ("FLOAT_COLOR", "color", "f"),
    "int8": ("INT8", "value", "b"),
    "int16": ("INT", "value", "h"),
    "int32": ("INT", "value", "i"),
    "uint8": ("INT", "value", "B"),
    "uint16": ("INT", "value", "H"),
    "uint32": ("INT", "value", "I"),
    "bool": ("BOOLEAN", "value", "?"),
    "string": ("STRING", "value", ""),
    "Float": ("FLOAT", "value", "f"),
    "Float2": ("FLOAT2", "vector", "f"),
    "Float3": ("FLOAT_VECTOR", "vector", "f"),
    "Float4": ("FLOAT_COLOR", "color", "f"),
    "Int8": ("INT8", "value", "b"),
    "Int16": ("INT", "value", "h"),
    "Int32": ("INT", "value", "i"),
    "UInt8": ("INT", "value", "B"),
    "UInt16": ("INT", "value", "H"),
    "UInt32": ("INT", "value", "I"),
    "Bool": ("BOOLEAN", "value", "?"),
    "String": ("STRING", "value", ""),
}


def _get_mesh(mesh_or_obj: Any) -> Any:
    """Helper to resolve bpy.types.Mesh from either Mesh or Object."""
    if hasattr(mesh_or_obj, "type") and mesh_or_obj.type == "MESH":
        return mesh_or_obj.data
    return mesh_or_obj


# =============================================================================
# Topology Extraction Helpers (Vertex & Quad/Tri Topologies)
# =============================================================================

def _extract_topology_quads(
    mesh: Any,
    num_polys: int,
    num_verts: int,
    num_loops: int,
) -> Tuple[array.array, array.array, array.array, array.array]:
    """Extract contiguous vertex positions, normals, quad indices, and face materials."""
    total_corners = num_polys * 4

    raw_pos = array.array("f", [0.0]) * (num_verts * 3)
    mesh.vertices.foreach_get("co", raw_pos)

    raw_norms = array.array("f", [0.0]) * (num_verts * 3)
    mesh.vertices.foreach_get("normal", raw_norms)

    raw_loop_v_indices = array.array("I", [0]) * num_loops
    mesh.loops.foreach_get("vertex_index", raw_loop_v_indices)

    face_mats = array.array("H", [0]) * num_polys
    mesh.polygons.foreach_get("material_index", face_mats)

    if HAS_NUMPY:
        np_pos = np.frombuffer(raw_pos, dtype=np.float32).reshape((num_verts, 3))
        np_norms = np.frombuffer(raw_norms, dtype=np.float32).reshape((num_verts, 3))
        np_loop_v = np.frombuffer(raw_loop_v_indices, dtype=np.uint32)

        np_corner_pos = np_pos[np_loop_v].ravel()
        np_corner_norms = np_norms[np_loop_v].ravel()

        positions = array.array("f")
        positions.frombytes(np_corner_pos.tobytes())
        normals = array.array("f")
        normals.frombytes(np_corner_norms.tobytes())

        base_v = (np.arange(num_polys, dtype=np.uint32) * 4)[:, None]
        quad_pattern = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)[None, :]
        np_indices = (base_v + quad_pattern).ravel()
        indices = array.array("I")
        indices.frombytes(np_indices.tobytes())
    else:
        positions = array.array("f", [0.0]) * (total_corners * 3)
        normals = array.array("f", [0.0]) * (total_corners * 3)
        indices = array.array("I", [0]) * (num_polys * 6)

        for l_idx, v_idx in enumerate(raw_loop_v_indices):
            p_off = l_idx * 3
            v_off = v_idx * 3
            positions[p_off:p_off + 3] = raw_pos[v_off:v_off + 3]
            normals[p_off:p_off + 3] = raw_norms[v_off:v_off + 3]

        for poly_idx in range(num_polys):
            base_v = poly_idx * 4
            idx_off = poly_idx * 6
            indices[idx_off:idx_off + 6] = array.array("I", [
                base_v, base_v + 1, base_v + 2,
                base_v, base_v + 2, base_v + 3
            ])

    return positions, normals, indices, face_mats


def _extract_topology_tris(
    mesh: Any,
    num_polys: int,
    num_verts: int,
    triangulate_if_needed: bool,
) -> Tuple[array.array, array.array, array.array, array.array]:
    """Extract arbitrary or triangulated mesh positions, normals, triangle indices, and face materials."""
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

    return pos_arr, norm_arr, tri_indices, face_mats_arr


# =============================================================================
# UV Extraction Helpers
# =============================================================================

def _extract_uvs_quads(
    uv_layer: Optional[Any],
    num_polys: int,
    num_loops: int,
) -> array.array:
    """Extract UV coordinates for quad topology."""
    total_corners = num_polys * 4
    if uv_layer:
        uvs = array.array("f", [0.0]) * (num_loops * 2)
        uv_layer.data.foreach_get("uv", uvs)
        return uvs
    return array.array("f", [0.0]) * (total_corners * 2)


def _extract_uvs_tris(
    mesh: Any,
    uv_layer: Optional[Any],
    num_verts: int,
) -> array.array:
    """Extract UV coordinates for arbitrary/triangulated topology."""
    uv_arr = array.array("f", [0.0]) * (num_verts * 2)
    if uv_layer is not None and len(mesh.loops) > 0:
        num_loops = len(mesh.loops)
        loop_uvs = array.array("f", [0.0]) * (num_loops * 2)
        uv_layer.data.foreach_get("uv", loop_uvs)
        loop_vert_indices = array.array("I", [0]) * num_loops
        mesh.loops.foreach_get("vertex_index", loop_vert_indices)
        if HAS_NUMPY:
            np_loop_uvs = np.frombuffer(loop_uvs, dtype=np.float32).reshape(-1, 2)
            np_loop_v_idx = np.frombuffer(loop_vert_indices, dtype=np.uint32)
            np_uv_arr = np.zeros((num_verts, 2), dtype=np.float32)
            np_uv_arr[np_loop_v_idx] = np_loop_uvs
            uv_arr = array.array("f")
            uv_arr.frombytes(np_uv_arr.tobytes())
        else:
            for loop_idx, v_idx in enumerate(loop_vert_indices):
                uv_arr[v_idx * 2] = loop_uvs[loop_idx * 2]
                uv_arr[v_idx * 2 + 1] = loop_uvs[loop_idx * 2 + 1]
    return uv_arr


# =============================================================================
# Attribute Extraction Helpers
# =============================================================================

def _extract_custom_attributes(mesh: Any, mesh_data: Any) -> None:
    """Safely extracts custom attributes with RNA error suppression."""
    if not hasattr(mesh, "attributes"):
        return

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
            continue


# =============================================================================
# Topology Injection Helpers
# =============================================================================

def _inject_topology(
    mesh: Any,
    mesh_data: Any,
    v_count: int,
    is_quad: bool,
    total_indices: int,
    shade_smooth: bool = False,
) -> bool:
    """Rebuilds mesh geometry topology (vertices, loops, polygons) from MeshData indices."""
    if hasattr(mesh.vertices, "add") and hasattr(mesh.loops, "add") and hasattr(mesh.polygons, "add"):
        mesh.clear_geometry()
        mesh.vertices.add(v_count)

        pos_mv = mesh_data.positions_memoryview() if hasattr(mesh_data, "positions_memoryview") else None
        if pos_mv is not None:
            if hasattr(pos_mv, "cast") and pos_mv.format == "B":
                pos_mv = pos_mv.cast("f")
            mesh.vertices.foreach_set("co", pos_mv)
        else:
            mesh.vertices.foreach_set("co", mesh_data.get_flat_positions())

        poly_count = (total_indices // 6) if is_quad else (total_indices // 3)
        stride = 4 if is_quad else 3
        total_loops = poly_count * stride
        mesh.loops.add(total_loops)

        if is_quad:
            quad_mv = mesh_data.quad_indices_memoryview() if hasattr(mesh_data, "quad_indices_memoryview") else None
            if quad_mv is not None:
                if hasattr(quad_mv, "cast") and quad_mv.format == "B":
                    quad_mv = quad_mv.cast("i")
                mesh.loops.foreach_set("vertex_index", quad_mv)
            else:
                mesh.loops.foreach_set("vertex_index", mesh_data.get_quad_indices())
        else:
            indices_mv = mesh_data.indices_memoryview() if hasattr(mesh_data, "indices_memoryview") else None
            if indices_mv is not None:
                if hasattr(indices_mv, "cast") and indices_mv.format == "B":
                    indices_mv = indices_mv.cast("i")
                mesh.loops.foreach_set("vertex_index", indices_mv)
            else:
                mesh.loops.foreach_set("vertex_index", mesh_data.get_indices())

        mesh.polygons.add(poly_count)
        if not shade_smooth:
            mesh.polygons.foreach_set("use_smooth", b"\x00" * poly_count)

        if hasattr(mesh_data, "loop_starts_memoryview"):
            starts_mv = mesh_data.loop_starts_memoryview().cast("i")
            totals_mv = mesh_data.loop_totals_memoryview().cast("i")
            mesh.polygons.foreach_set("loop_start", starts_mv)
            mesh.polygons.foreach_set("loop_total", totals_mv)
        else:
            loop_starts = array.array("i", range(0, total_loops, stride))
            loop_totals = array.array("i", [stride] * poly_count)
            mesh.polygons.foreach_set("loop_start", loop_starts)
            mesh.polygons.foreach_set("loop_total", loop_totals)

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


def _inject_vertex_positions(mesh: Any, mesh_data: Any) -> None:
    """Fast vertex positions injection via MemoryView or flat array."""
    try:
        pos_mv = mesh_data.positions_memoryview()
        if hasattr(pos_mv, "cast") and pos_mv.format == "B":
            pos_mv = pos_mv.cast("f")
        mesh.vertices.foreach_set("co", pos_mv)
    except Exception:
        mesh.vertices.foreach_set("co", mesh_data.get_flat_positions())


def _inject_vertex_normals(mesh: Any, mesh_data: Any) -> None:
    """Vertex normals injection via MemoryView or flat array."""
    try:
        norm_mv = mesh_data.normals_memoryview()
        if hasattr(norm_mv, "cast") and norm_mv.format == "B":
            norm_mv = norm_mv.cast("f")
        mesh.vertices.foreach_set("normal", norm_mv)
    except Exception:
        mesh.vertices.foreach_set("normal", mesh_data.get_flat_normals())


# =============================================================================
# UV & Material Slot Injection Helpers
# =============================================================================

def _inject_uvs(mesh: Any, mesh_data: Any, uv_layer_name: Optional[str] = None) -> None:
    """UV coordinates injection into loop domain."""
    if not hasattr(mesh, "uv_layers") or len(mesh.loops) == 0:
        return

    uv_layer = None
    if uv_layer_name:
        uv_layer = mesh.uv_layers.get(uv_layer_name)
    if uv_layer is None:
        uv_layer = mesh.uv_layers.active or (
            mesh.uv_layers[0] if len(mesh.uv_layers) > 0 else mesh.uv_layers.new(name=uv_layer_name or "UVMap")
        )
    if uv_layer is None:
        return

    num_loops = len(mesh.loops)
    uv_injected = False
    if hasattr(mesh_data, "loop_uvs_memoryview"):
        try:
            loop_uv_mv = mesh_data.loop_uvs_memoryview()
            if hasattr(loop_uv_mv, "cast") and loop_uv_mv.format == "B":
                loop_uv_mv = loop_uv_mv.cast("f")
            if len(loop_uv_mv) == num_loops * 2:
                uv_layer.data.foreach_set("uv", loop_uv_mv)
                uv_injected = True
        except Exception as e:
            logger.debug("Fast loop UV injection fallback: %s", e)

    if not uv_injected:
        uv_mv = mesh_data.uvs_memoryview() if hasattr(mesh_data, "uvs_memoryview") else None
        if uv_mv is not None:
            if hasattr(uv_mv, "cast") and uv_mv.format == "B":
                uv_mv = uv_mv.cast("f")
            if len(uv_mv) == num_loops * 2:
                uv_layer.data.foreach_set("uv", uv_mv)
            else:
                uv_cast = uv_mv.cast("f") if hasattr(uv_mv, "cast") else uv_mv
                loop_vert_indices = array.array("I", [0]) * num_loops
                mesh.loops.foreach_get("vertex_index", loop_vert_indices)
                loop_uv_arr = array.array("f", [0.0]) * (num_loops * 2)
                uv_len = len(uv_cast)
                for loop_idx, v_idx in enumerate(loop_vert_indices):
                    v2 = v_idx * 2
                    if v2 + 1 < uv_len:
                        loop_uv_arr[loop_idx * 2:loop_idx * 2 + 2] = uv_cast[v2:v2 + 2]
                uv_layer.data.foreach_set("uv", loop_uv_arr)
        else:
            uv_flat = mesh_data.get_flat_uvs()
            if len(uv_flat) == num_loops * 2:
                uv_layer.data.foreach_set("uv", uv_flat)
            else:
                loop_vert_indices = array.array("I", [0]) * num_loops
                mesh.loops.foreach_get("vertex_index", loop_vert_indices)
                loop_uv_arr = array.array("f", [0.0]) * (num_loops * 2)
                for loop_idx, v_idx in enumerate(loop_vert_indices):
                    if v_idx * 2 + 1 < len(uv_flat):
                        loop_uv_arr[loop_idx * 2:loop_idx * 2 + 2] = uv_flat[v_idx * 2:v_idx * 2 + 2]
                uv_layer.data.foreach_set("uv", loop_uv_arr)


def _inject_color_attributes(mesh: Any, mesh_data: Any) -> None:
    """Vertex Colors injection (AO / Tint)."""
    if not hasattr(mesh, "color_attributes"):
        return
    try:
        col_mv = mesh_data.colors_memoryview() if hasattr(mesh_data, "colors_memoryview") else None
        if col_mv is not None:
            if hasattr(col_mv, "cast") and col_mv.format == "B":
                col_mv = col_mv.cast("f")
            num_color_elems = len(col_mv) // 4
            if num_color_elems == len(mesh.loops):
                domain = "CORNER"
            elif num_color_elems == len(mesh.vertices):
                domain = "POINT"
            else:
                return
            color_attr = mesh.color_attributes.get("color")
            if color_attr is None or color_attr.domain != domain:
                if color_attr is not None:
                    mesh.color_attributes.remove(color_attr)
                color_attr = mesh.color_attributes.new(name="color", type="FLOAT_COLOR", domain=domain)
            color_attr.data.foreach_set("color", col_mv)
    except Exception:
        pass


def _inject_face_materials(mesh: Any, mesh_data: Any) -> None:
    """Material indices injection for polygons."""
    if not hasattr(mesh, "polygons") or len(mesh.polygons) == 0:
        return
    try:
        mats_mv = mesh_data.face_materials_memoryview() if hasattr(mesh_data, "face_materials_memoryview") else None
        if mats_mv is not None:
            if hasattr(mats_mv, "cast") and mats_mv.format == "B":
                mats_mv = mats_mv.cast("H")
            if len(mats_mv) == len(mesh.polygons):
                mesh.polygons.foreach_set("material_index", mats_mv)
        else:
            face_mats = mesh_data.get_face_materials()
            if len(face_mats) == len(mesh.polygons):
                mat_arr = array.array("H", face_mats)
                mesh.polygons.foreach_set("material_index", mat_arr)
    except Exception as e:
        logger.debug("Failed setting material indices: %s", e)


def _inject_custom_attributes(mesh: Any, mesh_data: Any) -> None:
    """Generic custom attributes synchronization into mesh.attributes."""
    if not hasattr(mesh, "attributes") or not hasattr(mesh_data, "attribute_names"):
        return

    for attr_name in mesh_data.attribute_names():
        try:
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
            if b_attr is not None and (b_attr.data_type != b_type or b_attr.domain != b_domain):
                mesh.attributes.remove(b_attr)
                b_attr = None

            if b_attr is None:
                try:
                    b_attr = mesh.attributes.new(name=attr_name, type=b_type, domain=b_domain)
                except Exception:
                    continue

            if dtype_name.lower() == "string":
                str_vals = mesh_data.get_string_attribute(attr_name)
                if str_vals and len(str_vals) == len(b_attr.data):
                    for i, val in enumerate(str_vals):
                        b_val = val.encode("utf-8") if isinstance(val, str) else bytes(val)
                        try:
                            b_attr.data[i].value = b_val
                        except Exception:
                            try:
                                b_attr.data[i].value = val
                            except Exception:
                                pass
            else:
                mv = mesh_data.attribute_memoryview(attr_name)
                if mv is not None:
                    try:
                        if hasattr(mv, "cast") and mv.format == "B" and typecode:
                            mv = mv.cast(typecode)
                        b_attr.data.foreach_set(value_key, mv)
                    except Exception as e:
                        logger.debug("Failed setting attribute %s: %s", attr_name, e)
        except Exception as e:
            logger.debug("Error injecting attribute %s: %s", attr_name, e)


# =============================================================================
# Standalone Attribute Injection API (Delegation targets for pipeline.py)
# =============================================================================

def _get_or_create_attribute(mesh: Any, name: str, data_type: str, domain: str = "FACE") -> Optional[Any]:
    """Helper to safely get or create a Blender Mesh attribute."""
    if not hasattr(mesh, "attributes"):
        return None
    attr = mesh.attributes.get(name)
    if attr is None:
        try:
            return mesh.attributes.new(name=name, type=data_type, domain=domain)
        except Exception:
            return None
    return attr


def inject_face_attribute_string(mesh: Any, name: str, values: List[str]) -> None:
    """Inject a Face-domain String attribute into Blender Mesh."""
    attr = _get_or_create_attribute(mesh, name, "STRING", "FACE")
    if attr and len(attr.data) == len(values):
        for i, val in enumerate(values):
            b_val = val.encode("utf-8") if isinstance(val, str) else bytes(val)
            try:
                attr.data[i].value = b_val
            except Exception:
                try:
                    attr.data[i].value = val
                except Exception:
                    pass


def inject_face_attribute_int(mesh: Any, name: str, values: Any) -> None:
    """Inject a Face-domain Int attribute into Blender Mesh."""
    attr = _get_or_create_attribute(mesh, name, "INT", "FACE")
    if attr and len(attr.data) == len(values):
        arr = values if isinstance(values, array.array) and values.typecode == "i" else array.array("i", values)
        attr.data.foreach_set("value", arr)


def inject_face_attribute_float(mesh: Any, name: str, values: Any) -> None:
    """Inject a Face-domain Float attribute into Blender Mesh."""
    attr = _get_or_create_attribute(mesh, name, "FLOAT", "FACE")
    if attr and len(attr.data) == len(values):
        arr = values if isinstance(values, array.array) and values.typecode == "f" else array.array("f", values)
        attr.data.foreach_set("value", arr)


def inject_face_attribute_float4(mesh: Any, name: str, flat_values: Any) -> None:
    """Inject a Face-domain Float4/Color attribute into Blender Mesh."""
    attr = _get_or_create_attribute(mesh, name, "FLOAT_COLOR", "FACE")
    if attr and len(attr.data) * 4 == len(flat_values):
        arr = flat_values if isinstance(flat_values, array.array) and flat_values.typecode == "f" else array.array("f", flat_values)
        attr.data.foreach_set("color", arr)


def inject_face_attribute_vector(mesh: Any, name: str, flat_values: Any) -> None:
    """Inject a Face-domain Float Vector attribute into Blender Mesh."""
    attr = _get_or_create_attribute(mesh, name, "FLOAT_VECTOR", "FACE")
    if attr and len(attr.data) * 3 == len(flat_values):
        arr = flat_values if isinstance(flat_values, array.array) and flat_values.typecode == "f" else array.array("f", flat_values)
        attr.data.foreach_set("vector", arr)


def inject_attribute(
    mesh: Any,
    name: str,
    values: Any,
    data_type: str = "FLOAT",
    domain: str = "FACE",
) -> None:
    """Generic attribute injection dispatcher for Blender Mesh attributes."""
    dtype_upper = data_type.upper()
    dom_upper = domain.upper()

    if dom_upper == "FACE":
        if dtype_upper == "STRING":
            inject_face_attribute_string(mesh, name, values)
            return
        elif dtype_upper in ("INT", "INT32", "INT8", "BOOLEAN"):
            inject_face_attribute_int(mesh, name, values)
            return
        elif dtype_upper == "FLOAT":
            inject_face_attribute_float(mesh, name, values)
            return
        elif dtype_upper in ("FLOAT_COLOR", "BYTE_COLOR"):
            inject_face_attribute_float4(mesh, name, values)
            return
        elif dtype_upper in ("FLOAT_VECTOR", "FLOAT3"):
            inject_face_attribute_vector(mesh, name, values)
            return

    attr = _get_or_create_attribute(mesh, name, dtype_upper, dom_upper)
    if not attr:
        return

    if dtype_upper == "STRING" and len(attr.data) == len(values):
        for i, val in enumerate(values):
            b_val = val.encode("utf-8") if isinstance(val, str) else bytes(val)
            try:
                attr.data[i].value = b_val
            except Exception:
                try:
                    attr.data[i].value = val
                except Exception:
                    pass
    elif dtype_upper in ("FLOAT_COLOR", "BYTE_COLOR"):
        attr.data.foreach_set("color", array.array("f", values))
    elif dtype_upper in ("FLOAT_VECTOR", "FLOAT3"):
        attr.data.foreach_set("vector", array.array("f", values))
    elif dtype_upper in ("INT", "INT32", "INT8", "BOOLEAN"):
        attr.data.foreach_set("value", array.array("i", values))
    elif dtype_upper == "FLOAT":
        attr.data.foreach_set("value", array.array("f", values))


# =============================================================================
# Primary Public Bridge Functions
# =============================================================================

def extract_mesh_data(
    mesh_or_obj: Any,
    uv_layer_name: Optional[str] = None,
    include_attributes: bool = True,
    triangulate_if_needed: bool = False,
) -> Any:
    """
    Extracts contiguous geometry and custom attributes from a Blender Mesh into PyMeshData.

    Preserves Quad face topology and per-corner Loop UVs without destroying UV seams.
    """
    if mtk_py is None or not hasattr(mtk_py, "MeshData"):
        raise RuntimeError("mtk_py is not installed or available.")

    mesh = _get_mesh(mesh_or_obj)
    num_polys = len(mesh.polygons)
    num_verts = len(mesh.vertices)
    if num_polys == 0 or num_verts == 0:
        return mtk_py.MeshData()

    uv_layer = None
    if hasattr(mesh, "uv_layers") and len(mesh.uv_layers) > 0:
        if uv_layer_name:
            uv_layer = mesh.uv_layers.get(uv_layer_name)
        if uv_layer is None:
            uv_layer = mesh.uv_layers.active or mesh.uv_layers[0]

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

    mesh_data = mtk_py.MeshData.from_raw_buffers(
        positions=positions,
        uvs=uvs,
        indices=indices,
        normals=normals,
        face_materials=face_mats,
    )

    if include_attributes:
        _extract_custom_attributes(mesh, mesh_data)

    return mesh_data


def inject_mesh_data(
    mesh_data: Any,
    mesh_or_obj: Any,
    uv_layer_name: Optional[str] = None,
    update_topology: bool = False,
    update_normals: bool = False,
    inject_attributes: bool = True,
    shade_smooth: bool = False,
) -> None:
    """
    Injects processed geometry and custom attributes from PyMeshData back into a Blender Mesh.

    Preserves Quad face topology when available.
    """
    if hasattr(mesh_or_obj, "vertex_count") and not hasattr(mesh_data, "vertex_count"):
        mesh_data, mesh_or_obj = mesh_or_obj, mesh_data

    mesh = _get_mesh(mesh_or_obj)
    v_count = getattr(mesh_data, "vertex_count", 0)

    if v_count == 0:
        return

    topology_updated = False
    if update_topology or len(mesh.vertices) != v_count:
        face_count = getattr(mesh_data, "face_count", None)
        if face_count is None:
            face_count = len(mesh_data.get_face_materials()) if hasattr(mesh_data, "get_face_materials") else 0
        tri_count = getattr(mesh_data, "triangle_count", 0)
        total_indices = tri_count * 3
        is_quad = (
            total_indices > 0
            and total_indices % 6 == 0
            and face_count == total_indices // 6
        )
        topology_updated = _inject_topology(mesh, mesh_data, v_count, is_quad, total_indices, shade_smooth)

    if not topology_updated:
        _inject_vertex_positions(mesh, mesh_data)

    if update_normals:
        _inject_vertex_normals(mesh, mesh_data)

    _inject_uvs(mesh, mesh_data, uv_layer_name)
    _inject_color_attributes(mesh, mesh_data)
    _inject_face_materials(mesh, mesh_data)

    if inject_attributes:
        _inject_custom_attributes(mesh, mesh_data)

    mesh.update(calc_edges=topology_updated)

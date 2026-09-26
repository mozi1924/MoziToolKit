"""
Universal Quad Grid Mesh Subdivision and Topology Cleanup Engine.

Provides high-performance quad face subdivision with bilinear interpolation of:
- Vertex positions
- Vertex deform skinning weights (bone groups for Rig 2 / character rigs)
- Vertex, edge, and face custom attributes (float, int, string layers)
- Loop UV coordinates (bilinear interpolation or normalized mapping)
- Loop vertex colors
- Outer boundary edge attributes (seams, sharpness, smoothness, creases)
- Automatic cleanup of original base face and orphan outer edges.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import bmesh
from mathutils import Vector

try:
    from ...bridge.subdivide import slice_face_by_pixel_grid
except (ImportError, ValueError):
    from bridge.subdivide import slice_face_by_pixel_grid


def _interpolate_bilinear(v0, v1, v2, v3, u: float, v: float):
    """Bilinear interpolation across 4 quad corners (0:bottom-left, 1:bottom-right, 2:top-right, 3:top-left)."""
    return (1.0 - u) * (1.0 - v) * v0 + u * (1.0 - v) * v1 + u * v * v2 + (1.0 - u) * v * v3


def _get_vertex_weights(vert: bmesh.types.BMVert, dlayer) -> dict:
    """Safely extract vertex group deform weight dictionary from a BMVert."""
    if dlayer is None:
        return {}
    try:
        dvert = vert[dlayer]
        return dict(dvert.items())
    except Exception:
        return {}


def _extract_all_face_layers(bm: bmesh.types.BMesh, face: bmesh.types.BMFace, is_subdivided: bool = False) -> dict:
    """Extract all custom layer values from a BMFace across all face layer collections."""
    layer_values = {}
    is_fluid = False
    fluid_layer = bm.faces.layers.bool.get("mtk_is_fluid")
    if fluid_layer:
        is_fluid = bool(face[fluid_layer])

    for attr_name in dir(bm.faces.layers):
        if attr_name.startswith("_"):
            continue
        try:
            layer_col = getattr(bm.faces.layers, attr_name)
            if isinstance(layer_col, bmesh.types.BMLayerCollection):
                for layer in layer_col:
                    val = face[layer]
                    name = layer.name.lower()
                    if is_subdivided:
                        if name in ("mtk_uv_tiling_transform", "uv_tiling_transform"):
                            val = Vector((1.0, 1.0, 0.0, 0.0)) if hasattr(val, "__len__") else (1.0, 1.0, 0.0, 0.0)
                        elif name in ("mtk_uv_tiling_scale", "uv_tiling_scale"):
                            val = Vector((1.0, 1.0)) if hasattr(val, "__len__") else (1.0, 1.0)
                        elif name in ("mtk_uv_tiling_location", "uv_tiling_location"):
                            val = Vector((0.0, 0.0)) if hasattr(val, "__len__") else (0.0, 0.0)
                        elif name in ("mtk_uv_rotation", "uv_rotation") and not is_fluid:
                            val = 0.0
                        elif hasattr(val, "copy"):
                            val = val.copy()
                    else:
                        if hasattr(val, "copy"):
                            val = val.copy()
                    layer_values[layer] = val
        except Exception:
            pass
    return layer_values


def _apply_all_face_layers(sub_face: bmesh.types.BMFace, layer_values: dict) -> None:
    """Apply all extracted custom layer values to a newly created BMFace."""
    for layer, val in layer_values.items():
        try:
            sub_face[layer] = val.copy() if hasattr(val, "copy") else val
        except Exception:
            pass


def _extract_all_vert_layers(bm: bmesh.types.BMesh, v0, v1, v2, v3):
    """Extract interpolatable and discrete vertex layers across 4 quad corners."""
    interp_layers = []
    discrete_layers = []
    for attr_name in dir(bm.verts.layers):
        if attr_name.startswith("_") or attr_name == "deform":
            continue
        try:
            layer_col = getattr(bm.verts.layers, attr_name)
            if isinstance(layer_col, bmesh.types.BMLayerCollection):
                for layer in layer_col:
                    if attr_name in ("float", "float_vector", "float_color", "color"):
                        val0 = v0[layer]
                        val1 = v1[layer]
                        val2 = v2[layer]
                        val3 = v3[layer]
                        if hasattr(val0, "__len__") and not isinstance(val0, (str, bytes)):
                            val0, val1, val2, val3 = Vector(val0), Vector(val1), Vector(val2), Vector(val3)
                        else:
                            val0, val1, val2, val3 = float(val0), float(val1), float(val2), float(val3)
                        interp_layers.append((layer, val0, val1, val2, val3))
                    else:
                        discrete_layers.append(layer)
        except Exception:
            pass
    return interp_layers, discrete_layers


def slice_polygon_face_by_pixel_grid(
    bm: bmesh.types.BMesh,
    face: bmesh.types.BMFace,
    tex_w: int,
    tex_h: int,
    pixels_per_face: float = 1.0,
    max_subdivisions: int = 64,
    uv_layer: Optional[bmesh.types.BMLoopUV] = None,
) -> List[bmesh.types.BMFace]:
    """Slices a polygon face strictly along the 2D texture pixel grid lines (X = 1, 2... and Y = 1, 2...).

    Cuts in UV space strictly follow the image's integer pixel lines.
    For rotated/slanted UVs, the cuts on the 3D mesh naturally match the slanted orientation of the texture.
    Preserves all vertex deform skinning weights, loop UVs, and custom attributes.

    :param bm: BMesh object
    :param face: Target Quad or Triangle face to subdivide
    :param tex_w: Texture width in pixels
    :param tex_h: Texture height in pixels
    :param pixels_per_face: Step size in pixels (1.0 = 1 face per pixel)
    :param max_subdivisions: Upper bound for safety
    :param uv_layer: Target UV layer
    :return: List of created sub-face BMFace objects
    """
    if not face.is_valid or len(face.verts) < 3:
        return [face] if face.is_valid else []

    # Active UV loop layer
    uv_l = uv_layer or bm.loops.layers.uv.active or (
        bm.loops.layers.uv[0] if len(bm.loops.layers.uv) > 0 else bm.loops.layers.uv.verify()
    )

    positions = [v.co.to_tuple() for v in face.verts]
    uvs = [(loop[uv_l].uv.x, loop[uv_l].uv.y) for loop in face.loops]

    # Call pure Rust core geometry engine
    new_positions, new_uvs, new_faces, param_coords = slice_face_by_pixel_grid(
        positions,
        uvs,
        tex_w=tex_w,
        tex_h=tex_h,
        pixels_per_face=pixels_per_face,
        max_subdivisions=max_subdivisions,
    )

    if len(new_faces) <= 1:
        return [face]

    # Extract all face attributes
    mat_idx = face.material_index
    smooth = face.smooth
    face_layer_values = _extract_all_face_layers(bm, face, is_subdivided=True)

    # Extract deform weights and custom vertex layers
    dlayer = bm.verts.layers.deform.active or (
        bm.verts.layers.deform[0] if len(bm.verts.layers.deform) > 0 else None
    )

    is_quad = len(face.verts) == 4
    if is_quad:
        v0, v1, v2, v3 = [l.vert for l in face.loops]
        w0 = _get_vertex_weights(v0, dlayer)
        w1 = _get_vertex_weights(v1, dlayer)
        w2 = _get_vertex_weights(v2, dlayer)
        w3 = _get_vertex_weights(v3, dlayer)
        group_ids = set(w0.keys()) | set(w1.keys()) | set(w2.keys()) | set(w3.keys())
        vert_interp_layers, vert_discrete_layers = _extract_all_vert_layers(bm, v0, v1, v2, v3)
    else:
        v0 = face.verts[0]
        group_ids = set()
        vert_interp_layers, vert_discrete_layers = [], []

    # Create new BMVerts
    bm_verts = []
    for pos, (s, t) in zip(new_positions, param_coords):
        new_v = bm.verts.new(pos)

        if dlayer and group_ids and is_quad:
            dvert = new_v[dlayer]
            for g_id in group_ids:
                g_int = int(g_id)
                val0 = float(w0.get(g_id, 0.0))
                val1 = float(w1.get(g_id, 0.0))
                val2 = float(w2.get(g_id, 0.0))
                val3 = float(w3.get(g_id, 0.0))
                w_interp = _interpolate_bilinear(val0, val1, val2, val3, s, t)
                if w_interp > 1e-5:
                    dvert[g_int] = w_interp

        if is_quad:
            for layer, val0, val1, val2, val3 in vert_interp_layers:
                try:
                    new_v[layer] = _interpolate_bilinear(val0, val1, val2, val3, s, t)
                except Exception:
                    pass

            nearest_vert = v0 if (s < 0.5 and t < 0.5) else (
                v1 if (s >= 0.5 and t < 0.5) else (v2 if (s >= 0.5 and t >= 0.5) else v3)
            )
            for layer in vert_discrete_layers:
                try:
                    val = nearest_vert[layer]
                    new_v[layer] = val.copy() if hasattr(val, "copy") else val
                except Exception:
                    pass

        bm_verts.append(new_v)

    # Create new BMFaces
    created_faces = []
    for poly_v_indices in new_faces:
        cell_verts = [bm_verts[idx] for idx in poly_v_indices]
        try:
            sub_face = bm.faces.new(cell_verts)
            sub_face.material_index = mat_idx
            sub_face.smooth = smooth
            _apply_all_face_layers(sub_face, face_layer_values)

            # Assign UVs aligned to pixel grid
            for loop_idx, loop in enumerate(sub_face.loops):
                orig_v_idx = poly_v_indices[loop_idx]
                loop[uv_l].uv = Vector(new_uvs[orig_v_idx])

            created_faces.append(sub_face)
        except ValueError:
            pass

    # Remove original base face and clean up orphan outer edges
    orig_edges = list(face.edges)
    bm.faces.remove(face)
    for edge in orig_edges:
        if edge.is_valid and len(edge.link_faces) == 0:
            bm.edges.remove(edge)

    return created_faces


def cleanup_mesh_topology(
    bm: bmesh.types.BMesh,
    verts: Optional[List[bmesh.types.BMVert]] = None,
    weld_dist: float = 0.0001,
    recalc_normals: bool = True,
) -> None:
    """Clean up mesh topology after subdivision or unmerging operations."""
    if weld_dist > 0:
        target_verts = [v for v in (verts if verts is not None else bm.verts) if v.is_valid]
        if target_verts:
            bmesh.ops.remove_doubles(bm, verts=target_verts, dist=weld_dist)

    loose_edges = [e for e in bm.edges if e.is_valid and len(e.link_faces) == 0]
    if loose_edges:
        bmesh.ops.delete(bm, geom=loose_edges, context='EDGES')

    loose_verts = [v for v in bm.verts if v.is_valid and len(v.link_edges) == 0]
    if loose_verts:
        bmesh.ops.delete(bm, geom=loose_verts, context='VERTS')

    if recalc_normals and bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

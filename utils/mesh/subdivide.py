"""
Universal Quad Grid Mesh Subdivision and Topology Cleanup Engine.

Provides high-performance quad face subdivision with bilinear interpolation of:
- Vertex positions
- Vertex deform skinning weights (bone groups)
- Vertex, edge, and face custom attributes (float, int, string layers)
- Loop UV coordinates (either normalized [0, 1] unit block mapping or bilinear interpolation)
- Loop vertex colors
- Outer boundary edge attributes (seams, sharpness, smoothness, creases)
- Automatic cleanup of original base face and orphan outer edges.
"""

from typing import List, Optional, Tuple, Union
import bmesh
from mathutils import Vector


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


def _get_edge_between(bm, v_a: bmesh.types.BMVert, v_b: bmesh.types.BMVert) -> Optional[bmesh.types.BMEdge]:
    """Find edge connecting v_a and v_b if exists."""
    for edge in v_a.link_edges:
        if edge.other_vert(v_a) == v_b:
            return edge
    return None


def _extract_all_face_layers(bm: bmesh.types.BMesh, face: bmesh.types.BMFace, is_subdivided: bool = False) -> dict:
    """Extract all custom layer values from a BMFace across all face layer collections.

    When is_subdivided is True (cols > 1 or rows > 1), affine UV tiling and rotation metadata
    (mtk_uv_tiling_transform, mtk_uv_tiling_scale, mtk_uv_tiling_location, mtk_uv_rotation)
    are sanitized/reset to identity defaults (Scale=(1,1), Loc=(0,0), Rot=0.0). This ensures
    that all subdivided sub-faces together seamlessly reconstruct a single complete texture
    when materials are replaced or UVs are re-baked, preventing double-rotation or duplicate scaling.
    """
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


def _extract_all_loop_layers(bm: bmesh.types.BMesh, loops):
    """Extract loop layers (excluding UVs) for bilinear interpolation or discrete nearest assignment."""
    interp_layers = {}
    discrete_layers = {}
    for attr_name in dir(bm.loops.layers):
        if attr_name.startswith("_") or attr_name == "uv":
            continue
        try:
            layer_col = getattr(bm.loops.layers, attr_name)
            if isinstance(layer_col, bmesh.types.BMLayerCollection):
                for layer in layer_col:
                    vals = [l[layer] for l in loops]
                    if attr_name in ("color", "float_color", "float_vector", "float"):
                        if hasattr(vals[0], "__len__") and not isinstance(vals[0], (str, bytes)):
                            vals = [Vector(v) for v in vals]
                        else:
                            vals = [float(v) for v in vals]
                        interp_layers[layer] = vals
                    else:
                        discrete_layers[layer] = vals
        except Exception:
            pass
    return interp_layers, discrete_layers


def _extract_edge_attrs(bm: bmesh.types.BMesh, edge: Optional[bmesh.types.BMEdge]) -> dict:
    """Safely extract sharpness, seam, and all custom layer attributes from a BMEdge."""
    if not edge:
        return {"smooth": True, "seam": False, "layers": {}}
    edge_layer_values = {}
    for attr_name in dir(bm.edges.layers):
        if attr_name.startswith("_"):
            continue
        try:
            layer_col = getattr(bm.edges.layers, attr_name)
            if isinstance(layer_col, bmesh.types.BMLayerCollection):
                for layer in layer_col:
                    val = edge[layer]
                    if hasattr(val, "copy"):
                        val = val.copy()
                    edge_layer_values[layer] = val
        except Exception:
            pass
    return {
        "smooth": edge.smooth,
        "seam": edge.seam,
        "layers": edge_layer_values,
    }


def _apply_edge_attrs(edge: bmesh.types.BMEdge, attrs: dict) -> None:
    """Apply extracted edge attributes to a newly created or linked BMEdge."""
    edge.smooth = attrs["smooth"]
    edge.seam = attrs["seam"]
    for layer, val in attrs["layers"].items():
        try:
            edge[layer] = val.copy() if hasattr(val, "copy") else val
        except Exception:
            pass


def subdivide_quad_face(
    bm: bmesh.types.BMesh,
    face: bmesh.types.BMFace,
    cols: int,
    rows: int,
    normalize_uvs: bool = False,
    uv_layer: Optional[bmesh.types.BMLoopUV] = None,
) -> List[bmesh.types.BMFace]:
    """Subdivide a single Quad face into a grid of (cols x rows) quad sub-faces.

    Migrates vertex deform weights, face/vert/edge/loop attributes, UV seams, and sharpness.
    Cleans up the original base face and any orphan edges left behind.

    :param bm: BMesh object
    :param face: Target Quad face to subdivide
    :param cols: Number of horizontal grid subdivisions (>= 1)
    :param rows: Number of vertical grid subdivisions (>= 1)
    :param normalize_uvs: If True, assign [0, 1] local UV coordinates to each sub-quad (for block unmerge);
                          if False, bilinearly interpolate original UV coordinates (for pixel split).
    :param uv_layer: Target UV layer or None to process all UV layers.
    :return: List of created sub-quad BMFace objects
    """
    if not face.is_valid or len(face.verts) != 4:
        return [face] if face.is_valid else []

    if cols <= 1 and rows <= 1:
        if normalize_uvs:
            uv_lays = [uv_layer] if uv_layer else list(bm.loops.layers.uv)
            if not uv_lays:
                uv_lays = [bm.loops.layers.uv.verify()]
            for uv_lay in uv_lays:
                corners = [l[uv_lay].uv.copy() for l in face.loops]
                min_u, max_u = min(c.x for c in corners), max(c.x for c in corners)
                min_v, max_v = min(c.y for c in corners), max(c.y for c in corners)
                span_u, span_v = max_u - min_u, max_v - min_v
                if span_u > 1e-6 and span_v > 1e-6:
                    for loop, c in zip(face.loops, corners):
                        loop[uv_lay].uv = Vector(((c.x - min_u) / span_u, (c.y - min_v) / span_v))
                else:
                    std_uvs = (Vector((0.0, 0.0)), Vector((1.0, 0.0)), Vector((1.0, 1.0)), Vector((0.0, 1.0)))
                    for loop, uv_val in zip(face.loops, std_uvs):
                        loop[uv_lay].uv = uv_val
        return [face]

    # Active UV loop layers
    uv_layers = [uv_layer] if uv_layer else list(bm.loops.layers.uv)
    if not uv_layers:
        uv_layers = [bm.loops.layers.uv.verify()]

    loops = face.loops
    v0, v1, v2, v3 = [l.vert for l in loops]
    p0, p1, p2, p3 = v0.co.copy(), v1.co.copy(), v2.co.copy(), v3.co.copy()

    # Extract UVs and calculate normalized corner orientations for all UV layers
    loop_uv_maps = {}
    norm_uv_maps = {}
    for uv_l in uv_layers:
        corners = [l[uv_l].uv.copy() for l in loops]
        loop_uv_maps[uv_l] = corners
        min_u, max_u = min(c.x for c in corners), max(c.x for c in corners)
        min_v, max_v = min(c.y for c in corners), max(c.y for c in corners)
        span_u, span_v = max_u - min_u, max_v - min_v
        if span_u > 1e-6 and span_v > 1e-6:
            norm_uv_maps[uv_l] = tuple(
                Vector(((c.x - min_u) / span_u, (c.y - min_v) / span_v))
                for c in corners
            )
        else:
            norm_uv_maps[uv_l] = (
                Vector((0.0, 0.0)),
                Vector((1.0, 0.0)),
                Vector((1.0, 1.0)),
                Vector((0.0, 1.0)),
            )

    # Extract non-UV loop custom layers (color, float_color, etc.)
    loop_interp_layers, loop_discrete_layers = _extract_all_loop_layers(bm, loops)

    mat_idx = face.material_index
    smooth = face.smooth

    # 0. Extract all face custom attributes (all layer collections: int, float, string, bool, vector, color, etc.)
    face_layer_values = _extract_all_face_layers(bm, face, is_subdivided=(cols > 1 or rows > 1))

    # 1. Extract 4 outer edge attributes before face deletion
    e01 = _get_edge_between(bm, v0, v1)
    e12 = _get_edge_between(bm, v1, v2)
    e23 = _get_edge_between(bm, v2, v3)
    e30 = _get_edge_between(bm, v3, v0)

    edge_attrs = {
        "bot": _extract_edge_attrs(bm, e01),
        "right": _extract_edge_attrs(bm, e12),
        "top": _extract_edge_attrs(bm, e23),
        "left": _extract_edge_attrs(bm, e30),
    }

    # 2. Extract vertex deform weights and all custom vertex layers
    dlayer = bm.verts.layers.deform.active or (bm.verts.layers.deform[0] if len(bm.verts.layers.deform) > 0 else None)

    w0_dict = _get_vertex_weights(v0, dlayer)
    w1_dict = _get_vertex_weights(v1, dlayer)
    w2_dict = _get_vertex_weights(v2, dlayer)
    w3_dict = _get_vertex_weights(v3, dlayer)
    group_ids = set(w0_dict.keys()) | set(w1_dict.keys()) | set(w2_dict.keys()) | set(w3_dict.keys())

    vert_interp_layers, vert_discrete_layers = _extract_all_vert_layers(bm, v0, v1, v2, v3)

    # 2D Grid of vertices: shape (rows + 1) x (cols + 1)
    grid_verts = [[None for _ in range(cols + 1)] for _ in range(rows + 1)]

    # Populate corner vertices to preserve topology references
    grid_verts[0][0] = v0
    grid_verts[0][cols] = v1
    grid_verts[rows][cols] = v2
    grid_verts[rows][0] = v3

    # Create internal and edge vertices
    for r in range(rows + 1):
        v_factor = r / rows
        for c in range(cols + 1):
            if grid_verts[r][c] is not None:
                continue

            u_factor = c / cols
            pos = _interpolate_bilinear(p0, p1, p2, p3, u_factor, v_factor)
            new_v = bm.verts.new(pos)

            # Interpolate vertex group deform weights
            if dlayer and group_ids:
                dvert = new_v[dlayer]
                for g_id in group_ids:
                    g_int = int(g_id)
                    w0 = float(w0_dict.get(g_id, 0.0))
                    w1 = float(w1_dict.get(g_id, 0.0))
                    w2 = float(w2_dict.get(g_id, 0.0))
                    w3 = float(w3_dict.get(g_id, 0.0))
                    w_interp = _interpolate_bilinear(w0, w1, w2, w3, u_factor, v_factor)
                    if w_interp > 1e-5:
                        dvert[g_int] = w_interp

            # Interpolate continuous vertex layers (float, float_vector, color, float_color)
            for layer, val0, val1, val2, val3 in vert_interp_layers:
                try:
                    new_v[layer] = _interpolate_bilinear(val0, val1, val2, val3, u_factor, v_factor)
                except Exception:
                    pass

            # Transfer discrete vertex layers (int, bool, string) from nearest corner
            nearest_vert = v0 if (u_factor < 0.5 and v_factor < 0.5) else (v1 if (u_factor >= 0.5 and v_factor < 0.5) else (v2 if (u_factor >= 0.5 and v_factor >= 0.5) else v3))
            for layer in vert_discrete_layers:
                try:
                    val = nearest_vert[layer]
                    new_v[layer] = val.copy() if hasattr(val, "copy") else val
                except Exception:
                    pass

            grid_verts[r][c] = new_v

    new_faces = []

    # 3. Create grid quad faces and assign loop & face attributes
    for r in range(rows):
        v_bot = r / rows
        v_top = (r + 1) / rows
        for c in range(cols):
            u_left = c / cols
            u_right = (c + 1) / cols

            cell_verts = (
                grid_verts[r][c],
                grid_verts[r][c + 1],
                grid_verts[r + 1][c + 1],
                grid_verts[r + 1][c],
            )

            try:
                sub_face = bm.faces.new(cell_verts)
                sub_face.material_index = mat_idx
                sub_face.smooth = smooth

                # Transfer all face custom attributes
                _apply_all_face_layers(sub_face, face_layer_values)

                # Assign UV coordinates
                if normalize_uvs:
                    for uv_l, norm_corners in norm_uv_maps.items():
                        for loop, uv_val in zip(sub_face.loops, norm_corners):
                            loop[uv_l].uv = uv_val.copy()
                else:
                    for uv_l, corners in loop_uv_maps.items():
                        c0, c1, c2, c3 = corners
                        cell_uvs = (
                            _interpolate_bilinear(c0, c1, c2, c3, u_left, v_bot),
                            _interpolate_bilinear(c0, c1, c2, c3, u_right, v_bot),
                            _interpolate_bilinear(c0, c1, c2, c3, u_right, v_top),
                            _interpolate_bilinear(c0, c1, c2, c3, u_left, v_top),
                        )
                        for loop, uv_val in zip(sub_face.loops, cell_uvs):
                            loop[uv_l].uv = uv_val

                # Assign interpolated loop layers (color, float_color, float_vector, etc.)
                for layer, corners in loop_interp_layers.items():
                    c0, c1, c2, c3 = corners
                    cell_vals = (
                        _interpolate_bilinear(c0, c1, c2, c3, u_left, v_bot),
                        _interpolate_bilinear(c0, c1, c2, c3, u_right, v_bot),
                        _interpolate_bilinear(c0, c1, c2, c3, u_right, v_top),
                        _interpolate_bilinear(c0, c1, c2, c3, u_left, v_top),
                    )
                    for loop, val in zip(sub_face.loops, cell_vals):
                        try:
                            loop[layer] = val
                        except Exception:
                            pass

                # Assign discrete loop layers (int, bool, string)
                for layer, corners in loop_discrete_layers.items():
                    for loop_idx, loop in enumerate(sub_face.loops):
                        try:
                            val = corners[loop_idx]
                            loop[layer] = val.copy() if hasattr(val, "copy") else val
                        except Exception:
                            pass

                new_faces.append(sub_face)
            except ValueError:
                pass

    # 4. Transfer edge attributes to outer boundary sub-edges
    for r in range(rows):
        for c in range(cols):
            # Bottom boundary sub-edge (r=0)
            if r == 0:
                e_bot = _get_edge_between(bm, grid_verts[0][c], grid_verts[0][c + 1])
                if e_bot:
                    _apply_edge_attrs(e_bot, edge_attrs["bot"])

            # Top boundary sub-edge (r=rows-1)
            if r == rows - 1:
                e_top = _get_edge_between(bm, grid_verts[rows][c], grid_verts[rows][c + 1])
                if e_top:
                    _apply_edge_attrs(e_top, edge_attrs["top"])

            # Left boundary sub-edge (c=0)
            if c == 0:
                e_left = _get_edge_between(bm, grid_verts[r][0], grid_verts[r + 1][0])
                if e_left:
                    _apply_edge_attrs(e_left, edge_attrs["left"])

            # Right boundary sub-edge (c=cols-1)
            if c == cols - 1:
                e_right = _get_edge_between(bm, grid_verts[r][cols], grid_verts[r + 1][cols])
                if e_right:
                    _apply_edge_attrs(e_right, edge_attrs["right"])

    # 5. Remove original base face and clean up orphan outer edges
    orig_edges = list(face.edges)
    bm.faces.remove(face)
    for edge in orig_edges:
        if edge.is_valid and len(edge.link_faces) == 0:
            bm.edges.remove(edge)

    return new_faces


def cleanup_mesh_topology(
    bm: bmesh.types.BMesh,
    verts: Optional[List[bmesh.types.BMVert]] = None,
    weld_dist: float = 0.0001,
    recalc_normals: bool = True,
) -> None:
    """Clean up mesh topology after subdivision or unmerging operations.

    - Welds duplicate boundary vertices within weld_dist.
    - Removes orphan loose edges (0 linked faces).
    - Removes orphan loose vertices (0 linked edges).
    - Recalculates face normals and updates lookup tables.

    :param bm: Target BMesh
    :param verts: Optional list of specific vertices to weld. If None, all valid vertices are considered.
    :param weld_dist: Distance threshold for welding duplicate vertices.
    :param recalc_normals: Whether to recalculate face normals.
    """
    # 1. Weld duplicate vertices
    if weld_dist > 0:
        target_verts = [v for v in (verts if verts is not None else bm.verts) if v.is_valid]
        if target_verts:
            bmesh.ops.remove_doubles(bm, verts=target_verts, dist=weld_dist)

    # 2. Clean up orphan loose edges (0 linked faces)
    loose_edges = [e for e in bm.edges if e.is_valid and len(e.link_faces) == 0]
    if loose_edges:
        bmesh.ops.delete(bm, geom=loose_edges, context='EDGES')

    # 3. Clean up orphan loose vertices (0 linked edges)
    loose_verts = [v for v in bm.verts if v.is_valid and len(v.link_edges) == 0]
    if loose_verts:
        bmesh.ops.delete(bm, geom=loose_verts, context='VERTS')

    # 4. Recalculate face normals and update lookup tables
    if recalc_normals and bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

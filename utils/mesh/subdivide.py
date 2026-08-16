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


def subdivide_quad_face(
    bm: bmesh.types.BMesh,
    face: bmesh.types.BMFace,
    cols: int,
    rows: int,
    normalize_uvs: bool = False,
    uv_layer: Optional[bmesh.types.BMLoopUV] = None,
) -> List[bmesh.types.BMFace]:
    """Subdivide a single Quad face into a grid of (cols x rows) quad sub-faces.

    Migrates vertex deform weights, face/vert/edge attributes, UV seams, and sharpness.
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

    # Active UV loop layers & Color layers
    uv_layers = [uv_layer] if uv_layer else list(bm.loops.layers.uv)
    if not uv_layers:
        uv_layers = [bm.loops.layers.uv.verify()]
    color_layers = list(bm.loops.layers.color) if hasattr(bm.loops.layers, "color") else []

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

    # Extract Loop Colors for all Color layers
    loop_col_maps = {}
    for col_l in color_layers:
        loop_col_maps[col_l] = [Vector(l[col_l]) for l in loops]

    mat_idx = face.material_index
    smooth = face.smooth

    # 0. Extract face custom attributes (Int, Float, Vector, String layers)
    face_float_layers = list(bm.faces.layers.float)
    face_vector_layers = list(bm.faces.layers.float_vector)
    face_int_layers = list(bm.faces.layers.int)
    face_string_layers = list(bm.faces.layers.string)

    face_floats = {l: face[l] for l in face_float_layers}
    face_vectors = {l: Vector(face[l]) for l in face_vector_layers}
    face_ints = {l: face[l] for l in face_int_layers}
    face_strings = {l: face[l] for l in face_string_layers}

    # 1. Extract 4 outer edge attributes before face deletion
    e01 = _get_edge_between(bm, v0, v1)
    e12 = _get_edge_between(bm, v1, v2)
    e23 = _get_edge_between(bm, v2, v3)
    e30 = _get_edge_between(bm, v3, v0)

    edge_float_layers = list(bm.edges.layers.float)
    edge_int_layers = list(bm.edges.layers.int)

    def extract_edge_attrs(edge):
        if not edge:
            return {"smooth": True, "seam": False, "float": {}, "int": {}}
        return {
            "smooth": edge.smooth,
            "seam": edge.seam,
            "float": {l: float(edge[l]) for l in edge_float_layers},
            "int": {l: int(edge[l]) for l in edge_int_layers},
        }

    edge_attrs = {
        "bot": extract_edge_attrs(e01),
        "right": extract_edge_attrs(e12),
        "top": extract_edge_attrs(e23),
        "left": extract_edge_attrs(e30),
    }

    # 2. Extract vertex deform weights and float/int custom attributes
    dlayer = bm.verts.layers.deform.verify() if len(bm.verts.layers.deform) > 0 else None
    vert_float_layers = list(bm.verts.layers.float)
    vert_int_layers = list(bm.verts.layers.int)

    w0_dict = _get_vertex_weights(v0, dlayer)
    w1_dict = _get_vertex_weights(v1, dlayer)
    w2_dict = _get_vertex_weights(v2, dlayer)
    w3_dict = _get_vertex_weights(v3, dlayer)
    group_ids = set(w0_dict.keys()) | set(w1_dict.keys()) | set(w2_dict.keys()) | set(w3_dict.keys())

    v_floats_0 = [float(v0[l]) for l in vert_float_layers]
    v_floats_1 = [float(v1[l]) for l in vert_float_layers]
    v_floats_2 = [float(v2[l]) for l in vert_float_layers]
    v_floats_3 = [float(v3[l]) for l in vert_float_layers]

    v_ints_0 = [int(v0[l]) for l in vert_int_layers]

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

            # Interpolate vertex float custom layers (creases, etc.)
            for idx, fl_layer in enumerate(vert_float_layers):
                val_interp = _interpolate_bilinear(v_floats_0[idx], v_floats_1[idx], v_floats_2[idx], v_floats_3[idx], u_factor, v_factor)
                new_v[fl_layer] = val_interp

            # Transfer vertex int custom layers
            for idx, int_layer in enumerate(vert_int_layers):
                new_v[int_layer] = v_ints_0[idx]

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

                # Transfer face custom attributes (atlas_chunk_id, atlas_texture_id, provenance, etc.)
                for l, val in face_floats.items():
                    sub_face[l] = val
                for l, val in face_vectors.items():
                    sub_face[l] = val
                for l, val in face_ints.items():
                    sub_face[l] = val
                for l, val in face_strings.items():
                    sub_face[l] = val

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

                # Assign interpolated Colors for all Color layers
                for col_l, corners in loop_col_maps.items():
                    c0, c1, c2, c3 = corners
                    cell_cols = (
                        _interpolate_bilinear(c0, c1, c2, c3, u_left, v_bot),
                        _interpolate_bilinear(c0, c1, c2, c3, u_right, v_bot),
                        _interpolate_bilinear(c0, c1, c2, c3, u_right, v_top),
                        _interpolate_bilinear(c0, c1, c2, c3, u_left, v_top),
                    )
                    for loop, col_val in zip(sub_face.loops, cell_cols):
                        loop[col_l] = col_val

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
                    attrs = edge_attrs["bot"]
                    e_bot.smooth = attrs["smooth"]
                    e_bot.seam = attrs["seam"]
                    for l, val in attrs["float"].items():
                        e_bot[l] = val
                    for l, val in attrs["int"].items():
                        e_bot[l] = val

            # Top boundary sub-edge (r=rows-1)
            if r == rows - 1:
                e_top = _get_edge_between(bm, grid_verts[rows][c], grid_verts[rows][c + 1])
                if e_top:
                    attrs = edge_attrs["top"]
                    e_top.smooth = attrs["smooth"]
                    e_top.seam = attrs["seam"]
                    for l, val in attrs["float"].items():
                        e_top[l] = val
                    for l, val in attrs["int"].items():
                        e_top[l] = val

            # Left boundary sub-edge (c=0)
            if c == 0:
                e_left = _get_edge_between(bm, grid_verts[r][0], grid_verts[r + 1][0])
                if e_left:
                    attrs = edge_attrs["left"]
                    e_left.smooth = attrs["smooth"]
                    e_left.seam = attrs["seam"]
                    for l, val in attrs["float"].items():
                        e_left[l] = val
                    for l, val in attrs["int"].items():
                        e_left[l] = val

            # Right boundary sub-edge (c=cols-1)
            if c == cols - 1:
                e_right = _get_edge_between(bm, grid_verts[r][cols], grid_verts[r + 1][cols])
                if e_right:
                    attrs = edge_attrs["right"]
                    e_right.smooth = attrs["smooth"]
                    e_right.seam = attrs["seam"]
                    for l, val in attrs["float"].items():
                        e_right[l] = val
                    for l, val in attrs["int"].items():
                        e_right[l] = val

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

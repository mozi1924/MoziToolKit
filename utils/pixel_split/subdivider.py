import bmesh
from mathutils import Vector
from typing import List, Dict, Tuple, Optional
from .types import TargetGrid


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


def subdivide_quad_face(bm, face: bmesh.types.BMFace, uv_layer, grid: TargetGrid) -> List[bmesh.types.BMFace]:
    """Subdivide a single Quad face into a grid of (cols x rows) quad sub-faces with 1:1 pixel UV mapping
    and full attribute migration (Vertex Weights, Sharp Edges, UV Seams, Edge Creases, Vertex Colors).

    :param bm: BMesh object
    :param face: Target Quad face to subdivide
    :param uv_layer: Active BMesh UV loop layer
    :param grid: TargetGrid specifying cols (Nx) and rows (Ny)
    :return: List of created sub-quad BMFace objects
    """
    if len(face.verts) != 4:
        # Fallback for non-quad faces: return face as-is
        return [face]

    cols, rows = grid.cols, grid.rows
    if cols <= 1 and rows <= 1:
        return [face]

    # Active UV loop layers & Color layers
    uv_layers = list(bm.loops.layers.uv)
    color_layers = list(bm.loops.layers.color) if hasattr(bm.loops.layers, "color") else []

    loops = face.loops
    v0, v1, v2, v3 = [l.vert for l in loops]
    p0, p1, p2, p3 = v0.co.copy(), v1.co.copy(), v2.co.copy(), v3.co.copy()

    # Extract UVs for all UV layers
    loop_uv_maps = {}
    for uv_l in uv_layers:
        loop_uv_maps[uv_l] = [l[uv_l].uv.copy() for l in loops]

    # Extract Loop Colors for all Color layers
    loop_col_maps = {}
    for col_l in color_layers:
        loop_col_maps[col_l] = [Vector(l[col_l]) for l in loops]

    mat_idx = face.material_index
    smooth = face.smooth

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

            grid_verts[r][c] = new_v

    new_faces = []

    # 3. Create grid quad faces and assign loop attributes
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

                # Assign interpolated UVs for all UV layers
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

    # 5. Remove original base face and orphan outer edges
    orig_edges = list(face.edges)
    bm.faces.remove(face)
    for edge in orig_edges:
        if edge.is_valid and len(edge.link_faces) == 0:
            bm.edges.remove(edge)

    return new_faces

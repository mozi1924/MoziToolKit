import bmesh
from mathutils import Vector
from typing import List
from .types import TargetGrid


def _interpolate_bilinear(v0: Vector, v1: Vector, v2: Vector, v3: Vector, u: float, v: float) -> Vector:
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


def subdivide_quad_face(bm, face: bmesh.types.BMFace, uv_layer, grid: TargetGrid) -> List[bmesh.types.BMFace]:
    """Subdivide a single Quad face into a grid of (cols x rows) quad sub-faces with 1:1 pixel UV mapping.

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

    # Active UV loop layer
    uv_layer = bm.loops.layers.uv.active or bm.loops.layers.uv.verify()

    loops = face.loops
    v0, v1, v2, v3 = [l.vert for l in loops]
    p0, p1, p2, p3 = v0.co.copy(), v1.co.copy(), v2.co.copy(), v3.co.copy()
    uv0, uv1, uv2, uv3 = [l[uv_layer].uv.copy() for l in loops]



    mat_idx = face.material_index
    smooth = face.smooth

    # Active deform layer for vertex weights
    dlayer = bm.verts.layers.deform.verify() if len(bm.verts.layers.deform) > 0 else None



    # Extract vertex weight dicts for 4 corners
    w0_dict = _get_vertex_weights(v0, dlayer)
    w1_dict = _get_vertex_weights(v1, dlayer)
    w2_dict = _get_vertex_weights(v2, dlayer)
    w3_dict = _get_vertex_weights(v3, dlayer)
    group_ids = set(w0_dict.keys()) | set(w1_dict.keys()) | set(w2_dict.keys()) | set(w3_dict.keys())

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

            # Interpolate vertex weights across deform groups
            if dlayer and group_ids:
                dvert = new_v[dlayer]
                for g_id in group_ids:
                    g_int = int(g_id)
                    w0 = float(w0_dict.get(g_id, 0.0))
                    w1 = float(w1_dict.get(g_id, 0.0))
                    w2 = float(w2_dict.get(g_id, 0.0))
                    w3 = float(w3_dict.get(g_id, 0.0))
                    w_interp = (
                        (1.0 - u_factor) * (1.0 - v_factor) * w0
                        + u_factor * (1.0 - v_factor) * w1
                        + u_factor * v_factor * w2
                        + (1.0 - u_factor) * v_factor * w3
                    )
                    if w_interp > 1e-5:
                        dvert[g_int] = w_interp

            grid_verts[r][c] = new_v

    new_faces = []

    # Create grid quad faces
    for r in range(rows):
        v_bot = r / rows
        v_top = (r + 1) / rows
        for c in range(cols):
            u_left = c / cols
            u_right = (c + 1) / cols

            # 4 vertices for sub-quad cell
            cell_verts = (
                grid_verts[r][c],
                grid_verts[r][c + 1],
                grid_verts[r + 1][c + 1],
                grid_verts[r + 1][c],
            )

            # Interpolate UVs for sub-quad cell
            cell_uvs = (
                _interpolate_bilinear(uv0, uv1, uv2, uv3, u_left, v_bot),
                _interpolate_bilinear(uv0, uv1, uv2, uv3, u_right, v_bot),
                _interpolate_bilinear(uv0, uv1, uv2, uv3, u_right, v_top),
                _interpolate_bilinear(uv0, uv1, uv2, uv3, u_left, v_top),
            )

            try:
                sub_face = bm.faces.new(cell_verts)
                sub_face.material_index = mat_idx
                sub_face.smooth = smooth

                # Assign loop UV coordinates
                for loop, uv_val in zip(sub_face.loops, cell_uvs):
                    loop[uv_layer].uv = uv_val

                new_faces.append(sub_face)
            except ValueError:
                # Face already exists or invalid geometry
                pass

    # Remove the original base face and any orphan outer edges
    orig_edges = list(face.edges)
    bm.faces.remove(face)
    for edge in orig_edges:
        if edge.is_valid and len(edge.link_faces) == 0:
            bm.edges.remove(edge)

    return new_faces


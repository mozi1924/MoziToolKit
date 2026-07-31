import bmesh
from mathutils import Vector
from typing import List
from .types import TargetGrid


def _interpolate_bilinear(v0: Vector, v1: Vector, v2: Vector, v3: Vector, u: float, v: float) -> Vector:
    """Bilinear interpolation across 4 quad corners (0:bottom-left, 1:bottom-right, 2:top-right, 3:top-left)."""
    return (1.0 - u) * (1.0 - v) * v0 + u * (1.0 - v) * v1 + u * v * v2 + (1.0 - u) * v * v3


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

    # Extract original 4 corners in loop order
    loops = face.loops
    v0, v1, v2, v3 = [l.vert for l in loops]
    p0, p1, p2, p3 = v0.co.copy(), v1.co.copy(), v2.co.copy(), v3.co.copy()
    uv0, uv1, uv2, uv3 = [l[uv_layer].uv.copy() for l in loops]

    mat_idx = face.material_index
    smooth = face.smooth

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
            grid_verts[r][c] = bm.verts.new(pos)

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

    # Remove the original base face
    bm.faces.remove(face)

    return new_faces

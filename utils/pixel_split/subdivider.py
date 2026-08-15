"""
Adaptive Pixel Split Subdivider Bridge.

Delegates quad grid subdivision to universal subdivider in utils.mesh.subdivide.
"""

from typing import List
import bmesh
from .types import TargetGrid
from ..mesh.subdivide import subdivide_quad_face as core_subdivide_quad_face


def subdivide_quad_face(bm: bmesh.types.BMesh, face: bmesh.types.BMFace, uv_layer, grid: TargetGrid) -> List[bmesh.types.BMFace]:
    """Subdivide a single Quad face into a grid of (cols x rows) quad sub-faces with 1:1 pixel UV mapping
    and full attribute migration (Vertex Weights, Sharp Edges, UV Seams, Edge Creases, Vertex Colors).

    :param bm: BMesh object
    :param face: Target Quad face to subdivide
    :param uv_layer: Active BMesh UV loop layer
    :param grid: TargetGrid specifying cols (Nx) and rows (Ny)
    :return: List of created sub-quad BMFace objects
    """
    return core_subdivide_quad_face(
        bm,
        face,
        cols=grid.cols,
        rows=grid.rows,
        normalize_uvs=False,
        uv_layer=uv_layer,
    )

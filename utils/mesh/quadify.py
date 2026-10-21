"""
Triangle-to-quad cleanup for generated meshes.

Runs Blender's ``bmesh.ops.join_triangles`` over a mesh in place. Only triangle
pairs that are coplanar and form a well-shaped quad are joined, and UVs,
materials, seams, sharp edges, and vertex colors must match on both sides, so
the subdivision produced by the pixel splitter is preserved (no quads are
created across pixel cell boundaries).
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

#: Blender's own "Tris to Quads" defaults.
DEFAULT_ANGLE_FACE = math.radians(40.0)
DEFAULT_ANGLE_SHAPE = math.radians(40.0)


def quadify_mesh(
    mesh,
    angle_face: Optional[float] = None,
    angle_shape: Optional[float] = None,
) -> Tuple[int, int, int]:
    """Joins adjacent triangles into quads in place.

    Returns ``(quads_before, quads_after, triangles_remaining)``.
    """
    import bmesh

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        quads_before = sum(1 for face in bm.faces if len(face.verts) == 4)
        triangles = [face for face in bm.faces if len(face.verts) == 3]
        if triangles:
            bmesh.ops.join_triangles(
                bm,
                faces=triangles,
                cmp_seam=True,
                cmp_sharp=True,
                cmp_uvs=True,
                cmp_vcols=True,
                cmp_materials=True,
                angle_face_threshold=(
                    DEFAULT_ANGLE_FACE if angle_face is None else angle_face
                ),
                angle_shape_threshold=(
                    DEFAULT_ANGLE_SHAPE if angle_shape is None else angle_shape
                ),
            )
            bm.to_mesh(mesh)
            mesh.update()

        quads_after = sum(1 for face in bm.faces if len(face.verts) == 4)
        triangles_remaining = sum(1 for face in bm.faces if len(face.verts) == 3)
    finally:
        bm.free()

    return quads_before, quads_after, triangles_remaining


__all__ = ["quadify_mesh", "DEFAULT_ANGLE_FACE", "DEFAULT_ANGLE_SHAPE"]

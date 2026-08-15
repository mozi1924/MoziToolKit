"""
High-Performance Block Grid Unmerge Utility.

Subdivides multi-block optimized quad faces (produced by importers like jmc2obj with
`optimiseGeometry=true`) back into unit 1x1 block quads, and normalizes local UVs to [0, 1]
for proper grid geometry, shader compatibility, pixel subdivision, and texture atlas mapping.
"""

from typing import Tuple, Optional
import bmesh
from .subdivide import subdivide_quad_face, cleanup_mesh_topology


def fast_unmerge_block_quads(
    mesh,
    uv_layer_name: Optional[str] = None,
    uv_span_threshold: float = 1.05
) -> Tuple[int, int]:
    """Subdivide multi-block quad faces with tiled UVs into 1x1 block quads.

    :param mesh: Target Blender Mesh datablock (in Object Mode).
    :param uv_layer_name: Specific UV layer name or None for active UV layer.
    :param uv_span_threshold: Threshold above which a quad's UV span is considered multi-block.
    :return: (large_faces_count, new_sub_faces_count)
    """
    bm = bmesh.new()
    bm.from_mesh(mesh)
    uv_lay = (
        bm.loops.layers.uv.get(uv_layer_name)
        if uv_layer_name
        else (bm.loops.layers.uv.active or bm.loops.layers.uv.verify())
    )

    # 1. Identify large multi-block quad faces
    large_faces_data = []
    for f in bm.faces:
        if len(f.verts) != 4:
            continue
        u_vals = [l[uv_lay].uv.x for l in f.loops]
        v_vals = [l[uv_lay].uv.y for l in f.loops]
        u_span = max(u_vals) - min(u_vals)
        v_span = max(v_vals) - min(v_vals)

        n_u = max(1, int(round(u_span)))
        n_v = max(1, int(round(v_span)))

        if (n_u > 1 or n_v > 1) and (u_span > uv_span_threshold or v_span > uv_span_threshold):
            large_faces_data.append((f, n_u, n_v))

    if not large_faces_data:
        bm.free()
        return 0, 0

    initial_large_count = len(large_faces_data)
    new_sub_faces = []

    # 2. Subdivide each large face using universal quad subdivider
    for f, n_u, n_v in large_faces_data:
        sub_faces = subdivide_quad_face(
            bm,
            f,
            cols=n_u,
            rows=n_v,
            normalize_uvs=True,
            uv_layer=uv_lay,
        )
        new_sub_faces.extend(sub_faces)

    # 3. Clean up mesh topology: weld duplicate boundary vertices and remove orphan loose edges/verts
    sub_verts = list(set(v for f in new_sub_faces if f.is_valid for v in f.verts if v.is_valid))
    cleanup_mesh_topology(bm, verts=sub_verts, weld_dist=0.0001, recalc_normals=True)

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return initial_large_count, len(new_sub_faces)

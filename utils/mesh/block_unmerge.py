"""
High-Performance Block Grid Unmerge Utility.

Subdivides multi-block optimized quad faces (produced by importers like jmc2obj with
`optimiseGeometry=true`) back into unit 1x1 block quads, and normalizes local UVs to [0, 1]
so they map cleanly into Texture Atlas tiles without texture cross-bleeding.
"""

from typing import Tuple, Optional
import bmesh
from mathutils import Vector


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

    face_string_layers = list(bm.faces.layers.string)
    face_float_layers = list(bm.faces.layers.float)
    face_int_layers = list(bm.faces.layers.int)

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
    new_sub_faces_count = 0

    # 2. Process and subdivide each large face
    for f, n_u, n_v in large_faces_data:
        loops = f.loops
        v0, v1, v2, v3 = [l.vert for l in loops]
        p0, p1, p2, p3 = v0.co.copy(), v1.co.copy(), v2.co.copy(), v3.co.copy()

        mat_idx = f.material_index
        smooth = f.smooth
        face_strings = {l: f[l] for l in face_string_layers}
        face_floats = {l: f[l] for l in face_float_layers}
        face_ints = {l: f[l] for l in face_int_layers}

        # Create (n_u + 1) x (n_v + 1) grid vertices
        grid_verts = [[None for _ in range(n_u + 1)] for _ in range(n_v + 1)]
        grid_verts[0][0] = v0
        grid_verts[0][n_u] = v1
        grid_verts[n_v][n_u] = v2
        grid_verts[n_v][0] = v3

        for r in range(n_v + 1):
            v_fac = r / n_v
            for c in range(n_u + 1):
                if grid_verts[r][c] is not None:
                    continue
                u_fac = c / n_u
                # Bilinear position interpolation
                pos = (
                    (1.0 - u_fac) * (1.0 - v_fac) * p0
                    + u_fac * (1.0 - v_fac) * p1
                    + u_fac * v_fac * p2
                    + (1.0 - u_fac) * v_fac * p3
                )
                grid_verts[r][c] = bm.verts.new(pos)

        # Remove the original consolidated large face
        bm.faces.remove(f)

        # Reconstruct sub-quads
        for r in range(n_v):
            for c in range(n_u):
                cell_verts = (
                    grid_verts[r][c],
                    grid_verts[r][c + 1],
                    grid_verts[r + 1][c + 1],
                    grid_verts[r + 1][c],
                )
                try:
                    sub_f = bm.faces.new(cell_verts)
                    sub_f.material_index = mat_idx
                    sub_f.smooth = smooth

                    # Preserve all face custom attributes (provenance, atlas ids, etc.)
                    for l, val in face_strings.items():
                        sub_f[l] = val
                    for l, val in face_floats.items():
                        sub_f[l] = val
                    for l, val in face_ints.items():
                        sub_f[l] = val

                    # Normalized [0, 1] local UV coordinates per sub-block face
                    cell_uvs = (
                        Vector((0.0, 0.0)),
                        Vector((1.0, 0.0)),
                        Vector((1.0, 1.0)),
                        Vector((0.0, 1.0)),
                    )
                    for loop, uv_val in zip(sub_f.loops, cell_uvs):
                        loop[uv_lay].uv = uv_val
                    new_sub_faces_count += 1
                except Exception:
                    pass

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return initial_large_count, new_sub_faces_count

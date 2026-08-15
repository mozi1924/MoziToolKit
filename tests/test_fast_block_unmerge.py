"""High-performance Block Grid Unmerge Benchmark and Logic Test."""

import time
import unittest
import bpy
import bmesh
from mathutils import Vector
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def fast_unmerge_block_quads(mesh, uv_layer_name=None) -> tuple[int, int]:
    """High-performance unmerge of multi-block quad faces with tiled UVs into 1x1 block quads.

    Returns (initial_large_faces_count, new_sub_faces_count).
    """
    bm = bmesh.new()
    bm.from_mesh(mesh)
    uv_lay = bm.loops.layers.uv.get(uv_layer_name) if uv_layer_name else (bm.loops.layers.uv.active or bm.loops.layers.uv.verify())

    face_string_layers = list(bm.faces.layers.string)
    face_float_layers = list(bm.faces.layers.float)
    face_int_layers = list(bm.faces.layers.int)

    # 1. Identify large quad faces
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

        if n_u > 1 or n_v > 1:
            large_faces_data.append((f, n_u, n_v))

    if not large_faces_data:
        bm.free()
        return 0, 0

    initial_large_count = len(large_faces_data)
    new_sub_faces_count = 0

    # 2. Process each large face
    for f, n_u, n_v in large_faces_data:
        loops = f.loops
        v0, v1, v2, v3 = [l.vert for l in loops]
        p0, p1, p2, p3 = v0.co.copy(), v1.co.copy(), v2.co.copy(), v3.co.copy()

        mat_idx = f.material_index
        smooth = f.smooth
        face_strings = {l: f[l] for l in face_string_layers}
        face_floats = {l: f[l] for l in face_float_layers}
        face_ints = {l: f[l] for l in face_int_layers}

        # Grid verts
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
                pos = (1.0 - u_fac) * (1.0 - v_fac) * p0 + u_fac * (1.0 - v_fac) * p1 + u_fac * v_fac * p2 + (1.0 - u_fac) * v_fac * p3
                grid_verts[r][c] = bm.verts.new(pos)

        # Remove original large face
        bm.faces.remove(f)

        # Build sub quads
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


class TestFastBlockUnmerge(unittest.TestCase):
    def test_performance_on_10k_faces(self):
        # Create a mesh with 10,000 faces, including 500 large merged faces
        mesh = bpy.data.meshes.new("BenchmarkMesh")
        bm = bmesh.new()
        uv_lay = bm.loops.layers.uv.new("UVMap")

        # 9500 normal 1x1 faces
        for i in range(95):
            for j in range(100):
                v0 = bm.verts.new((i, j, 0))
                v1 = bm.verts.new((i + 1, j, 0))
                v2 = bm.verts.new((i + 1, j + 1, 0))
                v3 = bm.verts.new((i, j + 1, 0))
                f = bm.faces.new((v0, v1, v2, v3))
                f.loops[0][uv_lay].uv = (0, 0)
                f.loops[1][uv_lay].uv = (1, 0)
                f.loops[2][uv_lay].uv = (1, 1)
                f.loops[3][uv_lay].uv = (0, 1)

        # 500 large 5x5 merged faces
        for k in range(500):
            x = 100 + (k % 25) * 5
            y = (k // 25) * 5
            v0 = bm.verts.new((x, y, 0))
            v1 = bm.verts.new((x + 5, y, 0))
            v2 = bm.verts.new((x + 5, y + 5, 0))
            v3 = bm.verts.new((x, y + 5, 0))
            f = bm.faces.new((v0, v1, v2, v3))
            f.loops[0][uv_lay].uv = (0, 0)
            f.loops[1][uv_lay].uv = (5, 0)
            f.loops[2][uv_lay].uv = (5, 5)
            f.loops[3][uv_lay].uv = (0, 5)

        bm.to_mesh(mesh)
        bm.free()

        t0 = time.time()
        large_count, new_count = fast_unmerge_block_quads(mesh)
        elapsed = time.time() - t0

        print(f"\n[Benchmark] Processed {large_count} large faces -> {new_count} sub-faces in {elapsed*1000:.2f}ms")
        self.assertEqual(large_count, 500)
        self.assertEqual(new_count, 500 * 25)
        self.assertLess(elapsed, 0.5, "10k mesh unmerge must execute in under 500ms")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

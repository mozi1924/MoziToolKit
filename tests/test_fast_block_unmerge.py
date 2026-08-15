"""High-performance Block Grid Unmerge Benchmark, Edge Cleanup, and Logic Test."""

import time
import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import bpy
    import bmesh
    from mathutils import Vector
    from utils.mesh import fast_unmerge_block_quads, subdivide_quad_face, cleanup_mesh_topology
    HAS_BPY = True
except ImportError:
    HAS_BPY = False


@unittest.skipUnless(HAS_BPY, "bpy module is required for test_fast_block_unmerge")
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

    def test_material_and_attribute_preservation(self):
        """Verify unmerging preserves material indices, smooth flags, custom attributes, and local UVs."""
        mesh = bpy.data.meshes.new("UnmergeAttrMesh")
        bm = bmesh.new()
        uv_lay = bm.loops.layers.uv.new("UVMap")
        str_layer = bm.faces.layers.string.new("provenance")
        float_layer = bm.faces.layers.float.new("custom_weight")

        # 1 merged 3x2 face
        v0 = bm.verts.new((0, 0, 0))
        v1 = bm.verts.new((3, 0, 0))
        v2 = bm.verts.new((3, 2, 0))
        v3 = bm.verts.new((0, 2, 0))
        f = bm.faces.new((v0, v1, v2, v3))
        f.material_index = 2
        f.smooth = True
        f[str_layer] = b"minecraft:stone_bricks"
        f[float_layer] = 0.75

        f.loops[0][uv_lay].uv = (0, 0)
        f.loops[1][uv_lay].uv = (3, 0)
        f.loops[2][uv_lay].uv = (3, 2)
        f.loops[3][uv_lay].uv = (0, 2)

        bm.to_mesh(mesh)
        bm.free()

        large_count, new_count = fast_unmerge_block_quads(mesh)
        self.assertEqual(large_count, 1)
        self.assertEqual(new_count, 6)
        self.assertEqual(len(mesh.polygons), 6)

        # Inspect resulting mesh in BMesh
        bm_res = bmesh.new()
        bm_res.from_mesh(mesh)
        uv_res = bm_res.loops.layers.uv.active
        str_res = bm_res.faces.layers.string.get("provenance")
        float_res = bm_res.faces.layers.float.get("custom_weight")

        self.assertIsNotNone(str_res)
        self.assertIsNotNone(float_res)

        for poly in bm_res.faces:
            self.assertEqual(poly.material_index, 2)
            self.assertTrue(poly.smooth)
            self.assertEqual(poly[str_res], b"minecraft:stone_bricks")
            self.assertAlmostEqual(poly[float_res], 0.75, places=4)

            # Local UVs must be within [0, 1]
            u_vals = [l[uv_res].uv.x for l in poly.loops]
            v_vals = [l[uv_res].uv.y for l in poly.loops]
            self.assertAlmostEqual(min(u_vals), 0.0, places=4)
            self.assertAlmostEqual(max(u_vals), 1.0, places=4)
            self.assertAlmostEqual(min(v_vals), 0.0, places=4)
            self.assertAlmostEqual(max(v_vals), 1.0, places=4)

        bm_res.free()

    def test_original_edges_and_loose_geometry_cleaned_up(self):
        """Verify that after unmerging, the original large face edges are cleaned up and no orphan edges or vertices exist."""
        mesh = bpy.data.meshes.new("CleanupEdgeMesh")
        bm = bmesh.new()
        uv_lay = bm.loops.layers.uv.new("UVMap")

        # Create a 4x4 merged quad
        v0 = bm.verts.new((0, 0, 0))
        v1 = bm.verts.new((4, 0, 0))
        v2 = bm.verts.new((4, 4, 0))
        v3 = bm.verts.new((0, 4, 0))
        f = bm.faces.new((v0, v1, v2, v3))
        f.loops[0][uv_lay].uv = (0, 0)
        f.loops[1][uv_lay].uv = (4, 0)
        f.loops[2][uv_lay].uv = (4, 4)
        f.loops[3][uv_lay].uv = (0, 4)

        bm.to_mesh(mesh)
        bm.free()

        large_count, new_count = fast_unmerge_block_quads(mesh)
        self.assertEqual(large_count, 1)
        self.assertEqual(new_count, 16)

        # Inspect resulting topology
        bm_res = bmesh.new()
        bm_res.from_mesh(mesh)

        # Every edge must be linked to at least 1 face (no loose/orphan edges)
        loose_edges = [e for e in bm_res.edges if len(e.link_faces) == 0]
        self.assertEqual(len(loose_edges), 0, f"Found {len(loose_edges)} loose edges that were not cleaned up!")

        # Every vert must be linked to at least 1 edge (no loose vertices)
        loose_verts = [v for v in bm_res.verts if len(v.link_edges) == 0]
        self.assertEqual(len(loose_verts), 0, f"Found {len(loose_verts)} loose vertices!")

        # For a 4x4 grid of quads (5x5 vertices):
        # Expected number of vertices = (4+1)*(4+1) = 25
        # Expected number of faces = 16
        # Expected number of edges = 4*(4+1) + 4*(4+1) = 40
        self.assertEqual(len(bm_res.faces), 16)
        self.assertEqual(len(bm_res.verts), 25)
        self.assertEqual(len(bm_res.edges), 40)

        bm_res.free()


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

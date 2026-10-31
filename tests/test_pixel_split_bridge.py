import _mesh_arrays as ma
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from MoziToolKit.bridge.mesh import MeshData
from MoziToolKit.bridge.engine import get_libmtk
from MoziToolKit.bridge.subdivide import adaptive_pixel_split_mesh
import numpy as np


def calculate_face_target_grid(uvs, tex_w, tex_h, pixels_per_face=1.0, max_subdivisions=64):
    mtk = get_libmtk()
    return mtk.unstable.testing.calculate_face_target_grid(
        [tuple(p) for p in uvs], tex_w, tex_h, pixels_per_face, max_subdivisions
    )


def calculate_pixel_grid_cut_factors(uvs, tex_w, tex_h, pixels_per_face=1.0, max_subdivisions=64):
    mtk = get_libmtk()
    return mtk.unstable.testing.calculate_pixel_grid_cut_factors(
        [tuple(p) for p in uvs], tex_w, tex_h, pixels_per_face, max_subdivisions
    )


def slice_face_by_pixel_grid(positions, uvs, tex_w, tex_h, pixels_per_face=1.0, max_subdivisions=64):
    mtk = get_libmtk()
    return mtk.unstable.testing.slice_face_by_pixel_grid(
        [list(p) for p in positions], [list(u) for u in uvs], tex_w, tex_h, pixels_per_face, max_subdivisions
    )




class TestPixelSplitBridge(unittest.TestCase):

    def test_calculate_face_target_grid_animated_strip(self):
        # 16x512 vertical animated texture
        uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        cols, rows = calculate_face_target_grid(uvs, 16, 512, pixels_per_face=1.0, max_subdivisions=64)
        self.assertEqual(cols, 16)
        self.assertEqual(rows, 16, "Animated water strip must be clamped to single frame square 16x16")

    def test_adaptive_pixel_split_quad_subdivision(self):
        positions = [
            (-0.5, -0.5, 0.0),
            (0.5, -0.5, 0.0),
            (0.5, 0.5, 0.0),
            (-0.5, 0.5, 0.0),
        ]
        quad_uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        mesh = ma.mesh_from_quads(
            [c for p in positions for c in p],
            [[0, 1, 2, 3]],
            [quad_uvs],
            [0],
        )


        # Subdivide 2x2 grid
        subdivided = adaptive_pixel_split_mesh(
            mesh,
            face_resolutions=[(2, 2)],
            default_resolution=(16, 16),
            pixels_per_face=1.0,
            max_subdivisions=64,
            weld_dist=0.0,
        )

        self.assertEqual(subdivided.face_count, 4)
        self.assertEqual(subdivided.triangle_count, 8)
    def test_calculate_face_target_grid_atlas_subregion(self):
        # 16x16 tile inside a 512x512 atlas
        u0, u1 = 32.0 / 512.0, 48.0 / 512.0
        v0, v1 = 64.0 / 512.0, 80.0 / 512.0
        uvs = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
        cols, rows = calculate_face_target_grid(uvs, 512, 512, pixels_per_face=1.0, max_subdivisions=64)
        self.assertEqual(cols, 16)
        self.assertEqual(rows, 16)

    def test_calculate_face_target_grid_rotated_uv(self):
        # 16x16 tile rotated 90 degrees in a 512x512 atlas
        u0, u1 = 32.0 / 512.0, 48.0 / 512.0
        v0, v1 = 64.0 / 512.0, 80.0 / 512.0
        uvs = [(u1, v0), (u1, v1), (u0, v1), (u0, v0)]
        cols, rows = calculate_face_target_grid(uvs, 512, 512, pixels_per_face=1.0, max_subdivisions=64)
        self.assertEqual(cols, 16)
        self.assertEqual(rows, 16)

    def test_calculate_face_target_grid_nonsquare(self):
        # 32x16 tile
        uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        cols, rows = calculate_face_target_grid(uvs, 32, 16, pixels_per_face=1.0, max_subdivisions=64)
        self.assertEqual(cols, 32)
        self.assertEqual(rows, 16)

    def test_adaptive_pixel_split_shared_vertices_preserves_per_loop_uvs(self):
        # 2 adjacent quads sharing 2 vertices with distinct per-loop UVs
        positions = [
            (-1.0, -1.0, 0.0),
            (0.0, -1.0, 0.0),
            (0.0, 0.0, 0.0),
            (-1.0, 0.0, 0.0),
            (1.0, -1.0, 0.0),
            (1.0, 0.0, 0.0),
        ]
        face0_uvs = [(0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)]
        face1_uvs = [(0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)]

        mesh = ma.mesh_from_quads(
            [c for p in positions for c in p],
            [[0, 1, 2, 3], [1, 4, 5, 2]],
            [face0_uvs, face1_uvs],
            [0, 0],
        )

        subdivided = adaptive_pixel_split_mesh(
            mesh,
            face_resolutions=[(4, 2), (4, 2)],
            default_resolution=(4, 2),
            pixels_per_face=1.0,
            max_subdivisions=64,
            weld_dist=1e-4,
        )

        # 2 faces subdivided 2x2 = 8 quads
        self.assertEqual(subdivided.face_count, 8)
        self.assertEqual(subdivided.vertex_count, 15)  # 18 - 3 welded boundary vertices = 15
        loop_uvs = np.frombuffer(subdivided.loop_uvs_memoryview(), dtype=np.float32).reshape(-1, 2)
        self.assertEqual(len(loop_uvs), 32)  # Exactly 4 UVs per quad

        # Verify Face 0 UVs stay in [0.0, 0.5] and Face 1 UVs stay in [0.5, 1.0] (no pretzel tangling)
        self.assertTrue(np.all(loop_uvs[:16, 0] <= 0.5 + 1e-4))
        self.assertTrue(np.all(loop_uvs[16:, 0] >= 0.5 - 1e-4))

    def test_adaptive_pixel_split_rotated_45_uv(self):
        # 45-degree diamond UV on a 3D quad
        positions = [
            (-1.0, -1.0, 0.0),
            (1.0, -1.0, 0.0),
            (1.0, 1.0, 0.0),
            (-1.0, 1.0, 0.0),
        ]
        diamond_uv = [(0.5, 0.0), (1.0, 0.5), (0.5, 1.0), (0.0, 0.5)]
        mesh = ma.mesh_from_quads(
            [c for p in positions for c in p],
            [[0, 1, 2, 3]],
            [diamond_uv],
            [0],
        )

        subdivided = adaptive_pixel_split_mesh(
            mesh,
            face_resolutions=[(16, 16)],
            default_resolution=(16, 16),
            pixels_per_face=1.0,
            max_subdivisions=64,
            weld_dist=0.0,
        )

        self.assertGreater(subdivided.face_count, 20)
        loop_uvs = np.frombuffer(subdivided.loop_uvs_memoryview(), dtype=np.float32).reshape(-1, 2)
        self.assertEqual(len(loop_uvs), len(subdivided.indices_memoryview()))

    def test_slice_face_by_pixel_grid_bridge(self):
        positions = [
            (-1.0, -1.0, 0.0),
            (1.0, -1.0, 0.0),
            (1.0, 1.0, 0.0),
            (-1.0, 1.0, 0.0),
        ]
        diamond_uv = [(0.5, 0.0), (1.0, 0.5), (0.5, 1.0), (0.0, 0.5)]
        pos_out, uv_out, faces_out, param_out = slice_face_by_pixel_grid(
            positions, diamond_uv, 16, 16, 1.0, 64
        )
        self.assertGreater(len(faces_out), 10)
        self.assertEqual(len(pos_out), len(uv_out))


if __name__ == "__main__":
    unittest.main()


import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from bridge.mesh import MeshData
from bridge.subdivide import calculate_face_target_grid, adaptive_pixel_split_mesh




class TestPixelSplitBridge(unittest.TestCase):

    def test_calculate_face_target_grid_animated_strip(self):
        # 16x512 vertical animated texture
        uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        cols, rows = calculate_face_target_grid(uvs, 16, 512, pixels_per_face=1.0, max_subdivisions=64)
        self.assertEqual(cols, 16)
        self.assertEqual(rows, 16, "Animated water strip must be clamped to single frame square 16x16")

    def test_adaptive_pixel_split_quad_subdivision(self):
        mesh = MeshData()
        positions = [
            (-0.5, -0.5, 0.0),
            (0.5, -0.5, 0.0),
            (0.5, 0.5, 0.0),
            (-0.5, 0.5, 0.0),
        ]
        normals = [(0.0, 0.0, 1.0)] * 4
        uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        indices = [0, 1, 2, 0, 2, 3]
        mesh.set_buffers(positions, normals, uvs, indices, [0], [-1])


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


if __name__ == "__main__":
    unittest.main()


"""
Differential test suite comparing Rust (libmtk_py) vs Python UV algorithm implementations.
Ensures 100% mathematical parity and identical results across edge cases.
"""

import math
import random
import sys
import unittest
from pathlib import Path

# Add target/release to sys.path so libmtk_py can be loaded in tests
libmtk_release_path = Path(__file__).resolve().parent.parent.parent / "libmozitoolkit" / "target" / "release"
if libmtk_release_path.exists():
    sys.path.insert(0, str(libmtk_release_path))

import bridge.uv as uv_bridge
from bridge.uv import (
    _py_calculate_uv_area,
    _py_get_uv_bounds,
    _py_get_uv_center,
    _py_is_uv_collapsed,
    _py_is_orthogonal_angle,
    _py_detect_uv_rotation,
    _py_straighten_uv,
    _py_scale_uv,
    _py_normalize_uv_for_atlas_tiling,
    _py_uv_requires_atlas_tiling,
    _py_restore_atlas_tiling_uv,
)

try:
    import libmtk_py as rust_uv
    HAS_RUST_BACKEND = hasattr(rust_uv, "calculate_uv_area")
except ImportError:
    rust_uv = None
    HAS_RUST_BACKEND = False


class TestUvConsistencyRustVsPy(unittest.TestCase):
    def setUp(self):
        random.seed(42)

    def test_rust_backend_available(self):
        self.assertTrue(HAS_RUST_BACKEND, "libmtk_py Rust module must be loaded and available for parity testing")

    def test_calculate_uv_area_consistency(self):
        test_cases = [
            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],  # Standard unit quad
            [(0.0, 0.0), (2.5, 0.0), (2.5, 3.0), (0.0, 3.0)],  # Scaled rectangle
            [(0.1, 0.2), (0.9, 0.4), (0.6, 0.8)],              # Triangle
            [(0.0, 0.0), (1.0, 0.0), (1.0, 0.5), (0.5, 0.5), (0.5, 1.0), (0.0, 1.0)],  # L-shape
            [(0.5, 0.5), (0.5, 0.5), (0.5, 0.5)],              # Degenerate point
            [(0.0, 0.0), (1.0, 1.0)],                          # Line (len < 3)
            [],                                                 # Empty
        ]

        # Generate 50 random polygons
        for _ in range(50):
            num_pts = random.randint(3, 8)
            poly = [(random.uniform(-10.0, 10.0), random.uniform(-10.0, 10.0)) for _ in range(num_pts)]
            test_cases.append(poly)

        for poly in test_cases:
            py_res = _py_calculate_uv_area(poly)
            rust_res = rust_uv.calculate_uv_area(poly)
            self.assertAlmostEqual(py_res, rust_res, places=4, msg=f"Area mismatch on poly: {poly}")

    def test_get_uv_bounds_consistency(self):
        test_cases = [
            [(0.2, 0.3), (0.8, 0.3), (0.8, 0.7), (0.2, 0.7)],
            [(0.0, 0.0)],
            [],
        ]

        for _ in range(50):
            num_pts = random.randint(3, 8)
            poly = [(random.uniform(-5.0, 5.0), random.uniform(-5.0, 5.0)) for _ in range(num_pts)]
            test_cases.append(poly)

        for poly in test_cases:
            py_res = _py_get_uv_bounds(poly)
            rust_res = rust_uv.get_uv_bounds(poly)
            for i in range(6):
                self.assertAlmostEqual(py_res[i], rust_res[i], places=5, msg=f"Bounds index {i} mismatch on {poly}")

    def test_get_uv_center_consistency(self):
        test_cases = [
            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
            [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)],
            [],
        ]

        for _ in range(50):
            num_pts = random.randint(1, 6)
            poly = [(random.uniform(-10.0, 10.0), random.uniform(-10.0, 10.0)) for _ in range(num_pts)]
            test_cases.append(poly)

        for poly in test_cases:
            py_res = _py_get_uv_center(poly)
            rust_res = rust_uv.get_uv_center(poly)
            self.assertAlmostEqual(py_res[0], rust_res[0], places=5)
            self.assertAlmostEqual(py_res[1], rust_res[1], places=5)

    def test_is_uv_collapsed_consistency(self):
        test_cases = [
            ([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)], None, None, None),
            ([(0.5, 0.5), (0.5, 0.5), (0.5, 0.5)], None, None, None),
            ([(0.0, 0.0), (0.00001, 0.0), (0.0, 0.00001)], None, None, None),
            ([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)], 0.05, 0.01, None),
            ([(0.0, 0.0), (0.05, 0.0), (0.05, 0.05), (0.0, 0.05)], None, None, (1.0 / 16.0, 1.0 / 16.0)),
        ]

        for uvs, a_th, d_th, step in test_cases:
            py_res = _py_is_uv_collapsed(uvs, a_th, d_th, step)
            rust_res = rust_uv.is_uv_collapsed(uvs, a_th, d_th, step)
            self.assertEqual(py_res, rust_res, msg=f"Collapse mismatch for {uvs}")

    def test_is_orthogonal_angle_consistency(self):
        test_angles = [
            0.0,
            math.pi / 2.0,
            math.pi,
            -math.pi / 2.0,
            -math.pi,
            math.pi / 4.0,
            math.radians(30.0),
            math.radians(89.999),
            math.radians(90.0001),
        ]

        for angle in test_angles:
            py_res = _py_is_orthogonal_angle(angle, 1e-3)
            rust_res = rust_uv.is_orthogonal_angle(angle, 1e-3)
            self.assertEqual(py_res, rust_res, msg=f"Orthogonal angle mismatch for {angle}")

    def test_detect_uv_rotation_and_straighten_consistency(self):
        # 1. Unrotated quad
        quad = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        self.assertAlmostEqual(_py_detect_uv_rotation(quad), rust_uv.detect_uv_rotation(quad), places=5)

        # 2. 45-degree diamond UV
        diamond = [(0.5, 0.0), (1.0, 0.5), (0.5, 1.0), (0.0, 0.5)]
        py_rot = _py_detect_uv_rotation(diamond)
        rust_rot = rust_uv.detect_uv_rotation(diamond)
        self.assertAlmostEqual(py_rot, rust_rot, places=5)
        self.assertAlmostEqual(abs(rust_rot), math.pi / 4.0, places=4)

        py_str = _py_straighten_uv(diamond)
        rust_str = rust_uv.straighten_uv(diamond)
        self.assertAlmostEqual(py_str[0], rust_str[0], places=5)
        self.assertEqual(py_str[1], rust_str[1])
        self.assertEqual(len(py_str[2]), len(rust_str[2]))
        for (py_u, py_v), (ru_u, ru_v) in zip(py_str[2], rust_str[2]):
            self.assertAlmostEqual(py_u, ru_u, places=5)
            self.assertAlmostEqual(py_v, ru_v, places=5)

    def test_scale_uv_consistency(self):
        quad = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        for factor in [0.1, 0.5, 0.8, 1.0, 2.0, 5.0]:
            py_res = _py_scale_uv(quad, factor)
            rust_res = rust_uv.scale_uv(quad, factor)
            self.assertEqual(len(py_res), len(rust_res))
            for (py_u, py_v), (ru_u, ru_v) in zip(py_res, rust_res):
                self.assertAlmostEqual(py_u, ru_u, places=5)
                self.assertAlmostEqual(py_v, ru_v, places=5)

    def test_atlas_tiling_consistency(self):
        quads = [
            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
            [(-0.5, -0.5), (2.5, -0.5), (2.5, 2.5), (-0.5, 2.5)],
            [(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)],
        ]

        for q in quads:
            py_req = _py_uv_requires_atlas_tiling(q, 1e-4)
            rust_req = rust_uv.uv_requires_atlas_tiling(q, 1e-4)
            self.assertEqual(py_req, rust_req)

            py_norm, py_scale, py_loc = _py_normalize_uv_for_atlas_tiling(q, 1e-6)
            rust_norm, rust_scale, rust_loc = rust_uv.normalize_uv_for_atlas_tiling(q, 1e-6)

            for i in range(3):
                self.assertAlmostEqual(py_scale[i], rust_scale[i], places=5)
                self.assertAlmostEqual(py_loc[i], rust_loc[i], places=5)

            for (py_u, py_v), (ru_u, ru_v) in zip(py_norm, rust_norm):
                self.assertAlmostEqual(py_u, ru_u, places=5)
                self.assertAlmostEqual(py_v, ru_v, places=5)

            # Test reverse reconstruction
            py_restored = _py_restore_atlas_tiling_uv(py_norm[0][0], py_norm[0][1], py_scale, py_loc, 0.0)
            rust_restored = rust_uv.restore_atlas_tiling_uv(rust_norm[0][0], rust_norm[0][1], rust_scale, rust_loc, 0.0)
            self.assertAlmostEqual(py_restored[0], rust_restored[0], places=5)
            self.assertAlmostEqual(py_restored[1], rust_restored[1], places=5)
            self.assertAlmostEqual(py_restored[0], q[0][0], places=5)
            self.assertAlmostEqual(py_restored[1], q[0][1], places=5)


if __name__ == "__main__":
    unittest.main()

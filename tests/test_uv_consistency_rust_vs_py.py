"""
Test suite for UV Bridge algorithms backed by libmtk_py.
Validates area calculation, bounding boxes, centers, angle/rotation detection,
straightening, scaling, and Atlas tiling math.
"""

import math
import random
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

for p in [str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import MoziToolKit.bridge.uv as uv_bridge
from MoziToolKit.bridge.engine import get_libmtk


def is_uv_collapsed(uvs, area_threshold=None, dist_threshold=None, pixel_step=None):
    return get_libmtk().unstable.testing.is_uv_collapsed(uvs, area_threshold, dist_threshold, pixel_step)


def is_orthogonal_angle(angle_rad, tolerance=1e-3):
    return get_libmtk().unstable.testing.is_orthogonal_angle(angle_rad, tolerance)


def detect_uv_rotation(uvs, tolerance=1e-3):
    return get_libmtk().unstable.testing.detect_uv_rotation(uvs, tolerance)


def straighten_uv(uvs, angle=None):
    return get_libmtk().unstable.testing.straighten_uv(uvs, angle)


def normalize_uv_for_atlas_tiling(uvs, epsilon=1e-6):
    return get_libmtk().unstable.testing.normalize_uv_for_atlas_tiling(uvs, epsilon)


def uv_requires_atlas_tiling(uvs, epsilon=1e-4):
    return get_libmtk().unstable.testing.uv_requires_atlas_tiling(uvs, epsilon)


def restore_atlas_tiling_uv(u, v, scale=(1.0, 1.0, 1.0), location=(0.0, 0.0, 0.0), rotation=0.0):
    return get_libmtk().unstable.testing.restore_atlas_tiling_uv(u, v, scale, location, rotation)


class TestUvBridge(unittest.TestCase):
    def setUp(self):
        random.seed(42)

    def test_calculate_uv_area(self):
        # Unit quad
        self.assertAlmostEqual(uv_bridge.calculate_uv_area([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]), 1.0, places=5)
        # Scaled rectangle
        self.assertAlmostEqual(uv_bridge.calculate_uv_area([(0.0, 0.0), (2.5, 0.0), (2.5, 3.0), (0.0, 3.0)]), 7.5, places=5)
        # Degenerate
        self.assertAlmostEqual(uv_bridge.calculate_uv_area([(0.5, 0.5), (0.5, 0.5), (0.5, 0.5)]), 0.0, places=5)
        self.assertAlmostEqual(uv_bridge.calculate_uv_area([(0.0, 0.0), (1.0, 1.0)]), 0.0, places=5)
        self.assertAlmostEqual(uv_bridge.calculate_uv_area([]), 0.0, places=5)

    def test_get_uv_bounds(self):
        quad = [(0.2, 0.3), (0.8, 0.3), (0.8, 0.7), (0.2, 0.7)]
        min_u, min_v, max_u, max_v, span_u, span_v = uv_bridge.get_uv_bounds(quad)
        self.assertAlmostEqual(min_u, 0.2, places=5)
        self.assertAlmostEqual(min_v, 0.3, places=5)
        self.assertAlmostEqual(max_u, 0.8, places=5)
        self.assertAlmostEqual(max_v, 0.7, places=5)
        self.assertAlmostEqual(span_u, 0.6, places=5)
        self.assertAlmostEqual(span_v, 0.4, places=5)

    def test_get_uv_center(self):
        quad = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        cu, cv = uv_bridge.get_uv_center(quad)
        self.assertAlmostEqual(cu, 0.5, places=5)
        self.assertAlmostEqual(cv, 0.5, places=5)

    def test_is_uv_collapsed(self):
        valid_quad = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        collapsed = [(0.5, 0.5), (0.5, 0.5), (0.5, 0.5)]
        tiny_line = [(0.0, 0.0), (0.00001, 0.0), (0.0, 0.00001)]

        self.assertFalse(is_uv_collapsed(valid_quad))
        self.assertTrue(is_uv_collapsed(collapsed))
        self.assertTrue(is_uv_collapsed(tiny_line))

    def test_is_orthogonal_angle(self):
        self.assertTrue(is_orthogonal_angle(0.0))
        self.assertTrue(is_orthogonal_angle(math.pi / 2.0))
        self.assertTrue(is_orthogonal_angle(math.pi))
        self.assertTrue(is_orthogonal_angle(-math.pi / 2.0))
        self.assertFalse(is_orthogonal_angle(math.pi / 4.0))

    def test_detect_uv_rotation_and_straighten(self):
        # Unrotated
        quad = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        self.assertAlmostEqual(detect_uv_rotation(quad), 0.0, places=5)

        # 45-degree diamond
        diamond = [(0.5, 0.0), (1.0, 0.5), (0.5, 1.0), (0.0, 0.5)]
        rot = detect_uv_rotation(diamond)
        self.assertAlmostEqual(abs(rot), math.pi / 4.0, places=4)

        ang, straightened, new_uvs = straighten_uv(diamond)
        self.assertTrue(straightened)
        self.assertAlmostEqual(abs(ang), math.pi / 4.0, places=4)
        self.assertEqual(len(new_uvs), 4)

    def test_scale_uv(self):
        quad = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        scaled = uv_bridge.scale_uv(quad, 0.5)
        self.assertAlmostEqual(scaled[0][0], 0.25, places=5)
        self.assertAlmostEqual(scaled[0][1], 0.25, places=5)
        self.assertAlmostEqual(scaled[2][0], 0.75, places=5)
        self.assertAlmostEqual(scaled[2][1], 0.75, places=5)

    def test_atlas_tiling(self):
        quad = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        self.assertFalse(uv_requires_atlas_tiling(quad))

        large_quad = [(-0.5, -0.5), (2.5, -0.5), (2.5, 2.5), (-0.5, 2.5)]
        self.assertTrue(uv_requires_atlas_tiling(large_quad))

        norm, scale, loc = normalize_uv_for_atlas_tiling(large_quad)
        self.assertEqual(len(norm), 4)
        # Normalization must actually normalize (an identity no-op would pass a round-trip
        # check on its own, so pin the intermediate values).
        self.assertEqual(
            [(round(u, 6), round(v, 6)) for u, v in norm],
            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        )
        self.assertEqual([round(c, 6) for c in scale], [3.0, 3.0, 1.0])
        self.assertEqual([round(c, 6) for c in loc], [0.5, 0.5, 0.0])

        restored = restore_atlas_tiling_uv(norm[0][0], norm[0][1], scale, loc, 0.0)
        self.assertAlmostEqual(restored[0], large_quad[0][0], places=5)
        self.assertAlmostEqual(restored[1], large_quad[0][1], places=5)

        # Rotation must be honoured by restore_atlas_tiling_uv; ignoring it would return
        # (0.5, 0.5) instead of the rotated position of the normalized origin.
        rotated = restore_atlas_tiling_uv(0.0, 0.0, scale, loc, math.pi / 2.0)
        self.assertAlmostEqual(rotated[0], 2.5, places=5)
        self.assertAlmostEqual(rotated[1], -0.5, places=5)


if __name__ == "__main__":
    if "--" in sys.argv:
        argv = [sys.argv[0]] + sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = [sys.argv[0]]
    unittest.main(argv=argv)

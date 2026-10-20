"""Tests for vectorized material-index remapping."""

import unittest

try:
    import numpy as np
except ImportError:
    np = None

from utils.materials.cleaner import remap_indices_lut


class TestRemapIndicesLUT(unittest.TestCase):
    def test_remap_indices_lut_fallback_list(self):
        mapping = {0: 10, 1: 20, 5: 50, 100: 999}
        indices = [0, 1, 5, 2, 100, 0, 7]
        expected = [10, 20, 50, 0, 999, 10, 0]
        self.assertEqual(remap_indices_lut(indices, mapping, default_value=0), expected)

    def test_remap_indices_lut_vectorized(self):
        if np is None:
            self.skipTest("NumPy is required")
        mapping = {0: 10, 1: 20, 5: 50, 100: 999}
        indices = np.array([0, 1, 5, 2, 100, 0, 7], dtype=np.int32)
        expected = np.array([10, 20, 50, 0, 999, 10, 0], dtype=np.int32)
        np.testing.assert_array_equal(
            remap_indices_lut(indices, mapping, default_value=0), expected
        )

    def test_remap_indices_lut_empty_and_fallback(self):
        if np is None:
            self.skipTest("NumPy is required")
        mapping = {1: 10}
        res_empty = remap_indices_lut(np.array([], dtype=np.int32), mapping)
        self.assertEqual(res_empty.size, 0)
        res_neg = remap_indices_lut(
            np.array([-1, 1], dtype=np.int32), mapping, default_value=0
        )
        np.testing.assert_array_equal(res_neg, np.array([0, 10], dtype=np.int32))


if __name__ == "__main__":
    unittest.main()

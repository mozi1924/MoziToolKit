"""
Unit tests for MaxRects 2D rectangle bin packing algorithm.
"""

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Bootstrap MoziToolKit package (also activates the isolated test sandbox)
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from utils.materials.atlas.packer import (
    PackedRect,
    MaxRectsBinPack,
    pack_category_textures,
    next_power_of_two,
)


class TestRectPacker(unittest.TestCase):
    def test_next_power_of_two(self):
        self.assertEqual(next_power_of_two(0), 16)
        self.assertEqual(next_power_of_two(12), 16)
        self.assertEqual(next_power_of_two(16), 16)
        self.assertEqual(next_power_of_two(17), 32)
        self.assertEqual(next_power_of_two(64), 64)
        self.assertEqual(next_power_of_two(65), 128)
        self.assertEqual(next_power_of_two(500), 512)

    def test_packed_rect_properties(self):
        r1 = PackedRect(10, 20, 30, 40, "test1")
        self.assertEqual(r1.right, 40)
        self.assertEqual(r1.bottom, 60)

        # Non-intersecting rect
        r2 = PackedRect(50, 20, 10, 10, "test2")
        self.assertFalse(r1.intersects(r2))

        # Intersecting rect
        r3 = PackedRect(20, 30, 20, 20, "test3")
        self.assertTrue(r1.intersects(r3))

        # Contained rect
        r4 = PackedRect(15, 25, 10, 10, "test4")
        self.assertTrue(r1.contains(r4))
        self.assertFalse(r4.contains(r1))

    def test_maxrects_packing_no_overlap(self):
        """Verify that MaxRectsBinPack places rectangles without any overlap."""
        packer = MaxRectsBinPack(512, 512)
        sizes = [
            ("creeper", 64, 32),
            ("steve", 64, 64),
            ("boat", 128, 64),
            ("horse", 128, 128),
            ("painting1", 32, 16),
            ("painting2", 64, 48),
            ("banner", 64, 64),
            ("chest", 64, 64),
        ]

        placed = []
        for key, w, h in sizes:
            rect = packer.insert(w, h, key=key)
            self.assertIsNotNone(rect, f"Failed to insert {key}")
            self.assertEqual(rect.width, w)
            self.assertEqual(rect.height, h)
            self.assertEqual(rect.key, key)

            # Check within bounds
            self.assertGreaterEqual(rect.x, 0)
            self.assertGreaterEqual(rect.y, 0)
            self.assertLessEqual(rect.right, 512)
            self.assertLessEqual(rect.bottom, 512)

            # Check overlap with previously placed
            for prev in placed:
                self.assertFalse(
                    rect.intersects(prev),
                    f"Rect {rect.key} ({rect.x},{rect.y},{rect.width},{rect.height}) intersects with {prev.key} ({prev.x},{prev.y},{prev.width},{prev.height})"
                )
            placed.append(rect)

        occ_w, occ_h = packer.get_occupancy_dimensions()
        self.assertGreater(occ_w, 0)
        self.assertGreater(occ_h, 0)
        self.assertLessEqual(occ_w, 512)
        self.assertLessEqual(occ_h, 512)

    def test_pack_category_textures_pagination(self):
        """Verify that when rectangles exceed a chunk's capacity, they split into multiple chunks."""
        # 10 items of 128x128 into a max 256x256 chunk (each chunk fits at most 4 items)
        items = [(f"item_{i}", 128, 128) for i in range(10)]
        chunks = pack_category_textures(items, max_chunk_size=256)

        # 10 items / 4 per chunk = 3 chunks (4 + 4 + 2)
        self.assertEqual(len(chunks), 3)

        total_placed = sum(len(placed) for _, _, placed in chunks)
        self.assertEqual(total_placed, 10)

        for chunk_w, chunk_h, placed in chunks:
            self.assertLessEqual(chunk_w, 256)
            self.assertLessEqual(chunk_h, 256)
            # Power of two canvas check
            self.assertEqual(chunk_w & (chunk_w - 1), 0)
            self.assertEqual(chunk_h & (chunk_h - 1), 0)

            for i, r1 in enumerate(placed):
                for j, r2 in enumerate(placed):
                    if i != j:
                        self.assertFalse(r1.intersects(r2))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

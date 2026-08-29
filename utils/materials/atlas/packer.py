"""
High-performance 2D Rectangle Bin Packing (Maximal Rectangles / MaxRects) algorithm
for Minecraft entity textures, paintings, banners, and non-uniform texture atlases.

Ensures zero texture distortion, 100% native aspect ratio preservation,
deterministic placement, and optimal space utilization.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Optional

logger = logging.getLogger("MoziToolKit.Atlas.Packer")


@dataclass(slots=True)
class PackedRect:
    """A 2D rectangle within an atlas coordinate space."""
    x: int
    y: int
    width: int
    height: int
    key: Any = None

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def intersects(self, other: PackedRect) -> bool:
        return not (
            self.right <= other.x
            or self.x >= other.right
            or self.bottom <= other.y
            or self.y >= other.bottom
        )

    def contains(self, other: PackedRect) -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and self.right >= other.right
            and self.bottom >= other.bottom
        )


def next_power_of_two(value: int, min_val: int = 16) -> int:
    """Return the smallest power of two >= value (at least min_val)."""
    val = max(min_val, int(value))
    # If already power of 2
    if val > 0 and (val & (val - 1)) == 0:
        return val
    power = 1
    while power < val:
        power <<= 1
    return power


class MaxRectsBinPack:
    """
    Maximal Rectangles (MaxRects) 2D bin packer using the Best-Short-Side-Fit (BSSF) heuristic.
    Industry standard for packing arbitrary rectangular textures without distortion.
    """

    def __init__(self, width: int, height: int):
        self.bin_width = int(width)
        self.bin_height = int(height)
        self.used_rectangles: list[PackedRect] = []
        self.free_rectangles: list[PackedRect] = [PackedRect(0, 0, self.bin_width, self.bin_height, None)]

    def insert(self, width: int, height: int, key: Any = None) -> Optional[PackedRect]:
        """Insert a single rectangle into the bin, returning the placed PackedRect or None if it does not fit."""
        width = int(width)
        height = int(height)
        if width <= 0 or height <= 0:
            return None

        best_short = float("inf")
        best_long = float("inf")
        best_x = 0
        best_y = 0
        found = False

        # Best-Short-Side-Fit heuristic
        for free in self.free_rectangles:
            if free.width >= width and free.height >= height:
                leftover_horiz = free.width - width
                leftover_vert = free.height - height
                short_side = min(leftover_horiz, leftover_vert)
                long_side = max(leftover_horiz, leftover_vert)

                if short_side < best_short or (short_side == best_short and long_side < best_long):
                    best_short = short_side
                    best_long = long_side
                    best_x = free.x
                    best_y = free.y
                    found = True

        if not found:
            return None

        placed_node = PackedRect(best_x, best_y, width, height, key)

        # Split all free rectangles that intersect with placed_node
        new_free_rects: list[PackedRect] = []
        for free in self.free_rectangles:
            if not free.intersects(placed_node):
                new_free_rects.append(free)
                continue

            # New rectangle at the top
            if placed_node.y > free.y and placed_node.y < free.bottom:
                new_free_rects.append(PackedRect(free.x, free.y, free.width, placed_node.y - free.y, None))

            # New rectangle at the bottom
            if placed_node.bottom < free.bottom and placed_node.bottom > free.y:
                new_free_rects.append(PackedRect(free.x, placed_node.bottom, free.width, free.bottom - placed_node.bottom, None))

            # New rectangle on the left
            if placed_node.x > free.x and placed_node.x < free.right:
                new_free_rects.append(PackedRect(free.x, free.y, placed_node.x - free.x, free.height, None))

            # New rectangle on the right
            if placed_node.right < free.right and placed_node.right > free.x:
                new_free_rects.append(PackedRect(placed_node.right, free.y, free.right - placed_node.right, free.height, None))

        # Prune redundant and contained free rectangles
        pruned_free_rects: list[PackedRect] = []
        for i, r1 in enumerate(new_free_rects):
            if r1.width <= 0 or r1.height <= 0:
                continue
            is_contained = False
            for j, r2 in enumerate(new_free_rects):
                if i != j and r2.contains(r1):
                    is_contained = True
                    break
            if not is_contained:
                pruned_free_rects.append(r1)

        self.free_rectangles = pruned_free_rects
        self.used_rectangles.append(placed_node)
        return placed_node

    def get_occupancy_dimensions(self) -> tuple[int, int]:
        """Return the minimum bounding box (width, height) enclosing all placed rectangles."""
        if not self.used_rectangles:
            return 0, 0
        max_x = max(r.right for r in self.used_rectangles)
        max_y = max(r.bottom for r in self.used_rectangles)
        return max_x, max_y


def pack_category_textures(
    items: list[tuple[Any, int, int]],
    max_chunk_size: int = 2048,
) -> list[tuple[int, int, list[PackedRect]]]:
    """
    Deterministically packs a list of texture items `(key, width, height)` into one or more chunks.

    Returns a list of chunks: `[(chunk_width, chunk_height, [PackedRect, ...]), ...]`.
    Guarantees:
    - Sort order: Height descending, Width descending, Key ascending (strict determinism).
    - Power-of-two canvas size up to `max_chunk_size`.
    - Zero pixel distortion or stretching.
    """
    if not items:
        return []

    # Sort deterministically: tallest first, widest second, stable key third
    sorted_items = sorted(items, key=lambda it: (-it[2], -it[1], str(it[0])))

    # Filter out textures that exceed maximum chunk size and log a warning
    pending = []
    for key, w, h in sorted_items:
        if w > max_chunk_size or h > max_chunk_size:
            logger.warning(
                f"Skipping texture '{key}' ({w}x{h}): exceeds maximum atlas chunk size ({max_chunk_size}px) "
                f"and cannot be packed losslessly."
            )
        else:
            pending.append((key, w, h))

    if not pending:
        return []

    chunks_result: list[tuple[int, int, list[PackedRect]]] = []

    while pending:
        packer = MaxRectsBinPack(max_chunk_size, max_chunk_size)
        placed_in_chunk: list[PackedRect] = []
        unplaced: list[tuple[Any, int, int]] = []

        for key, w, h in pending:
            rect = packer.insert(w, h, key=key)
            if rect is not None:
                placed_in_chunk.append(rect)
            else:
                unplaced.append((key, w, h))

        if not placed_in_chunk:
            # Should not happen because single texture fits within max_chunk_size
            key, w, h = pending[0]
            raise RuntimeError(f"Unable to place texture '{key}' ({w}x{h}) into an empty {max_chunk_size}px bin.")

        occ_w, occ_h = packer.get_occupancy_dimensions()
        chunk_w = next_power_of_two(occ_w)
        chunk_h = next_power_of_two(occ_h)

        chunks_result.append((chunk_w, chunk_h, placed_in_chunk))
        pending = unplaced

    return chunks_result

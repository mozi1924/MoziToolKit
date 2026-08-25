"""
VoxelStorage for MoziToolKit Live Sync.
Stores 3D voxel grid state, palette indexing, delta updates, and CRC32 section hashing.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Tuple
import zlib

logger = logging.getLogger("MoziToolKit.LiveSync")


def block_key(x: int, y: int, z: int) -> str:
    """Return canonical absolute-coordinate block key (e.g. '0,64,0')."""
    return f"{int(x)},{int(y)},{int(z)}"


class VoxelStorage:
    """In-memory 3D sparse/dense voxel array with section-based CRC32 validation."""

    def __init__(self) -> None:
        self.min_x: int = 0
        self.min_y: int = 0
        self.min_z: int = 0
        self.size_x: int = 0
        self.size_y: int = 0
        self.size_z: int = 0
        self.block_map: Dict[Tuple[int, int, int], str] = {}  # (abs_x, abs_y, abs_z) -> state_str
        self.section_crc_map: Dict[Tuple[int, int, int], int] = {}  # (sec_x, sec_y, sec_z) -> uint32 crc
        self._dirty_sections: Set[Tuple[int, int, int]] = set()
        self.generation: int = 0

    def clear(self) -> None:
        """Clear all stored voxel and section data."""
        self.block_map.clear()
        self.section_crc_map.clear()
        self._dirty_sections.clear()
        self.min_x = self.min_y = self.min_z = 0
        self.size_x = self.size_y = self.size_z = 0
        self.generation += 1

    def matches_bounds(self, min_x: int, min_y: int, min_z: int) -> bool:
        """Check if an incoming packet matches active selection bounds origin."""
        return (
            self.size_x > 0 and self.size_y > 0 and self.size_z > 0
            and (self.min_x, self.min_y, self.min_z) == (min_x, min_y, min_z)
        )

    def contains(self, x: int, y: int, z: int) -> bool:
        """Check if coordinate is within current bounds."""
        return (
            self.min_x <= x < self.min_x + self.size_x
            and self.min_y <= y < self.min_y + self.size_y
            and self.min_z <= z < self.min_z + self.size_z
        )

    def get_block(self, x: int, y: int, z: int) -> Optional[str]:
        """Get blockstate string at (x, y, z)."""
        return self.block_map.get((x, y, z))

    def set_block(self, x: int, y: int, z: int, state_str: str) -> None:
        """Set blockstate string at (x, y, z), expanding storage bounds if needed."""
        self.block_map[(x, y, z)] = state_str
        if self.size_x == 0 or self.size_y == 0 or self.size_z == 0:
            self.min_x, self.min_y, self.min_z = x, y, z
            self.size_x, self.size_y, self.size_z = 1, 1, 1
        else:
            max_x = max(self.min_x + self.size_x - 1, x)
            max_y = max(self.min_y + self.size_y - 1, y)
            max_z = max(self.min_z + self.size_z - 1, z)
            self.min_x = min(self.min_x, x)
            self.min_y = min(self.min_y, y)
            self.min_z = min(self.min_z, z)
            self.size_x = max_x - self.min_x + 1
            self.size_y = max_y - self.min_y + 1
            self.size_z = max_z - self.min_z + 1
        self.generation += 1

    def set_full_snapshot(
        self,
        min_x: int, min_y: int, min_z: int,
        size_x: int, size_y: int, size_z: int,
        palette: List[str],
        grid_indices: List[int],
    ) -> int:
        """Populate storage from a full snapshot binary packet."""
        self.min_x, self.min_y, self.min_z = min_x, min_y, min_z
        self.size_x, self.size_y, self.size_z = size_x, size_y, size_z
        self.block_map.clear()
        self.section_crc_map.clear()
        self._dirty_sections.clear()
        self.generation += 1

        total_blocks = size_x * size_y * size_z
        palette_len = len(palette)
        for idx in range(min(total_blocks, len(grid_indices))):
            palette_idx = grid_indices[idx]
            if 0 <= palette_idx < palette_len:
                state_str = palette[palette_idx]
                rem = idx % (size_y * size_z)
                x = idx // (size_y * size_z)
                y = rem // size_z
                z = rem % size_z

                abs_x = min_x + x
                abs_y = min_y + y
                abs_z = min_z + z
                self.block_map[(abs_x, abs_y, abs_z)] = state_str

        self.recalculate_all_section_crcs()
        return self.generation

    def set_section_snapshot(
        self,
        sec_x: int, sec_y: int, sec_z: int,
        start_x: int, start_y: int, start_z: int,
        size_x: int, size_y: int, size_z: int,
        palette: List[str],
        grid_indices: List[int],
    ) -> bool:
        """Update a specific 16x16x16 section from a section repair snapshot."""
        if not self.matches_bounds(self.min_x, self.min_y, self.min_z):
            return False
        if size_x <= 0 or size_y <= 0 or size_z <= 0:
            return False

        total_blocks = size_x * size_y * size_z
        max_x = self.min_x + self.size_x - 1
        max_y = self.min_y + self.size_y - 1
        max_z = self.min_z + self.size_z - 1

        expected_start = (
            max(self.min_x, sec_x << 4),
            max(self.min_y, sec_y << 4),
            max(self.min_z, sec_z << 4),
        )
        expected_end = (
            min(max_x, (sec_x << 4) + 15),
            min(max_y, (sec_y << 4) + 15),
            min(max_z, (sec_z << 4) + 15),
        )
        expected_size = tuple(max(0, end - start + 1) for start, end in zip(expected_start, expected_end))

        if (start_x, start_y, start_z) != expected_start or (size_x, size_y, size_z) != expected_size:
            logger.warning("Discarded section snapshot with unexpected bounds for (%d, %d, %d)", sec_x, sec_y, sec_z)
            return False

        palette_len = len(palette)
        if len(grid_indices) < total_blocks or any(idx < 0 or idx >= palette_len for idx in grid_indices[:total_blocks]):
            logger.warning("Discarded malformed section snapshot for (%d, %d, %d)", sec_x, sec_y, sec_z)
            return False

        for idx in range(total_blocks):
            palette_idx = grid_indices[idx]
            state_str = palette[palette_idx]
            rem = idx % (size_y * size_z)
            x = idx // (size_y * size_z)
            y = rem // size_z
            z = rem % size_z

            abs_x = start_x + x
            abs_y = start_y + y
            abs_z = start_z + z
            self.block_map[(abs_x, abs_y, abs_z)] = state_str

        self._dirty_sections.discard((sec_x, sec_y, sec_z))
        self.calculate_and_store_section_crc(sec_x, sec_y, sec_z)
        return True

    def apply_delta_update(
        self,
        min_x: int, min_y: int, min_z: int,
        changes: List[Tuple[int, int, int, str]],
    ) -> bool:
        """Apply incremental delta changes to voxel storage."""
        if not self.matches_bounds(min_x, min_y, min_z):
            logger.warning("Discarded delta for stale selection bounds (%d, %d, %d)", min_x, min_y, min_z)
            return False
        if any(not self.contains(x, y, z) for x, y, z, _state in changes):
            logger.warning("Discarded delta containing coordinates outside active selection")
            return False

        changed = False
        for abs_x, abs_y, abs_z, state_str in changes:
            key = (abs_x, abs_y, abs_z)
            if self.block_map.get(key) == state_str:
                continue
            self.block_map[key] = state_str
            self._dirty_sections.add((abs_x >> 4, abs_y >> 4, abs_z >> 4))
            changed = True

        return changed

    def calculate_and_store_section_crc(self, sec_x: int, sec_y: int, sec_z: int) -> int:
        """Compute CRC32 for a single 16x16x16 chunk section."""
        max_x = self.min_x + self.size_x - 1
        max_y = self.min_y + self.size_y - 1
        max_z = self.min_z + self.size_z - 1

        start_x = max(self.min_x, sec_x << 4)
        end_x = min(max_x, (sec_x << 4) + 15)
        start_y = max(self.min_y, sec_y << 4)
        end_y = min(max_y, (sec_y << 4) + 15)
        start_z = max(self.min_z, sec_z << 4)
        end_z = min(max_z, (sec_z << 4) + 15)

        crc_val = 0
        for x in range(start_x, end_x + 1):
            for y in range(start_y, end_y + 1):
                for z in range(start_z, end_z + 1):
                    state_str = self.block_map.get((x, y, z), "minecraft:air")
                    crc_val = zlib.crc32(state_str.encode("utf-8"), crc_val)

        unsigned_crc = crc_val & 0xFFFFFFFF
        self.section_crc_map[(sec_x, sec_y, sec_z)] = unsigned_crc
        return unsigned_crc

    def recalculate_all_section_crcs(self) -> None:
        """Recompute CRC32 across all sections in current bounds."""
        self.section_crc_map.clear()
        self._dirty_sections.clear()
        if self.size_x == 0 or self.size_y == 0 or self.size_z == 0:
            return

        max_x = self.min_x + self.size_x - 1
        max_y = self.min_y + self.size_y - 1
        max_z = self.min_z + self.size_z - 1

        min_sec_x, max_sec_x = self.min_x >> 4, max_x >> 4
        min_sec_y, max_sec_y = self.min_y >> 4, max_y >> 4
        min_sec_z, max_sec_z = self.min_z >> 4, max_z >> 4

        for sx in range(min_sec_x, max_sec_x + 1):
            for sy in range(min_sec_y, max_sec_y + 1):
                for sz in range(min_sec_z, max_sec_z + 1):
                    self.calculate_and_store_section_crc(sx, sy, sz)

    def validate_manifest(self, server_sections: List[Tuple[int, int, int, int]]) -> List[Tuple[int, int, int]]:
        """Compare server CRC32 hashes with local ones and return mismatched section coords."""
        mismatched = []
        for sec_x, sec_y, sec_z, server_crc32 in server_sections:
            key = (sec_x, sec_y, sec_z)
            if key in self._dirty_sections or key not in self.section_crc_map:
                self.calculate_and_store_section_crc(sec_x, sec_y, sec_z)
                self._dirty_sections.discard(key)
            local_crc = self.section_crc_map.get(key, None)
            if local_crc != server_crc32:
                mismatched.append(key)
        return mismatched


# Global singleton instance for live syncing in Blender session
voxel_storage = VoxelStorage()

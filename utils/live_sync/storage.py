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


def _extract_canonical_state_str(raw_state: str) -> str:
    """Extract canonical Minecraft blockstate string from raw or JSON-wrapped state string."""
    if not raw_state:
        return "minecraft:air"
    if raw_state.startswith('{"state":"'):
        end_idx = raw_state.find('"', 10)
        if end_idx != -1:
            return raw_state[10:end_idx]
    elif raw_state.startswith("{"):
        try:
            import json
            data = json.loads(raw_state)
            if isinstance(data, dict) and "state" in data:
                return str(data["state"])
        except Exception:
            pass
    return raw_state


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
        self._state_counts: Dict[str, int] = {}
        self.section_crc_map: Dict[Tuple[int, int, int], int] = {}  # (sec_x, sec_y, sec_z) -> uint32 crc
        self._dirty_sections: Set[Tuple[int, int, int]] = set()
        self.generation: int = 0

    def clear(self) -> None:
        """Clear all stored voxel and section data."""
        self.block_map.clear()
        self._state_counts.clear()
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

    def get_dirty_sections(self) -> Set[Tuple[int, int, int]]:
        """Return the set of dirty section coordinates that need mesh regeneration."""
        return set(self._dirty_sections)

    def clear_dirty_sections(self) -> None:
        """Clear the set of dirty sections after mesh synchronization."""
        self._dirty_sections.clear()

    def mark_all_sections_dirty(self) -> None:
        """Mark all sections within current bounds as dirty for a full rebuild."""
        self._dirty_sections.clear()
        if self.size_x == 0 or self.size_y == 0 or self.size_z == 0:
            return
        min_sec_x, max_sec_x = self.min_x >> 4, (self.min_x + self.size_x - 1) >> 4
        min_sec_y, max_sec_y = self.min_y >> 4, (self.min_y + self.size_y - 1) >> 4
        min_sec_z, max_sec_z = self.min_z >> 4, (self.min_z + self.size_z - 1) >> 4
        for sx in range(min_sec_x, max_sec_x + 1):
            for sy in range(min_sec_y, max_sec_y + 1):
                for sz in range(min_sec_z, max_sec_z + 1):
                    self._dirty_sections.add((sx, sy, sz))

    def get_all_sections(self) -> Set[Tuple[int, int, int]]:
        """Return all section coordinates that contain at least one non-air voxel."""
        sections = set()
        air_names = {"", "minecraft:air", "air", "minecraft:cave_air", "minecraft:void_air", "minecraft:structure_void"}
        for (x, y, z), state in self.block_map.items():
            if state and state not in air_names and not state.startswith("minecraft:air"):
                sections.add((x >> 4, y >> 4, z >> 4))
        return sections

    def get_section_blocks(self, sec_x: int, sec_y: int, sec_z: int) -> Dict[Tuple[int, int, int], str]:
        """Return all (abs_x, abs_y, abs_z) -> state_str within the given 16x16x16 section."""
        start_x = sec_x << 4
        start_y = sec_y << 4
        start_z = sec_z << 4
        result = {}
        for x in range(start_x, start_x + 16):
            for y in range(start_y, start_y + 16):
                for z in range(start_z, start_z + 16):
                    state = self.block_map.get((x, y, z))
                    if state is not None:
                        result[(x, y, z)] = state
        return result

    def get_state_counts(self) -> Dict[str, int]:
        """Return canonical dictionary of state_str -> count across active blocks."""
        if not self._state_counts and self.block_map:
            from collections import Counter
            self._state_counts = dict(Counter(self.block_map.values()))
        return self._state_counts

    def set_block(self, x: int, y: int, z: int, state_str: str) -> None:
        """Set blockstate string at (x, y, z), expanding storage bounds if needed and marking dirty sections."""
        old_state = self.block_map.get((x, y, z))
        if old_state == state_str:
            return
        if old_state:
            self._state_counts[old_state] = self._state_counts.get(old_state, 1) - 1
            if self._state_counts[old_state] <= 0:
                self._state_counts.pop(old_state, None)

        self.block_map[(x, y, z)] = state_str
        self._state_counts[state_str] = self._state_counts.get(state_str, 0) + 1

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

        sx, sy, sz = x >> 4, y >> 4, z >> 4
        self._dirty_sections.add((sx, sy, sz))
        if (x & 15) == 0:
            self._dirty_sections.add((sx - 1, sy, sz))
        elif (x & 15) == 15:
            self._dirty_sections.add((sx + 1, sy, sz))
        if (y & 15) == 0:
            self._dirty_sections.add((sx, sy - 1, sz))
        elif (y & 15) == 15:
            self._dirty_sections.add((sx, sy + 1, sz))
        if (z & 15) == 0:
            self._dirty_sections.add((sx, sy, sz - 1))
        elif (z & 15) == 15:
            self._dirty_sections.add((sx, sy, sz + 1))
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
        self._state_counts.clear()
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
                self._state_counts[state_str] = self._state_counts.get(state_str, 0) + 1

        self.recalculate_all_section_crcs()
        return self.generation

    def is_snapshot_identical(
        self,
        min_x: int, min_y: int, min_z: int,
        size_x: int, size_y: int, size_z: int,
        palette: List[str],
        grid_indices: List[int],
    ) -> bool:
        """Check if incoming full snapshot matches current in-memory block_map without mutating state."""
        if (
            self.min_x != min_x or self.min_y != min_y or self.min_z != min_z
            or self.size_x != size_x or self.size_y != size_y or self.size_z != size_z
        ):
            return False
        if not self.block_map:
            return False

        total_blocks = size_x * size_y * size_z
        palette_len = len(palette)
        if len(grid_indices) < total_blocks:
            return False

        idx = 0
        for x in range(size_x):
            for y in range(size_y):
                for z in range(size_z):
                    palette_idx = grid_indices[idx]
                    idx += 1
                    if palette_idx < 0 or palette_idx >= palette_len:
                        return False
                    expected_state = palette[palette_idx]
                    current_state = self.block_map.get((min_x + x, min_y + y, min_z + z), "")
                    if current_state != expected_state:
                        return False
        return True

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
            key = (abs_x, abs_y, abs_z)
            old_state = self.block_map.get(key)
            if old_state != state_str:
                if old_state:
                    self._state_counts[old_state] = self._state_counts.get(old_state, 1) - 1
                    if self._state_counts[old_state] <= 0:
                        self._state_counts.pop(old_state, None)
                self.block_map[key] = state_str
                self._state_counts[state_str] = self._state_counts.get(state_str, 0) + 1

        self._dirty_sections.discard((sec_x, sec_y, sec_z))
        self.calculate_and_store_section_crc(sec_x, sec_y, sec_z)
        return True

    def apply_delta_update(
        self,
        min_x: int, min_y: int, min_z: int,
        changes: List[Tuple[int, int, int, str]],
    ) -> bool:
        """Apply incremental delta changes to voxel storage, tracking dirty sections and boundary neighbors."""
        if not self.matches_bounds(min_x, min_y, min_z):
            logger.warning("Discarded delta for stale selection bounds (%d, %d, %d)", min_x, min_y, min_z)
            return False
        if any(not self.contains(x, y, z) for x, y, z, _state in changes):
            logger.warning("Discarded delta containing coordinates outside active selection")
            return False

        changed = False
        for abs_x, abs_y, abs_z, state_str in changes:
            key = (abs_x, abs_y, abs_z)
            old_state = self.block_map.get(key)
            if old_state == state_str:
                continue
            if old_state:
                self._state_counts[old_state] = self._state_counts.get(old_state, 1) - 1
                if self._state_counts[old_state] <= 0:
                    self._state_counts.pop(old_state, None)
            self.block_map[key] = state_str
            self._state_counts[state_str] = self._state_counts.get(state_str, 0) + 1

            sx, sy, sz = abs_x >> 4, abs_y >> 4, abs_z >> 4
            self._dirty_sections.add((sx, sy, sz))

            # Check boundary conditions and mark adjacent section dirty for face culling consistency
            if (abs_x & 15) == 0:
                self._dirty_sections.add((sx - 1, sy, sz))
            elif (abs_x & 15) == 15:
                self._dirty_sections.add((sx + 1, sy, sz))
            if (abs_y & 15) == 0:
                self._dirty_sections.add((sx, sy - 1, sz))
            elif (abs_y & 15) == 15:
                self._dirty_sections.add((sx, sy + 1, sz))
            if (abs_z & 15) == 0:
                self._dirty_sections.add((sx, sy, sz - 1))
            elif (abs_z & 15) == 15:
                self._dirty_sections.add((sx, sy, sz + 1))

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
                    raw_state = self.block_map.get((x, y, z), "minecraft:air")
                    state_str = _extract_canonical_state_str(raw_state)
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
            local_crc = self.section_crc_map.get(key, None)
            if local_crc != server_crc32:
                mismatched.append(key)
        return mismatched

    def export_manifest_metadata(self) -> dict:
        """Export current bounds and section CRC map for scene/object persistence."""
        crc_export = {}
        for (sx, sy, sz), crc_val in self.section_crc_map.items():
            crc_export[f"{sx},{sy},{sz}"] = crc_val
        return {
            "min_x": self.min_x,
            "min_y": self.min_y,
            "min_z": self.min_z,
            "size_x": self.size_x,
            "size_y": self.size_y,
            "size_z": self.size_z,
            "generation": self.generation,
            "section_crcs": crc_export,
        }

    def import_manifest_metadata(self, data: dict) -> bool:
        """Import bounds and section CRC map from serialized persistent scene/object data."""
        if not isinstance(data, dict):
            return False
        try:
            self.min_x = int(data.get("min_x", 0))
            self.min_y = int(data.get("min_y", 0))
            self.min_z = int(data.get("min_z", 0))
            self.size_x = int(data.get("size_x", 0))
            self.size_y = int(data.get("size_y", 0))
            self.size_z = int(data.get("size_z", 0))
            self.generation = int(data.get("generation", 0))
            crc_data = data.get("section_crcs", {})
            self.section_crc_map.clear()
            if isinstance(crc_data, dict):
                for k, v in crc_data.items():
                    parts = k.split(",")
                    if len(parts) == 3:
                        sx, sy, sz = int(parts[0]), int(parts[1]), int(parts[2])
                        self.section_crc_map[(sx, sy, sz)] = int(v) & 0xFFFFFFFF
            return True
        except Exception as e:
            logger.warning(f"Failed to import manifest metadata: {e}")
            return False


# Global singleton instance for live syncing in Blender session
voxel_storage = VoxelStorage()


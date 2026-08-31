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
    res = raw_state
    if raw_state.startswith('{"state":"'):
        end_idx = raw_state.find('"', 10)
        if end_idx != -1:
            res = raw_state[10:end_idx]
    elif raw_state.startswith("{"):
        try:
            import json
            data = json.loads(raw_state)
            if isinstance(data, dict) and "state" in data:
                res = str(data["state"])
        except Exception:
            pass
    if res in ("minecraft:air", "minecraft:cave_air", "minecraft:void_air", "air", "cave_air", "void_air"):
        return "minecraft:air"
    return res


_EMPTY_CRC_TABLE: List[int] = []


def _init_empty_crc_table() -> None:
    global _EMPTY_CRC_TABLE
    if _EMPTY_CRC_TABLE:
        return
    table = [0] * 4097
    crc_val = 0
    air_bytes = b"minecraft:air"
    table[0] = 0
    for count in range(1, 4097):
        crc_val = zlib.crc32(air_bytes, crc_val) & 0xFFFFFFFF
        table[count] = crc_val
    _EMPTY_CRC_TABLE = table


_init_empty_crc_table()


def get_empty_section_crc(block_count: int = 4096) -> int:
    """Compute canonical CRC32 for an empty chunk/section of air with `block_count` blocks."""
    if not _EMPTY_CRC_TABLE:
        _init_empty_crc_table()
    if 0 <= block_count < len(_EMPTY_CRC_TABLE):
        return _EMPTY_CRC_TABLE[block_count]
    crc_val = 0
    air_bytes = b"minecraft:air"
    for _ in range(max(0, block_count)):
        crc_val = zlib.crc32(air_bytes, crc_val)
    return crc_val & 0xFFFFFFFF


EMPTY_SECTION_CRC = get_empty_section_crc(4096)


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
        self._section_map: Dict[Tuple[int, int, int], Dict[Tuple[int, int, int], str]] = {}  # sec_pos -> {abs_pos: state_str}
        self._state_counts: Dict[str, int] = {}
        self.section_crc_map: Dict[Tuple[int, int, int], int] = {}  # (sec_x, sec_y, sec_z) -> uint32 crc
        self._dirty_sections: Set[Tuple[int, int, int]] = set()
        self._known_empty_sections: Set[Tuple[int, int, int]] = set()
        self.generation: int = 0

    def clear(self) -> None:
        """Clear all stored voxel and section data."""
        self.block_map.clear()
        self._section_map.clear()
        self._state_counts.clear()
        self.section_crc_map.clear()
        self._dirty_sections.clear()
        self._known_empty_sections.clear()
        self.min_x = self.min_y = self.min_z = 0
        self.size_x = self.size_y = self.size_z = 0
        self.generation += 1

    def set_bounds(self, min_x: int, min_y: int, min_z: int, size_x: int, size_y: int, size_z: int) -> None:
        """Initialize or update selection bounding box from selection info."""
        if (self.min_x, self.min_y, self.min_z, self.size_x, self.size_y, self.size_z) != (min_x, min_y, min_z, size_x, size_y, size_z):
            # If bounds changed completely, clear stale block data
            if self.size_x > 0 and (self.min_x != min_x or self.min_y != min_y or self.min_z != min_z):
                self.block_map.clear()
                self._section_map.clear()
                self._state_counts.clear()
                self.section_crc_map.clear()
                self._dirty_sections.clear()
            self.min_x = min_x
            self.min_y = min_y
            self.min_z = min_z
            self.size_x = size_x
            self.size_y = size_y
            self.size_z = size_z
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
        for sec_key, sec_dict in list(self._section_map.items()):
            for s in sec_dict.values():
                canonical = _extract_canonical_state_str(s)
                if canonical and canonical not in air_names and not canonical.startswith("minecraft:air"):
                    sections.add(sec_key)
                    break
        return sections

    def get_section_blocks(self, sec_x: int, sec_y: int, sec_z: int) -> Dict[Tuple[int, int, int], str]:
        """Return all (abs_x, abs_y, abs_z) -> state_str within the given 16x16x16 section in O(1)."""
        sec = self._section_map.get((sec_x, sec_y, sec_z))
        return dict(sec) if sec else {}

    def get_state_counts(self) -> Dict[str, int]:
        """Return canonical dictionary of state_str -> count across active blocks."""
        if not self._state_counts and self.block_map:
            from collections import Counter
            self._state_counts = dict(Counter(list(self.block_map.values())))
        return dict(self._state_counts)

    def get_unique_states(self) -> List[str]:
        """Return snapshot list of unique block states currently in storage."""
        if self._state_counts:
            return list(self._state_counts.keys())
        return list(set(list(self.block_map.values())))

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
        sec_key = (x >> 4, y >> 4, z >> 4)
        if sec_key not in self._section_map:
            self._section_map[sec_key] = {}
        self._section_map[sec_key][(x, y, z)] = state_str
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
        self.section_crc_map.pop((sx, sy, sz), None)
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
        self._section_map.clear()
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
                pos = (abs_x, abs_y, abs_z)
                self.block_map[pos] = state_str
                sec_key = (abs_x >> 4, abs_y >> 4, abs_z >> 4)
                if sec_key not in self._section_map:
                    self._section_map[sec_key] = {}
                self._section_map[sec_key][pos] = state_str
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
        if size_x <= 0 or size_y <= 0 or size_z <= 0:
            return False
        if self.size_x == 0 or self.size_y == 0 or self.size_z == 0:
            self.min_x = start_x
            self.min_y = start_y
            self.min_z = start_z
            self.size_x = size_x
            self.size_y = size_y
            self.size_z = size_z
        else:
            max_x = max(self.min_x + self.size_x - 1, start_x + size_x - 1)
            max_y = max(self.min_y + self.size_y - 1, start_y + size_y - 1)
            max_z = max(self.min_z + self.size_z - 1, start_z + size_z - 1)
            self.min_x = min(self.min_x, start_x)
            self.min_y = min(self.min_y, start_y)
            self.min_z = min(self.min_z, start_z)
            self.size_x = max_x - self.min_x + 1
            self.size_y = max_y - self.min_y + 1
            self.size_z = max_z - self.min_z + 1

        total_blocks = size_x * size_y * size_z
        palette_len = len(palette)
        if len(grid_indices) < total_blocks or any(idx < 0 or idx >= palette_len for idx in grid_indices[:total_blocks]):
            logger.warning("Discarded malformed section snapshot for (%d, %d, %d)", sec_x, sec_y, sec_z)
            return False

        sec_key = (sec_x, sec_y, sec_z)
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
                if sec_key not in self._section_map:
                    self._section_map[sec_key] = {}
                self._section_map[sec_key][key] = state_str
                self._state_counts[state_str] = self._state_counts.get(state_str, 0) + 1

        # A repair snapshot replaces voxel data directly, so its section must
        # be rebuilt.  Discarding it here made ``schedule_mesh_sync()`` a
        # no-op: storage became correct while the old water/entity geometry
        # stayed in the scene.  Fluids sample diagonal neighbours for their
        # corner heights, hence invalidate the full 3x3x3 section halo.
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    self._dirty_sections.add((sec_x + dx, sec_y + dy, sec_z + dz))
        self.calculate_and_store_section_crc(sec_x, sec_y, sec_z)
        return True

    def apply_delta_update(
        self,
        min_x: int, min_y: int, min_z: int,
        changes: List[Tuple[int, int, int, str]],
    ) -> bool:
        """Apply incremental delta changes to voxel storage, tracking dirty sections and boundary neighbors."""
        return bool(self.apply_delta_update_detailed(min_x, min_y, min_z, changes))

    def apply_delta_update_detailed(
        self,
        min_x: int, min_y: int, min_z: int,
        changes: List[Tuple[int, int, int, str]],
    ) -> List[Tuple[int, int, int, str, str]]:
        """Apply a delta and return the *effective* ``(x, y, z, old, new)`` edits.

        The old state is essential to mesh synchronization: removing water must
        rebuild the surrounding fluid surface even though the new state is air.
        Returning only a boolean used to lose that information, leaving stale
        fluid faces in the scene.
        """
        if not self.matches_bounds(min_x, min_y, min_z):
            logger.warning("Discarded delta for stale selection bounds (%d, %d, %d)", min_x, min_y, min_z)
            return []
        if any(not self.contains(x, y, z) for x, y, z, _state in changes):
            logger.warning("Discarded delta containing coordinates outside active selection")
            return []

        applied: List[Tuple[int, int, int, str, str]] = []
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
            sx, sy, sz = abs_x >> 4, abs_y >> 4, abs_z >> 4
            sec_key = (sx, sy, sz)
            if sec_key not in self._section_map:
                self._section_map[sec_key] = {}
            self._section_map[sec_key][key] = state_str
            self._state_counts[state_str] = self._state_counts.get(state_str, 0) + 1

            sx, sy, sz = abs_x >> 4, abs_y >> 4, abs_z >> 4
            self.section_crc_map.pop((sx, sy, sz), None)
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

            applied.append((abs_x, abs_y, abs_z, old_state or "minecraft:air", state_str))

        return applied

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

    def get_section_block_bounds(self, sec_x: int, sec_y: int, sec_z: int) -> Tuple[int, int, int, int, int, int]:
        """Return (start_x, start_y, start_z, size_x, size_y, size_z) for a section clamped to bounds."""
        if self.size_x == 0 or self.size_y == 0 or self.size_z == 0:
            return (sec_x << 4, sec_y << 4, sec_z << 4, 16, 16, 16)
        max_x = self.min_x + self.size_x - 1
        max_y = self.min_y + self.size_y - 1
        max_z = self.min_z + self.size_z - 1
        start_x = max(self.min_x, sec_x << 4)
        end_x = min(max_x, (sec_x << 4) + 15)
        start_y = max(self.min_y, sec_y << 4)
        end_y = min(max_y, (sec_y << 4) + 15)
        start_z = max(self.min_z, sec_z << 4)
        end_z = min(max_z, (sec_z << 4) + 15)
        sx = max(0, end_x - start_x + 1)
        sy = max(0, end_y - start_y + 1)
        sz = max(0, end_z - start_z + 1)
        return (start_x, start_y, start_z, sx, sy, sz)

    def get_section_block_count(self, sec_x: int, sec_y: int, sec_z: int) -> int:
        """Return total number of blocks within bounding box for given section."""
        _, _, _, sx, sy, sz = self.get_section_block_bounds(sec_x, sec_y, sec_z)
        return sx * sy * sz

    def is_empty_section_crc(self, sec_x: int, sec_y: int, sec_z: int, crc_val: int) -> bool:
        """Check if crc_val matches canonical CRC of all-air blocks for this section."""
        count = self.get_section_block_count(sec_x, sec_y, sec_z)
        return crc_val == get_empty_section_crc(count)

    def validate_manifest(
        self,
        server_sections: List[Tuple[int, int, int, int]],
        existing_section_meshes: Optional[Set[Tuple[int, int, int]]] = None,
    ) -> List[Tuple[int, int, int]]:
        """Compare server CRC32 hashes with local ones and check DCC scene mesh health.

        Returns mismatched or corrupted section coords (CRC mismatch, dirty, or missing mesh object).
        """
        mismatched = []
        for sec_x, sec_y, sec_z, server_crc32 in server_sections:
            key = (sec_x, sec_y, sec_z)
            if key in self._dirty_sections or key not in self.section_crc_map:
                self.calculate_and_store_section_crc(sec_x, sec_y, sec_z)
            local_crc = self.section_crc_map.get(key, None)
            if local_crc != server_crc32:
                logger.debug(
                    "Live Sync CRC mismatch for section (%d, %d, %d): local=0x%08X (%d), server=0x%08X (%d)",
                    sec_x, sec_y, sec_z,
                    local_crc if local_crc is not None else 0, local_crc if local_crc is not None else 0,
                    server_crc32, server_crc32
                )
                mismatched.append(key)
                continue

            # Bad chunk / missing mesh verification:
            # If the server reports a non-empty section (CRC differs from all-air blocks),
            # but the section generated visible geometry previously and its child mesh object is missing in Blender,
            # mark as a bad chunk. Empty / culled sections in _known_empty_sections are ignored.
            if existing_section_meshes is not None and not self.is_empty_section_crc(sec_x, sec_y, sec_z, server_crc32):
                if key not in existing_section_meshes and key not in self._known_empty_sections:
                    mismatched.append(key)

        return mismatched

    def export_manifest_metadata(self) -> dict:
        """Export current bounds and section CRC map for scene/object persistence."""
        crc_export = {}
        for (sx, sy, sz), crc_val in self.section_crc_map.items():
            crc_export[f"{sx},{sy},{sz}"] = crc_val
        empty_export = [f"{sx},{sy},{sz}" for (sx, sy, sz) in self._known_empty_sections]
        return {
            "min_x": self.min_x,
            "min_y": self.min_y,
            "min_z": self.min_z,
            "size_x": self.size_x,
            "size_y": self.size_y,
            "size_z": self.size_z,
            "generation": self.generation,
            "section_crcs": crc_export,
            "known_empty_sections": empty_export,
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
            self._known_empty_sections.clear()
            empty_data = data.get("known_empty_sections", [])
            if isinstance(empty_data, (list, set)):
                for k in empty_data:
                    parts = str(k).split(",")
                    if len(parts) == 3:
                        sx, sy, sz = int(parts[0]), int(parts[1]), int(parts[2])
                        self._known_empty_sections.add((sx, sy, sz))
            return True
        except Exception as e:
            logger.warning(f"Failed to import manifest metadata: {e}")
            return False


# Global singleton instance for live syncing in Blender session
voxel_storage = VoxelStorage()

#!/usr/bin/env python3
"""
MoziToolKit & libmtk Mock Live Sync WebSocket Server.

Simulates a high-performance Minecraft (Yefira / Forge / Fabric) streaming server
implementing the binary protocol specification (v1) defined in `mtk-sync`.

Features:
- 100% compliant with little-endian binary packet codecs (0x01..0x09, 0x80..0x82).
- Zero mandatory external dependencies (built-in async RFC 6455 server + optional websockets fallback).
- Multiple procedural terrain presets:
  * `flat`: Baseline testing with bedrock, dirt, grass, and trees.
  * `hills`: Procedural hilly terrain with elevation, caves, and water ponds.
  * `complex`: Comprehensive test suite for pure JSON models (stairs, slabs, fences, chests, beds, lanterns).
  * `fluids`: Stepped waterfall cascades and fluid interpolation test.
  * `benchmark`: Stress test for massive terrain ingestion and throughput.
- Full snapshot mode or progressive chunk section streaming (0x08/0x06/0x09).
- Automated live block delta generation (0x03) simulating real-time world edits.
- Interactive terminal REPL to trigger full sync, deltas, or manifest validation on demand.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import math
import os
import random
import struct
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
DEV_LIB = os.path.join(PROJECT_ROOT, "dev", "lib")
if DEV_LIB not in sys.path:
    sys.path.insert(0, DEV_LIB)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import libmtk_py
except ImportError:
    from bridge.engine import get_libmtk
    libmtk_py = get_libmtk()

# ---------------------------------------------------------------------------
# Protocol Constants (RFC v3.1 & Legacy)
# ---------------------------------------------------------------------------

PROTOCOL_MAGIC = b"MT"
PROTOCOL_VERSION = 0x03

# RFC v3.1 Opcodes
OPCODE_HELLO = 0x01
OPCODE_WELCOME = 0x02
OPCODE_BASELINE_BEGIN = 0x03
OPCODE_BASELINE_CHUNK = 0x04
OPCODE_BASELINE_END = 0x05
OPCODE_BASELINE_ACK = 0x06
OPCODE_DELTA_OP = 0x07
OPCODE_PALETTE_UPDATE = 0x08
OPCODE_STATE_VERIFY_REQ = 0x09
OPCODE_STATE_VERIFY_RESP = 0x0A
OPCODE_CANCEL = 0x0B
OPCODE_RESYNC_REQUEST = 0x0D
OPCODE_PING = 0x0E
OPCODE_PONG = 0x0F

# Legacy Packet Types (for test backward compatibility)
PKT_SELECTION_INFO = 0x01
PKT_FULL_SNAPSHOT = 0x02
PKT_DELTA_UPDATE = 0x03
PKT_BLOCK_PALETTE = 0x04
PKT_SECTION_MANIFEST = 0x05
PKT_SECTION_SNAPSHOT = 0x06
PKT_HANDSHAKE_INFO = 0x07
PKT_STREAM_BEGIN = 0x08
PKT_STREAM_END = 0x09
PKT_REQ_FULL_SYNC = 0x80
PKT_REQ_RESYNC = 0x81
PKT_REQ_SECTION_SYNC = 0x81
PKT_REQ_SYNC_CONFIG = 0x82
PKT_SYNC_CONFIG = 0x82


STREAM_STATUS_SUCCESS = 0
STREAM_STATUS_ERROR = 1

MIN_SUPPORTED_PROTOCOL_VERSION = 1
MAX_SUPPORTED_PROTOCOL_VERSION = 3


# ---------------------------------------------------------------------------
# Binary Packet Encoders
# ---------------------------------------------------------------------------

def encode_header(pkt_type: int) -> bytes:
    """Encodes the 4-byte protocol header: Magic(2) + Version(1) + Type(1)."""
    return PROTOCOL_MAGIC + bytes([PROTOCOL_VERSION, pkt_type])


def encode_selection_info(min_pos: Tuple[int, int, int], size: Tuple[int, int, int]) -> bytes:
    """0x01: Selection bounding box information."""
    payload = struct.pack(
        "<6i",
        min_pos[0], min_pos[1], min_pos[2],
        size[0], size[1], size[2],
    )
    return encode_header(PKT_SELECTION_INFO) + payload


def encode_handshake_info(
    total_sections: int,
    non_empty_sections: int,
    total_volume: int,
    dimension: str = "minecraft:overworld",
    flags: int = 0,
) -> bytes:
    """0x07: Handshake metadata."""
    dim_bytes = dimension.encode("utf-8")
    header_data = struct.pack(
        "<3IH",
        total_sections,
        non_empty_sections,
        total_volume,
        len(dim_bytes),
    )
    return encode_header(PKT_HANDSHAKE_INFO) + header_data + dim_bytes + struct.pack("<H", flags)


def encode_full_snapshot(
    min_pos: Tuple[int, int, int],
    size: Tuple[int, int, int],
    palette: List[str],
    grid_indices: List[int],
    biome_palette: Optional[List[str]] = None,
    biome_indices: Optional[List[int]] = None,
) -> bytes:
    """0x02: Full selection volume snapshot."""
    min_x, min_y, min_z = min_pos
    size_x, size_y, size_z = size

    buf = bytearray()
    buf.extend(encode_header(PKT_FULL_SNAPSHOT))
    buf.extend(struct.pack("<6i", min_x, min_y, min_z, size_x, size_y, size_z))

    # Palette
    buf.extend(struct.pack("<H", len(palette)))
    for p in palette:
        p_bytes = p.encode("utf-8")
        buf.extend(struct.pack("<H", len(p_bytes)))
        buf.extend(p_bytes)

    # Grid Indices
    use_u16 = len(palette) > 256
    buf.append(2 if use_u16 else 1)

    if use_u16:
        buf.extend(struct.pack(f"<{len(grid_indices)}H", *grid_indices))
    else:
        buf.extend(bytes(grid_indices))

    # Optional Biomes
    if biome_palette and biome_indices:
        buf.extend(struct.pack("<H", len(biome_palette)))
        for bp in biome_palette:
            bp_bytes = bp.encode("utf-8")
            buf.extend(struct.pack("<H", len(bp_bytes)))
            buf.extend(bp_bytes)

        if len(biome_palette) > 1:
            use_biome_u16 = len(biome_palette) > 256
            buf.append(2 if use_biome_u16 else 1)
            if use_biome_u16:
                buf.extend(struct.pack(f"<{len(biome_indices)}H", *biome_indices))
            else:
                buf.extend(bytes(biome_indices))

    return bytes(buf)


def encode_section_snapshot(
    sec_coord: Tuple[int, int, int],
    start_pos: Tuple[int, int, int],
    size: Tuple[int, int, int],
    palette: List[str],
    grid_indices: List[int],
    biome_palette: Optional[List[str]] = None,
    biome_indices: Optional[List[int]] = None,
) -> bytes:
    """0x06: Single 16x16x16 chunk section snapshot."""
    sec_x, sec_y, sec_z = sec_coord
    start_x, start_y, start_z = start_pos
    size_x, size_y, size_z = size

    buf = bytearray()
    buf.extend(encode_header(PKT_SECTION_SNAPSHOT))
    buf.extend(struct.pack("<3i3i3iH", sec_x, sec_y, sec_z, start_x, start_y, start_z, size_x, size_y, size_z, len(palette)))

    for p in palette:
        p_bytes = p.encode("utf-8")
        buf.extend(struct.pack("<H", len(p_bytes)))
        buf.extend(p_bytes)

    use_u16 = len(palette) > 256
    buf.append(2 if use_u16 else 1)

    if use_u16:
        buf.extend(struct.pack(f"<{len(grid_indices)}H", *grid_indices))
    else:
        buf.extend(bytes(grid_indices))

    if biome_palette and biome_indices:
        buf.extend(struct.pack("<H", len(biome_palette)))
        for bp in biome_palette:
            bp_bytes = bp.encode("utf-8")
            buf.extend(struct.pack("<H", len(bp_bytes)))
            buf.extend(bp_bytes)

        if len(biome_palette) > 1:
            use_biome_u16 = len(biome_palette) > 256
            buf.append(2 if use_biome_u16 else 1)
            if use_biome_u16:
                buf.extend(struct.pack(f"<{len(biome_indices)}H", *biome_indices))
            else:
                buf.extend(bytes(biome_indices))

    return bytes(buf)


def encode_delta_update(
    seq_id: int,
    min_pos: Tuple[int, int, int],
    changes: List[Tuple[Tuple[int, int, int], str]],
) -> bytes:
    """0x03: Real-time incremental block modifications."""
    buf = bytearray()
    buf.extend(encode_header(PKT_DELTA_UPDATE))
    buf.extend(struct.pack("<I3iH", seq_id, min_pos[0], min_pos[1], min_pos[2], len(changes)))

    for (rel_x, rel_y, rel_z), state in changes:
        state_bytes = state.encode("utf-8")
        buf.extend(struct.pack("<3HH", rel_x, rel_y, rel_z, len(state_bytes)))
        buf.extend(state_bytes)

    return bytes(buf)


def encode_stream_begin(stream_id: int, total_sections: int, flags: int = 0) -> bytes:
    """0x08: Progressive stream begin."""
    return encode_header(PKT_STREAM_BEGIN) + struct.pack("<IIH", stream_id, total_sections, flags)


def encode_stream_end(stream_id: int, sent_sections: int, status: int = STREAM_STATUS_SUCCESS) -> bytes:
    """0x09: Progressive stream complete."""
    return encode_header(PKT_STREAM_END) + struct.pack("<IIH", stream_id, sent_sections, status)


def encode_section_manifest(seq_id: int, entries: List[Tuple[Tuple[int, int, int], int]]) -> bytes:
    """0x05: Chunk section CRC32 verification manifest."""
    buf = bytearray()
    buf.extend(encode_header(PKT_SECTION_MANIFEST))
    buf.extend(struct.pack("<II", seq_id, len(entries)))

    for (sec_x, sec_y, sec_z), crc in entries:
        buf.extend(struct.pack("<3iI", sec_x, sec_y, sec_z, crc & 0xFFFFFFFF))

    return bytes(buf)


# ---------------------------------------------------------------------------
# Client Packet Decoder
# ---------------------------------------------------------------------------

def decode_client_packet(data: bytes) -> Optional[Dict[str, Any]]:
    """Decodes incoming client binary frame into an event dict."""
    if len(data) < 4:
        return None
    if data[0:2] != PROTOCOL_MAGIC or not (MIN_SUPPORTED_PROTOCOL_VERSION <= data[2] <= MAX_SUPPORTED_PROTOCOL_VERSION):
        return None

    pkt_type = data[3]
    if pkt_type == PKT_REQ_FULL_SYNC:
        return {"type": "REQ_FULL_SYNC"}

    if pkt_type == PKT_REQ_SECTION_SYNC:
        if len(data) < 6:
            return None
        count = struct.unpack("<H", data[4:6])[0]
        offset = 6
        sections = []
        for _ in range(count):
            if len(data) < offset + 12:
                break
            sx, sy, sz = struct.unpack("<3i", data[offset:offset + 12])
            sections.append((sx, sy, sz))
            offset += 12
        return {"type": "REQ_SECTION_SYNC", "sections": sections}

    if pkt_type == PKT_SYNC_CONFIG:
        if len(data) < 7:
            return None
        throttle, fps, active = struct.unpack("<BBB", data[4:7])
        return {
            "type": "SYNC_CONFIG",
            "throttle_mode": throttle,
            "target_fps": fps,
            "is_active": bool(active),
        }

    return {"type": f"UNKNOWN_{pkt_type:#x}"}


# ---------------------------------------------------------------------------
# Procedural Terrain Generation
# ---------------------------------------------------------------------------

COMPLEX_PALETTE_SAMPLES = [
    # Custom Non-Cube JSON Models
    "minecraft:oak_stairs[facing=east,half=bottom,shape=straight,waterlogged=false]",
    "minecraft:oak_stairs[facing=north,half=bottom,shape=straight,waterlogged=false]",
    "minecraft:oak_stairs[facing=west,half=top,shape=straight,waterlogged=false]",
    "minecraft:smooth_stone_slab[type=bottom,waterlogged=false]",
    "minecraft:smooth_stone_slab[type=top,waterlogged=false]",
    "minecraft:smooth_stone_slab[type=double,waterlogged=false]",
    "minecraft:oak_fence[east=true,north=false,south=false,west=true,waterlogged=false]",
    "minecraft:chest[facing=south,type=single,waterlogged=false]",
    "minecraft:red_bed[facing=north,occupied=false,part=foot]",
    "minecraft:red_bed[facing=north,occupied=false,part=head]",
    "minecraft:lantern[hanging=false,waterlogged=false]",
    "minecraft:torch",
    "minecraft:iron_bars[east=true,north=true,south=false,west=false,waterlogged=false]",
    # Fluids
    "minecraft:water[level=0]",
    "minecraft:water[level=2]",
    "minecraft:lava[level=0]",
]


class WorldGrid:
    """In-memory 3D block grid for testing."""

    def __init__(self, min_pos: Tuple[int, int, int], size: Tuple[int, int, int]):
        self.min_pos = min_pos
        self.size = size
        self.palette: List[str] = ["minecraft:air"]
        self.palette_lookup: Dict[str, int] = {"minecraft:air": 0}

        # Flat array indexed as: lx * (size_y * size_z) + ly * size_z + lz
        total_volume = size[0] * size[1] * size[2]
        self.indices: List[int] = [0] * total_volume

    def get_index(self, lx: int, ly: int, lz: int) -> int:
        return lx * (self.size[1] * self.size[2]) + ly * self.size[2] + lz

    def register_block(self, state: str) -> int:
        if state in self.palette_lookup:
            return self.palette_lookup[state]
        idx = len(self.palette)
        self.palette.append(state)
        self.palette_lookup[state] = idx
        return idx

    def set_block(self, lx: int, ly: int, lz: int, state: str) -> None:
        if 0 <= lx < self.size[0] and 0 <= ly < self.size[1] and 0 <= lz < self.size[2]:
            idx = self.register_block(state)
            self.indices[self.get_index(lx, ly, lz)] = idx

    def get_block(self, lx: int, ly: int, lz: int) -> str:
        if 0 <= lx < self.size[0] and 0 <= ly < self.size[1] and 0 <= lz < self.size[2]:
            idx = self.indices[self.get_index(lx, ly, lz)]
            return self.palette[idx]
        return "minecraft:air"

    def compute_section_crc(self, sec_coord: Tuple[int, int, int]) -> int:
        """Computes section CRC32 compatible with mtk-voxel."""
        sx, sy, sz = sec_coord
        sec_min_x = sx * 16
        sec_min_y = sy * 16
        sec_min_z = sz * 16

        buf = bytearray()
        for lx_sec in range(16):
            wx = sec_min_x + lx_sec
            lx = wx - self.min_pos[0]
            for ly_sec in range(16):
                wy = sec_min_y + ly_sec
                ly = wy - self.min_pos[1]
                for lz_sec in range(16):
                    wz = sec_min_z + lz_sec
                    lz = wz - self.min_pos[2]
                    state = self.get_block(lx, ly, lz)
                    buf.extend(state.encode("utf-8"))
        return zlib.crc32(buf) & 0xFFFFFFFF


def generate_terrain(
    preset: str,
    min_pos: Tuple[int, int, int] = (0, 64, 0),
    size: Tuple[int, int, int] = (32, 32, 32),
) -> WorldGrid:
    """Generates a procedural testing world."""
    grid = WorldGrid(min_pos, size)
    sx, sy, sz = size

    if preset == "flat":
        # Bedrock, dirt layers, grass, plus a small oak tree
        for x in range(sx):
            for z in range(sz):
                grid.set_block(x, 0, z, "minecraft:bedrock")
                for y in range(1, 4):
                    grid.set_block(x, y, z, "minecraft:dirt")
                grid.set_block(x, 4, z, "minecraft:grass_block[snowy=false]")

        # Plant an oak tree at center
        cx, cz = sx // 2, sz // 2
        for ty in range(5, 10):
            grid.set_block(cx, ty, cz, "minecraft:oak_log[axis=y]")
        for lx in range(cx - 2, cx + 3):
            for lz in range(cz - 2, cz + 3):
                for ly in range(8, 11):
                    if grid.get_block(lx, ly, lz) == "minecraft:air":
                        grid.set_block(lx, ly, lz, "minecraft:oak_leaves[distance=1,persistent=true]")

    elif preset == "hills":
        # Multi-frequency sine/cosine hilly terrain
        for x in range(sx):
            for z in range(sz):
                nx = (x + min_pos[0]) * 0.15
                nz = (z + min_pos[2]) * 0.15
                h = int(6 + 5.0 * math.sin(nx) + 4.0 * math.cos(nz) + 2.0 * math.sin(nx * 2.1 + nz))
                h = max(2, min(sy - 4, h))

                for y in range(0, h - 2):
                    grid.set_block(x, y, z, "minecraft:stone")
                for y in range(max(0, h - 2), h):
                    grid.set_block(x, y, z, "minecraft:dirt")
                grid.set_block(x, h, z, "minecraft:grass_block[snowy=false]")

                # Water body at sea level
                sea_level = 5
                if h < sea_level:
                    for y in range(h + 1, sea_level + 1):
                        grid.set_block(x, y, z, "minecraft:water[level=0]")

    elif preset == "complex":
        # Build ground
        for x in range(sx):
            for z in range(sz):
                grid.set_block(x, 0, z, "minecraft:smooth_stone")
                grid.set_block(x, 1, z, "minecraft:oak_planks")

        # Complex test arena: Pyramids of stairs, fences, beds, chests, lanterns
        for i in range(2, min(sx - 2, 10)):
            # East stairs
            grid.set_block(i, 2, 4, "minecraft:oak_stairs[facing=east,half=bottom,shape=straight,waterlogged=false]")
            # Slabs
            grid.set_block(i, 2, 6, "minecraft:smooth_stone_slab[type=bottom,waterlogged=false]")
            grid.set_block(i, 2, 8, "minecraft:smooth_stone_slab[type=top,waterlogged=false]")
            # Fences
            grid.set_block(i, 2, 10, "minecraft:oak_fence[east=true,north=false,south=false,west=true,waterlogged=false]")
            # Lantern on top
            if i % 2 == 0:
                grid.set_block(i, 3, 10, "minecraft:lantern[hanging=false,waterlogged=false]")

        # Chests and beds
        grid.set_block(4, 2, 14, "minecraft:chest[facing=south,type=single,waterlogged=false]")
        grid.set_block(6, 2, 14, "minecraft:chest[facing=north,type=single,waterlogged=false]")
        grid.set_block(8, 2, 14, "minecraft:red_bed[facing=north,occupied=false,part=foot]")
        grid.set_block(8, 2, 15, "minecraft:red_bed[facing=north,occupied=false,part=head]")

        # Water pool with stairs
        for wx in range(12, 16):
            for wz in range(12, 16):
                grid.set_block(wx, 1, wz, "minecraft:water[level=0]")
                grid.set_block(wx, 2, wz, "minecraft:oak_stairs[facing=south,half=bottom,shape=straight,waterlogged=true]")

    elif preset == "fluids":
        # Stepped waterfall
        for x in range(sx):
            for z in range(sz):
                grid.set_block(x, 0, z, "minecraft:stone")

        # Cascade steps
        for step in range(min(8, sy - 2)):
            y = step + 1
            z = step * 2 + 2
            for x in range(sx // 2 - 3, sx // 2 + 4):
                grid.set_block(x, y, z, "minecraft:stone")
                grid.set_block(x, y + 1, z, f"minecraft:water[level={min(7, step)}]")

    elif preset == "benchmark":
        # Dense layered terrain with random noise
        for x in range(sx):
            for z in range(sz):
                h = (x * 7 + z * 13) % (sy - 4) + 2
                for y in range(0, h - 1):
                    grid.set_block(x, y, z, "minecraft:stone")
                grid.set_block(x, h - 1, z, "minecraft:dirt")
                grid.set_block(x, h, z, "minecraft:grass_block[snowy=false]")

    elif preset in {"issues", "regression"}:
        # Showcase arena for directional and complex models
        for x in range(sx):
            for z in range(sz):
                grid.set_block(x, 0, z, "minecraft:bedrock")
                grid.set_block(x, 1, z, "minecraft:polished_andesite")

        # Row 1 (z=3): Chest orientations (North, South, East, West, single, left, right, trapped, ender)
        grid.set_block(2, 2, 3, "minecraft:chest[facing=north,type=single,waterlogged=false]")
        grid.set_block(4, 2, 3, "minecraft:chest[facing=south,type=single,waterlogged=false]")
        grid.set_block(6, 2, 3, "minecraft:chest[facing=east,type=single,waterlogged=false]")
        grid.set_block(8, 2, 3, "minecraft:chest[facing=west,type=single,waterlogged=false]")
        grid.set_block(10, 2, 3, "minecraft:chest[facing=north,type=left,waterlogged=false]")
        grid.set_block(11, 2, 3, "minecraft:chest[facing=north,type=right,waterlogged=false]")
        grid.set_block(13, 2, 3, "minecraft:trapped_chest[facing=south,type=single,waterlogged=false]")
        grid.set_block(15, 2, 3, "minecraft:ender_chest[facing=north,waterlogged=false]")

        # Row 2 (z=6): Chiseled bookshelves with different occupied states
        grid.set_block(2, 2, 6, "minecraft:chiseled_bookshelf[facing=north,slot_0_occupied=false,slot_1_occupied=false,slot_2_occupied=false,slot_3_occupied=false,slot_4_occupied=false,slot_5_occupied=false]")
        grid.set_block(4, 2, 6, "minecraft:chiseled_bookshelf[facing=north,slot_0_occupied=true,slot_1_occupied=false,slot_2_occupied=false,slot_3_occupied=false,slot_4_occupied=false,slot_5_occupied=false]")
        grid.set_block(6, 2, 6, "minecraft:chiseled_bookshelf[facing=north,slot_0_occupied=true,slot_1_occupied=true,slot_2_occupied=false,slot_3_occupied=false,slot_4_occupied=false,slot_5_occupied=false]")
        grid.set_block(8, 2, 6, "minecraft:chiseled_bookshelf[facing=north,slot_0_occupied=true,slot_1_occupied=true,slot_2_occupied=true,slot_3_occupied=false,slot_4_occupied=false,slot_5_occupied=false]")
        grid.set_block(10, 2, 6, "minecraft:chiseled_bookshelf[facing=south,slot_0_occupied=true,slot_1_occupied=true,slot_2_occupied=true,slot_3_occupied=true,slot_4_occupied=true,slot_5_occupied=true]")
        grid.set_block(12, 2, 6, "minecraft:chiseled_bookshelf[facing=east,slot_0_occupied=false,slot_1_occupied=true,slot_2_occupied=false,slot_3_occupied=true,slot_4_occupied=false,slot_5_occupied=true]")

        # Row 3 (z=9): Skulls and Heads (Floor with various rotations)
        grid.set_block(2, 2, 9, "minecraft:player_head[rotation=0]")
        grid.set_block(4, 2, 9, "minecraft:player_head[rotation=4]")
        grid.set_block(6, 2, 9, "minecraft:player_head[rotation=8]")
        grid.set_block(8, 2, 9, "minecraft:player_head[rotation=12]")
        grid.set_block(10, 2, 9, "minecraft:skeleton_skull[rotation=0]")
        grid.set_block(12, 2, 9, "minecraft:wither_skeleton_skull[rotation=4]")
        grid.set_block(14, 2, 9, "minecraft:zombie_head[rotation=8]")
        grid.set_block(16, 2, 9, "minecraft:creeper_head[rotation=12]")
        grid.set_block(18, 2, 9, "minecraft:piglin_head[rotation=0]")
        grid.set_block(20, 2, 9, "minecraft:piglin_head[rotation=8]")
        grid.set_block(22, 2, 9, "minecraft:dragon_head[rotation=0]")
        grid.set_block(24, 2, 9, "minecraft:dragon_head[rotation=8]")

        # Row 4 (z=12): Wall Skulls and Heads (against a wall at z=13)
        for x in range(2, 26):
            grid.set_block(x, 2, 13, "minecraft:stone_bricks")
        grid.set_block(2, 2, 12, "minecraft:player_wall_head[facing=north]")
        grid.set_block(4, 2, 12, "minecraft:skeleton_wall_skull[facing=north]")
        grid.set_block(6, 2, 12, "minecraft:wither_skeleton_wall_skull[facing=north]")
        grid.set_block(8, 2, 12, "minecraft:zombie_wall_head[facing=north]")
        grid.set_block(10, 2, 12, "minecraft:creeper_wall_head[facing=north]")
        grid.set_block(12, 2, 12, "minecraft:piglin_wall_head[facing=north]")
        grid.set_block(14, 2, 12, "minecraft:dragon_wall_head[facing=north]")

        # Row 5 (z=16): Pink Petals and Wildflowers (amounts 1, 2, 3, 4)
        grid.set_block(2, 2, 16, "minecraft:pink_petals[facing=north,flower_amount=1]")
        grid.set_block(4, 2, 16, "minecraft:pink_petals[facing=north,flower_amount=2]")
        grid.set_block(6, 2, 16, "minecraft:pink_petals[facing=north,flower_amount=3]")
        grid.set_block(8, 2, 16, "minecraft:pink_petals[facing=north,flower_amount=4]")
        grid.set_block(10, 2, 16, "minecraft:pink_petals[facing=east,flower_amount=1]")
        grid.set_block(12, 2, 16, "minecraft:pink_petals[facing=south,flower_amount=2]")
        grid.set_block(14, 2, 16, "minecraft:pink_petals[facing=west,flower_amount=3]")

        # Row 6 (z=19): Chains (axis=y, axis=x, axis=z)
        grid.set_block(2, 2, 19, "minecraft:iron_chain[axis=y,waterlogged=false]")
        grid.set_block(4, 2, 19, "minecraft:iron_chain[axis=x,waterlogged=false]")
        grid.set_block(6, 2, 19, "minecraft:iron_chain[axis=z,waterlogged=false]")
        grid.set_block(8, 2, 19, "minecraft:chain[axis=y,waterlogged=false]")
        grid.set_block(10, 2, 19, "minecraft:chain[axis=x,waterlogged=false]")
        grid.set_block(12, 2, 19, "minecraft:chain[axis=z,waterlogged=false]")
        grid.set_block(14, 2, 19, "minecraft:copper_chain[axis=y,waterlogged=false]")

        # Row 7 (z=22): Bells and Beds
        grid.set_block(2, 2, 22, "minecraft:bell[attachment=floor,facing=north]")
        grid.set_block(4, 2, 22, "minecraft:bell[attachment=ceiling,facing=south]")
        grid.set_block(6, 2, 22, "minecraft:bell[attachment=single_wall,facing=east]")
        grid.set_block(8, 2, 22, "minecraft:bell[attachment=double_wall,facing=west]")
        grid.set_block(10, 2, 22, "minecraft:red_bed[facing=north,occupied=false,part=foot]")
        grid.set_block(10, 2, 23, "minecraft:red_bed[facing=north,occupied=false,part=head]")
        grid.set_block(12, 2, 22, "minecraft:blue_bed[facing=east,occupied=false,part=foot]")
        grid.set_block(13, 2, 22, "minecraft:blue_bed[facing=east,occupied=false,part=head]")

    return grid


# ---------------------------------------------------------------------------
# Lightweight Standalone WebSocket Server (RFC 6455)
# ---------------------------------------------------------------------------

class MinimalWebSocketClient:
    """Async WebSocket connection handler with zero dependencies."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.is_open = True

    async def send_binary(self, data: bytes) -> None:
        """Sends a binary WebSocket frame (opcode 0x02)."""
        if not self.is_open:
            return
        frame = bytearray()
        frame.append(0x82)  # FIN + binary opcode

        length = len(data)
        if length < 126:
            frame.append(length)
        elif length < 65536:
            frame.append(126)
            frame.extend(struct.pack("!H", length))
        else:
            frame.append(127)
            frame.extend(struct.pack("!Q", length))

        frame.extend(data)
        self.writer.write(frame)
        await self.writer.drain()

    async def read_frame(self) -> Optional[bytes]:
        """Reads and unmasks a binary frame from client."""
        try:
            head = await self.reader.readexactly(2)
            b1, b2 = head[0], head[1]
            opcode = b1 & 0x0F
            is_masked = bool(b2 & 0x80)
            length = b2 & 0x7F

            if opcode == 0x08:  # Close
                self.is_open = False
                return None

            if length == 126:
                ext = await self.reader.readexactly(2)
                length = struct.unpack("!H", ext)[0]
            elif length == 127:
                ext = await self.reader.readexactly(8)
                length = struct.unpack("!Q", ext)[0]

            mask_key = b""
            if is_masked:
                mask_key = await self.reader.readexactly(4)

            payload = await self.reader.readexactly(length)
            if is_masked:
                unmasked = bytearray(length)
                for i in range(length):
                    unmasked[i] = payload[i] ^ mask_key[i % 4]
                return bytes(unmasked)
            return payload
        except (asyncio.IncompleteReadError, ConnectionResetError):
            self.is_open = False
            return None


class MockLiveSyncServer:
    """Central server coordinator and dispatch loop."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        preset: str = "complex",
        mode: str = "full",
        origin: Tuple[int, int, int] = (0, 64, 0),
        size: Tuple[int, int, int] = (32, 32, 32),
        delta_interval: float = 0.0,
    ):
        self.host = host
        self.port = port
        self.preset = preset
        self.mode = mode
        self.origin = origin
        self.size = size
        self.delta_interval = delta_interval

        self.grid = generate_terrain(preset, origin, size)
        self.clients: Set[MinimalWebSocketClient] = set()
        self.server_uuid = uuid.uuid4()
        self.server_uuid_bytes = self.server_uuid.bytes
        self.epoch = int(time.time())
        self.seq_id = 1
        self.snapshot_uuid = uuid.uuid4()
        self.snapshot_uuid_bytes = self.snapshot_uuid.bytes
        self.stream_id = 1
        self.palette_revision = 1
        self.synced_palette_count = 0
        self.is_running = True
        self.current_state_hash = 0
        self.update_state_hash()

    def get_canonical_blocks(self) -> List[str]:
        """Traverses volume according to RFC Section 3.1: bottom-up horizontal slice scan (Y slowest, Z next, X fastest)."""
        blocks = []
        min_x, min_y, min_z = self.origin
        size_x, size_y, size_z = self.size
        for y in range(min_y, min_y + size_y):
            for z in range(min_z, min_z + size_z):
                for x in range(min_x, min_x + size_x):
                    blocks.append(self.grid.get_block(x - min_x, y - min_y, z - min_z))
        return blocks

    def update_state_hash(self) -> int:
        """Calculates authoritative xxHash64 canonical state hash using libmtk_py core."""
        blocks = self.get_canonical_blocks()
        self.current_state_hash = libmtk_py.compute_canonical_state_hash(
            self.origin[0], self.origin[1], self.origin[2],
            self.size[0], self.size[1], self.size[2],
            "minecraft:overworld",
            blocks,
            None,
        )
        return self.current_state_hash

    async def start(self) -> None:
        """Starts TCP listener."""
        server = await asyncio.start_server(self._handle_connection, self.host, self.port)
        self._server_obj = server
        addr = f"ws://{self.host}:{self.port}"
        print("=" * 65)
        print(f"🚀 [MockSyncServer] Live Sync WebSocket Server (RFC v3.1) Started at: {addr}")
        print(f"📦 [Settings] Preset: '{self.preset}' | Mode: '{self.mode}' | Size: {self.size}")
        print(f"📍 [Bounds] Origin: {self.origin} | Total Blocks: {self.size[0] * self.size[1] * self.size[2]:,}")
        print(f"🔑 [UUID] Server: {self.server_uuid.hex} | StateHash: 0x{self.current_state_hash:016x}")
        if self.delta_interval > 0:
            print(f"⚡ [Live Deltas] Automated mutations enabled every {self.delta_interval:.1f}s")
        print("=" * 65)
        print("💡 Terminal Controls: Press [D] for delta, [F] for full sync, [M] for manifest, [Q] to quit")

        # Spawn delta worker
        if self.delta_interval > 0:
            asyncio.create_task(self._delta_worker())

        async with server:
            try:
                await server.serve_forever()
            except asyncio.CancelledError:
                pass

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Performs WebSocket HTTP upgrade handshake then starts packet loop."""
        request_line = await reader.readline()
        if not request_line:
            writer.close()
            return

        headers = {}
        while True:
            line = await reader.readline()
            if not line or line == b"\r\n":
                break
            parts = line.decode("utf-8", "ignore").strip().split(":", 1)
            if len(parts) == 2:
                headers[parts[0].strip().lower()] = parts[1].strip()

        ws_key = headers.get("sec-websocket-key")
        if not ws_key:
            writer.close()
            return

        # Calculate RFC 6455 response key
        magic_guid = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        sha = hashlib.sha1(ws_key.encode("utf-8") + magic_guid).digest()
        accept_key = base64.b64encode(sha).decode("utf-8")

        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key}\r\n\r\n"
        )
        writer.write(response.encode("utf-8"))
        await writer.drain()

        client = MinimalWebSocketClient(reader, writer)
        self.clients.add(client)
        print(f"🟢 [Client] DCC client connected from {writer.get_extra_info('peername')}")

        try:
            # 1. Read HELLO packet (0x01)
            msg = await client.read_frame()
            if not msg:
                return
            hello = libmtk_py.decode_packet(msg)
            if hello.get("type") != "HELLO":
                print(f"⚠️ [Protocol Error] Expected HELLO, got {hello.get('type')}")
                return

            cached_uuid = hello.get("cached_world_uuid", b"")
            cached_epoch = hello.get("cached_epoch", 0)
            cached_seq = hello.get("cached_seq", 0)
            cached_hash = hello.get("cached_state_hash", "")
            state_hash_hex = f"0x{self.current_state_hash:016x}"

            if (cached_uuid == self.server_uuid_bytes and
                cached_epoch == self.epoch and
                cached_seq == self.seq_id and
                (cached_hash == state_hash_hex or cached_hash == str(self.current_state_hash))):
                decision = 0  # VERIFIED_SKIP_REBUILD
                print("⚡ [Handshake] Cached state verified -> 0ms VERIFIED_SKIP_REBUILD")
            else:
                decision = 2  # FULL_BASELINE_REQUIRED
                print("📦 [Handshake] Cache mismatch or initial sync -> FULL_BASELINE_REQUIRED")

            # 2. Send WELCOME packet (0x02)
            welcome_bytes = libmtk_py.encode_welcome(
                server_uuid=self.server_uuid_bytes,
                epoch=self.epoch,
                sequence=self.seq_id,
                decision=decision,
                current_min=self.origin,
                current_size=self.size,
                current_state_hash=self.current_state_hash,
                dimension="minecraft:overworld",
                negotiated_version=3,
            )
            await client.send_binary(welcome_bytes)

            # 3. If baseline required, stream baseline
            if decision == 2:
                await self._send_baseline(client)

            # 4. Inbound listener
            while client.is_open:
                msg = await client.read_frame()
                if msg is None:
                    break
                decoded = libmtk_py.decode_packet(msg)
                if decoded:
                    await self._handle_client_event(client, decoded)

        except Exception as e:
            print(f"⚠️ [Client Error]: {e}")
        finally:
            self.clients.discard(client)
            writer.close()
            print("🔴 [Client] Client disconnected.")

    async def _send_baseline(self, client: MinimalWebSocketClient) -> None:
        """Sends BaselineBegin (0x03) -> BaselineChunk (0x04) -> BaselineEnd (0x05)."""
        self.update_state_hash()
        blocks = self.get_canonical_blocks()
        palette = list(self.grid.palette)
        self.synced_palette_count = len(palette)
        self.palette_revision = 1
        palette_lookup = dict(self.grid.palette_lookup)
        indices = [palette_lookup[b] for b in blocks]
        bits = 8 if len(palette) <= 256 else 16
        payload = bytes(indices) if bits == 8 else struct.pack(f"<{len(indices)}H", *indices)

        print(f"📤 [Baseline] Sending Baseline ({len(blocks):,} blocks, {len(palette)} palette entries)...")
        t0 = time.perf_counter()

        begin_pkt = libmtk_py.encode_baseline_begin(
            epoch=self.epoch,
            snapshot_uuid=self.snapshot_uuid_bytes,
            snapshot_seq=self.seq_id,
            min_pos=self.origin,
            size=self.size,
            state_hash=self.current_state_hash,
            palette_revision=1,
            total_chunks=1,
            total_encoded_bytes=len(payload),
            total_decoded_bytes=len(payload),
            compression_mode=0,
            palette_bits_per_block=bits,
            biome_bits_per_quart=0,
            dimension="minecraft:overworld",
            block_palette=palette,
            biome_palette=["minecraft:plains"],
        )
        await client.send_binary(begin_pkt)

        chunk_pkt = libmtk_py.encode_baseline_chunk(
            epoch=self.epoch,
            snapshot_uuid=self.snapshot_uuid_bytes,
            chunk_index=0,
            total_chunks=1,
            first_voxel_index=0,
            voxel_count=len(blocks),
            decoded_target_bytes=len(payload),
            payload=payload,
            chunk_xxhash64=0,
        )
        await client.send_binary(chunk_pkt)

        end_pkt = libmtk_py.encode_baseline_end(
            epoch=self.epoch,
            snapshot_uuid=self.snapshot_uuid_bytes,
            snapshot_seq=self.seq_id,
            total_chunks_sent=1,
            final_state_hash=self.current_state_hash,
            status=0,
        )
        await client.send_binary(end_pkt)
        t1 = time.perf_counter()
        print(f"✅ [Baseline] Baseline sent ({len(payload):,} bytes) in {(t1 - t0)*1000:.1f}ms")

    async def _handle_client_event(self, client: MinimalWebSocketClient, event: Dict[str, Any]) -> None:
        """Handles client commands."""
        ev_type = event.get("type")
        if ev_type in ("RESYNC_REQUEST", "REQ_FULL_SYNC"):
            print("📩 [Client Req] Full Baseline Resync Requested.")
            await self._send_baseline(client)
        elif ev_type == "BASELINE_ACK":
            print(f"✅ [Client Ack] Baseline committed sequence={event.get('committed_seq')}")

    async def broadcast_delta(self, changes: List[Tuple[Tuple[int, int, int], str]]) -> None:
        """Broadcasts incremental DELTA_OP to all active clients."""
        if not self.clients or not changes:
            return

        new_palette_entries = []
        entries = []
        for (rx, ry, rz), state in changes:
            if state not in self.grid.palette_lookup:
                idx = self.grid.register_block(state)
                new_palette_entries.append((idx, state))
            else:
                idx = self.grid.palette_lookup[state]
            entries.append((rx, ry, rz, idx))

        if new_palette_entries and hasattr(libmtk_py, "encode_palette_update"):
            self.palette_revision += 1
            pal_pkt = libmtk_py.encode_palette_update(
                epoch=self.epoch,
                seq_id=self.seq_id,
                base_revision=self.palette_revision - 1,
                new_revision=self.palette_revision,
                entries=new_palette_entries,
            )
            for client in list(self.clients):
                try:
                    await client.send_binary(pal_pkt)
                except Exception:
                    pass

        self.seq_id += 1
        delta_pkt = libmtk_py.encode_delta_op(
            epoch=self.epoch,
            seq_id=self.seq_id,
            palette_revision=self.palette_revision,
            entries=entries,
        )

        for client in list(self.clients):
            try:
                await client.send_binary(delta_pkt)
            except Exception:
                pass

        for (rx, ry, rz), state in changes:
            wx, wy, wz = self.origin[0] + rx, self.origin[1] + ry, self.origin[2] + rz
            print(f"⚡ [Delta #{self.seq_id}] Block at ({wx}, {wy}, {wz}) -> {state}")

    async def _delta_worker(self) -> None:
        """Background loop simulating active Minecraft gameplay edits."""
        while self.is_running:
            await asyncio.sleep(self.delta_interval)
            if not self.clients:
                continue

            # Pick 1-3 random blocks to mutate
            count = random.randint(1, 3)
            changes = []
            for _ in range(count):
                rx = random.randint(0, self.size[0] - 1)
                ry = random.randint(2, min(self.size[1] - 1, 15))
                rz = random.randint(0, self.size[2] - 1)

                curr = self.grid.get_block(rx, ry, rz)
                if curr == "minecraft:air":
                    new_state = random.choice(COMPLEX_PALETTE_SAMPLES)
                else:
                    new_state = "minecraft:air"

                self.grid.set_block(rx, ry, rz, new_state)
                changes.append(((rx, ry, rz), new_state))

            await self.broadcast_delta(changes)

    async def broadcast_full_snapshot(self, preset: Optional[str] = None) -> None:
        """Regenerates terrain (if preset provided) and broadcasts Baseline to all connected clients."""
        if preset is not None:
            self.preset = preset
            self.grid = generate_terrain(self.preset, self.origin, self.size)
        self.seq_id += 1
        self.update_state_hash()
        for client in list(self.clients):
            try:
                await self._send_baseline(client)
            except Exception:
                pass

    async def broadcast_selection_resize(
        self,
        new_origin: Tuple[int, int, int],
        new_size: Tuple[int, int, int],
        preset: Optional[str] = None,
    ) -> None:
        """Resizes the selection bounding box, broadcasts Baseline."""
        self.origin = new_origin
        self.size = new_size
        if preset is not None:
            self.preset = preset
        self.grid = generate_terrain(self.preset, self.origin, self.size)
        self.seq_id += 1
        self.update_state_hash()
        for client in list(self.clients):
            try:
                await self._send_baseline(client)
            except Exception:
                pass

    def stop(self) -> None:
        """Stops the mock server and disconnects clients."""
        self.is_running = False
        if hasattr(self, "_server_obj") and self._server_obj:
            try:
                self._server_obj.close()
            except Exception:
                pass
        for client in list(self.clients):
            try:
                client.writer.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# CLI Argument Parser & Entry Point
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="MoziToolKit Mock Live Sync WebSocket Server")
    parser.add_argument("--host", default="127.0.0.1", help="WebSocket bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="WebSocket bind port (default: 8765)")
    parser.add_argument(
        "--preset",
        choices=["flat", "hills", "complex", "fluids", "benchmark", "issues", "regression"],
        default="complex",
        help="Terrain & block test preset (default: complex)",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "stream"],
        default="full",
        help="Snapshot sync mode: 'full' (0x02) or 'stream' (0x06) (default: full)",
    )
    parser.add_argument("--origin", nargs=3, type=int, default=[0, 64, 0], help="World min origin X Y Z")
    parser.add_argument("--size", nargs=3, type=int, default=[32, 32, 32], help="World bounding size X Y Z")
    parser.add_argument("--delta", type=float, default=0.0, help="Interval in seconds for auto deltas (0.0 to disable)")
    return parser.parse_args()


async def main():
    args = parse_args()
    server = MockLiveSyncServer(
        host=args.host,
        port=args.port,
        preset=args.preset,
        mode=args.mode,
        origin=tuple(args.origin),
        size=tuple(args.size),
        delta_interval=args.delta,
    )
    await server.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server shutdown cleanly.")

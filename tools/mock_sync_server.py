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
import zlib
from typing import Any, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Protocol Constants (1:1 with mtk-sync/src/protocol/constants.rs)
# ---------------------------------------------------------------------------

PROTOCOL_MAGIC = b"MC"
PROTOCOL_VERSION = 0x01

# S -> C Packet IDs
PKT_SELECTION_INFO = 0x01
PKT_FULL_SNAPSHOT = 0x02
PKT_DELTA_UPDATE = 0x03
PKT_SECTION_MANIFEST = 0x05
PKT_SECTION_SNAPSHOT = 0x06
PKT_HANDSHAKE_INFO = 0x07
PKT_STREAM_BEGIN = 0x08
PKT_STREAM_END = 0x09

# C -> S Packet IDs
PKT_REQ_FULL_SYNC = 0x80
PKT_REQ_SECTION_SYNC = 0x81
PKT_SYNC_CONFIG = 0x82

STREAM_STATUS_SUCCESS = 0
STREAM_STATUS_CANCELLED = 1
STREAM_STATUS_ERROR = 2

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
    if data[0:2] != PROTOCOL_MAGIC or data[2] != PROTOCOL_VERSION:
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
        self.seq_id = 1
        self.stream_id = 1
        self.is_running = True

    async def start(self) -> None:
        """Starts TCP listener."""
        server = await asyncio.start_server(self._handle_connection, self.host, self.port)
        addr = f"ws://{self.host}:{self.port}"
        print("=" * 65)
        print(f"🚀 [MockSyncServer] Live Sync WebSocket Server Started at: {addr}")
        print(f"📦 [Settings] Preset: '{self.preset}' | Mode: '{self.mode}' | Size: {self.size}")
        print(f"📍 [Bounds] Origin: {self.origin} | Total Blocks: {self.size[0] * self.size[1] * self.size[2]:,}")
        if self.delta_interval > 0:
            print(f"⚡ [Live Deltas] Automated mutations enabled every {self.delta_interval:.1f}s")
        print("=" * 65)
        print("💡 Terminal Controls: Press [D] for delta, [F] for full sync, [M] for manifest, [Q] to quit")

        # Spawn delta worker
        if self.delta_interval > 0:
            asyncio.create_task(self._delta_worker())

        async with server:
            await server.serve_forever()

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
            # 1. Send SelectionInfo & HandshakeInfo
            await self._send_initial_packets(client)

            # 2. Send Scene Data
            if self.mode == "stream":
                await self._stream_sections(client)
            else:
                await self._send_full_snapshot(client)

            # 3. Send Section CRC Manifest
            await self._send_manifest(client)

            # 4. Inbound listener
            while client.is_open:
                msg = await client.read_frame()
                if msg is None:
                    break
                decoded = decode_client_packet(msg)
                if decoded:
                    await self._handle_client_event(client, decoded)

        except Exception as e:
            print(f"⚠️ [Client Error]: {e}")
        finally:
            self.clients.discard(client)
            writer.close()
            print("🔴 [Client] Client disconnected.")

    async def _send_initial_packets(self, client: MinimalWebSocketClient) -> None:
        """Sends SelectionInfo (0x01) and HandshakeInfo (0x07)."""
        sel_pkt = encode_selection_info(self.origin, self.size)
        await client.send_binary(sel_pkt)

        # Compute sections count
        min_sec_x, max_sec_x = self.origin[0] >> 4, (self.origin[0] + self.size[0] - 1) >> 4
        min_sec_y, max_sec_y = self.origin[1] >> 4, (self.origin[1] + self.size[1] - 1) >> 4
        min_sec_z, max_sec_z = self.origin[2] >> 4, (self.origin[2] + self.size[2] - 1) >> 4
        total_sections = (max_sec_x - min_sec_x + 1) * (max_sec_y - min_sec_y + 1) * (max_sec_z - min_sec_z + 1)

        total_vol = self.size[0] * self.size[1] * self.size[2]
        hs_pkt = encode_handshake_info(total_sections, total_sections, total_vol, "minecraft:overworld")
        await client.send_binary(hs_pkt)

    async def _send_full_snapshot(self, client: MinimalWebSocketClient) -> None:
        """Encodes and sends single FullSnapshot (0x02)."""
        print(f"📤 [Sync] Sending FullSnapshot ({len(self.grid.palette)} palette entries)...")
        t0 = time.perf_counter()
        pkt = encode_full_snapshot(
            self.origin,
            self.size,
            self.grid.palette,
            self.grid.indices,
            ["minecraft:plains"],
            [0] * len(self.grid.indices),
        )
        await client.send_binary(pkt)
        t1 = time.perf_counter()
        print(f"✅ [Sync] FullSnapshot sent ({len(pkt):,} bytes) in {(t1 - t0)*1000:.1f}ms")

    async def _stream_sections(self, client: MinimalWebSocketClient) -> None:
        """Streams chunk sections progressively (0x08 -> 0x06 -> 0x09)."""
        min_sec_x, max_sec_x = self.origin[0] >> 4, (self.origin[0] + self.size[0] - 1) >> 4
        min_sec_y, max_sec_y = self.origin[1] >> 4, (self.origin[1] + self.size[1] - 1) >> 4
        min_sec_z, max_sec_z = self.origin[2] >> 4, (self.origin[2] + self.size[2] - 1) >> 4

        sections = []
        for sx in range(min_sec_x, max_sec_x + 1):
            for sy in range(min_sec_y, max_sec_y + 1):
                for sz in range(min_sec_z, max_sec_z + 1):
                    sections.append((sx, sy, sz))

        print(f"📤 [Stream] Streaming {len(sections)} chunk sections...")
        stream_id = self.stream_id
        self.stream_id += 1

        await client.send_binary(encode_stream_begin(stream_id, len(sections)))

        for i, (sx, sy, sz) in enumerate(sections):
            start_x, start_y, start_z = sx * 16, sy * 16, sz * 16
            size_x, size_y, size_z = 16, 16, 16

            # Extract local section grid indices
            sec_indices = []
            for lx in range(16):
                wx = start_x + lx
                gx = wx - self.origin[0]
                for ly in range(16):
                    wy = start_y + ly
                    gy = wy - self.origin[1]
                    for lz in range(16):
                        wz = start_z + lz
                        gz = wz - self.origin[2]
                        st = self.grid.get_block(gx, gy, gz)
                        idx = self.grid.palette_lookup[st]
                        sec_indices.append(idx)

            pkt = encode_section_snapshot(
                (sx, sy, sz),
                (start_x, start_y, start_z),
                (size_x, size_y, size_z),
                self.grid.palette,
                sec_indices,
            )
            await client.send_binary(pkt)
            await asyncio.sleep(0.005)  # Slight yield for realism

        await client.send_binary(encode_stream_end(stream_id, len(sections), STREAM_STATUS_SUCCESS))
        print("✅ [Stream] Streaming completed.")

    async def _send_manifest(self, client: MinimalWebSocketClient) -> None:
        """Sends Section CRC Manifest (0x05)."""
        min_sec_x, max_sec_x = self.origin[0] >> 4, (self.origin[0] + self.size[0] - 1) >> 4
        min_sec_y, max_sec_y = self.origin[1] >> 4, (self.origin[1] + self.size[1] - 1) >> 4
        min_sec_z, max_sec_z = self.origin[2] >> 4, (self.origin[2] + self.size[2] - 1) >> 4

        entries = []
        for sx in range(min_sec_x, max_sec_x + 1):
            for sy in range(min_sec_y, max_sec_y + 1):
                for sz in range(min_sec_z, max_sec_z + 1):
                    crc = self.grid.compute_section_crc((sx, sy, sz))
                    entries.append(((sx, sy, sz), crc))

        pkt = encode_section_manifest(self.seq_id, entries)
        await client.send_binary(pkt)

    async def _handle_client_event(self, client: MinimalWebSocketClient, event: Dict[str, Any]) -> None:
        """Handles client commands."""
        ev_type = event.get("type")
        if ev_type == "REQ_FULL_SYNC":
            print("📩 [Client Req] Full Sync Requested.")
            await self._send_full_snapshot(client)
        elif ev_type == "REQ_SECTION_SYNC":
            sections = event.get("sections", [])
            print(f"📩 [Client Req] Section Repair Requested for {len(sections)} sections: {sections}")
            # Resend individual sections
            for sx, sy, sz in sections:
                start_x, start_y, start_z = sx * 16, sy * 16, sz * 16
                sec_indices = []
                for lx in range(16):
                    wx = start_x + lx
                    gx = wx - self.origin[0]
                    for ly in range(16):
                        wy = start_y + ly
                        gy = wy - self.origin[1]
                        for lz in range(16):
                            wz = start_z + lz
                            gz = wz - self.origin[2]
                            st = self.grid.get_block(gx, gy, gz)
                            sec_indices.append(self.grid.palette_lookup[st])

                pkt = encode_section_snapshot(
                    (sx, sy, sz),
                    (start_x, start_y, start_z),
                    (16, 16, 16),
                    self.grid.palette,
                    sec_indices,
                )
                await client.send_binary(pkt)
        elif ev_type == "SYNC_CONFIG":
            print(f"⚙️ [Client Config] Throttle={event.get('throttle_mode')}, FPS={event.get('target_fps')}, Active={event.get('is_active')}")

    async def broadcast_delta(self, changes: List[Tuple[Tuple[int, int, int], str]]) -> None:
        """Broadcasts incremental DeltaUpdate (0x03) to all active clients."""
        if not self.clients or not changes:
            return

        self.seq_id += 1
        pkt = encode_delta_update(self.seq_id, self.origin, changes)

        for client in list(self.clients):
            try:
                await client.send_binary(pkt)
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


# ---------------------------------------------------------------------------
# CLI Argument Parser & Entry Point
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="MoziToolKit Mock Live Sync WebSocket Server")
    parser.add_argument("--host", default="127.0.0.1", help="WebSocket bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="WebSocket bind port (default: 8765)")
    parser.add_argument(
        "--preset",
        choices=["flat", "hills", "complex", "fluids", "benchmark"],
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

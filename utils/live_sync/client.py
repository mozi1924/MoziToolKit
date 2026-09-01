"""
WebSocket Client for MoziToolKit Live Sync.
Listens to binary block delta streaming from the Minecraft Fabric Mod (Yefira).
"""

from __future__ import annotations

import asyncio
import logging
import struct
import threading
import time
from typing import Callable, List, Optional, Tuple

from .constants import (
    PROTOCOL_MAGIC,
    PROTOCOL_VERSION,
    PacketType,
    HEADER_FORMAT,
    HEADER_SIZE,
    SELECTION_INFO_FORMAT,
    SELECTION_INFO_SIZE,
    DELTA_HEADER_FORMAT,
    DELTA_HEADER_SIZE,
    DELTA_CHANGE_PREFIX_FORMAT,
    DELTA_CHANGE_PREFIX_SIZE,
    MANIFEST_HEADER_FORMAT,
    MANIFEST_HEADER_SIZE,
    MANIFEST_ENTRY_FORMAT,
    MANIFEST_ENTRY_SIZE,
    SECTION_SNAPSHOT_HEADER_FORMAT,
    SECTION_SNAPSHOT_HEADER_SIZE,
    HANDSHAKE_INFO_HEADER_FORMAT,
    HANDSHAKE_INFO_HEADER_SIZE,
    STREAM_BEGIN_FORMAT,
    STREAM_BEGIN_SIZE,
    STREAM_END_FORMAT,
    STREAM_END_SIZE,
)

logger = logging.getLogger("MoziToolKit.LiveSync")


class SyncClientThread(threading.Thread):
    """Background daemon thread managing the asynchronous WebSocket client connection."""

    def __init__(
        self,
        url: str,
        on_status_change: Callable[[str], None],
        on_selection_info: Callable[[int, int, int, int, int, int], None],
        on_full_snapshot: Callable[[int, int, int, int, int, int, List[str], List[int]], None],
        on_delta_update: Callable[[int, int, int, List[Tuple[int, int, int, str]], int], None],
        on_section_manifest: Optional[Callable[[int, List[Tuple[int, int, int, int]]], None]] = None,
        on_section_snapshot: Optional[Callable[[int, int, int, int, int, int, int, int, int, List[str], List[int]], None]] = None,
        on_handshake_info: Optional[Callable[[int, int, int, str, int], None]] = None,
        on_stream_begin: Optional[Callable[[int, int, int], None]] = None,
        on_stream_end: Optional[Callable[[int, int, int], None]] = None,
        auto_reconnect: bool = True,
        max_reconnect_attempts: int = 5,
        timeout: float = 10.0,
    ) -> None:
        super().__init__(daemon=True)
        self.url = url
        self.on_status_change = on_status_change
        self.on_selection_info = on_selection_info
        self.on_full_snapshot = on_full_snapshot
        self.on_delta_update = on_delta_update
        self.on_section_manifest = on_section_manifest
        self.on_section_snapshot = on_section_snapshot
        self.on_handshake_info = on_handshake_info
        self.on_stream_begin = on_stream_begin
        self.on_stream_end = on_stream_end
        self.auto_reconnect = auto_reconnect
        self.max_reconnect_attempts = max_reconnect_attempts
        self.timeout: float = max(1.0, float(timeout)) if timeout else 10.0
        self.reconnect_attempts: int = 0
        self.running = True
        self.is_connected = False
        self.websocket = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._connect_and_listen())
        finally:
            try:
                self.loop.close()
            except Exception:
                pass

    def stop(self) -> None:
        """Signal thread and event loop to cleanly disconnect, cancel retries, and terminate."""
        self.running = False
        self.auto_reconnect = False
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self._cancel_all_tasks)

    def _cancel_all_tasks(self) -> None:
        for task in asyncio.all_tasks(self.loop):
            task.cancel()

    async def _connect_and_listen(self) -> None:
        try:
            import websockets
        except ImportError:
            self.on_status_change("Missing 'websockets' library")
            logger.error("Missing 'websockets' module.")
            return

        while self.running:
            if self.reconnect_attempts > 0:
                self.on_status_change(f"RECONNECTING... ({self.reconnect_attempts}/{self.max_reconnect_attempts})")
            else:
                self.on_status_change("CONNECTING...")
            logger.info(f"Connecting to Minecraft Live Sync WebSocket at: {self.url}")

            try:
                # Use user timeout for connection handshake with sensible bounds
                connect_timeout = max(10.0, float(self.timeout))
                async with websockets.connect(
                    self.url,
                    max_size=None,  # No artificial limit on frame size for high-res voxel sync
                    max_queue=None,  # Unlimited queue to prevent buffer drops during massive section streams
                    open_timeout=connect_timeout,
                    close_timeout=connect_timeout,
                    ping_interval=None,  # Rely on continuous binary frame stream and TCP transport
                    ping_timeout=None,
                ) as websocket:
                    self.websocket = websocket
                    self.is_connected = True
                    self.reconnect_attempts = 0
                    self.on_status_change("CONNECTED")
                    logger.info("Connected to Minecraft Live Sync server successfully.")

                    while self.running and self.is_connected:
                        try:
                            message = await websocket.recv()
                            if isinstance(message, bytes):
                                self._parse_binary_packet(message)
                            elif isinstance(message, str):
                                logger.debug(f"Received text message: {message}")
                        except websockets.ConnectionClosed:
                            logger.info("WebSocket connection closed by server.")
                            break
                        except asyncio.CancelledError:
                            break
                        except Exception as e:
                            logger.error(f"Error receiving message: {e}")
                            break
            except asyncio.CancelledError:
                break
            except (ConnectionRefusedError, OSError) as e:
                if not self.running:
                    break
                logger.warning(f"Live Sync connection failed ({self.url}): {e}")
                self.reconnect_attempts += 1
                if not self.auto_reconnect or self.reconnect_attempts > self.max_reconnect_attempts:
                    self.on_status_change(f"DISCONNECTED (Connection failed: {e})")
                    break
                self.on_status_change(f"RECONNECTING... ({self.reconnect_attempts}/{self.max_reconnect_attempts})")
            except Exception as e:
                if not self.running:
                    break
                self.reconnect_attempts += 1
                if self.reconnect_attempts > self.max_reconnect_attempts:
                    logger.warning(f"Live Sync: Exceeded max reconnection attempts ({self.max_reconnect_attempts}). Stopping.")
                    self.on_status_change(f"DISCONNECTED (Exceeded {self.max_reconnect_attempts} reconnect attempts)")
                    break
                logger.warning(f"Failed to connect to Live Sync WebSocket: {e}. Will retry ({self.reconnect_attempts}/{self.max_reconnect_attempts})...")
                self.on_status_change(f"RECONNECTING... ({self.reconnect_attempts}/{self.max_reconnect_attempts})")
            finally:
                self.is_connected = False
                self.websocket = None

            if self.running and self.auto_reconnect and self.reconnect_attempts <= self.max_reconnect_attempts:
                try:
                    await asyncio.sleep(1.5)
                except asyncio.CancelledError:
                    break
            else:
                break

        if not self.running:
            self.on_status_change("DISCONNECTED")
        elif self.reconnect_attempts > self.max_reconnect_attempts:
            self.on_status_change(f"DISCONNECTED (Failed after {self.max_reconnect_attempts} attempts)")

    def send_full_sync_request(self) -> None:
        """Send Full Sync Request (0x80) to request a complete snapshot from server."""
        if not self.is_connected or not self.websocket or not self.loop:
            return

        packet = bytearray()
        packet.extend(PROTOCOL_MAGIC)
        packet.append(PROTOCOL_VERSION)
        packet.append(PacketType.FULL_SYNC_REQUEST)

        async def _send():
            try:
                if self.websocket:
                    await self.websocket.send(bytes(packet))
            except Exception as e:
                logger.error(f"Failed to send full sync request: {e}")

        asyncio.run_coroutine_threadsafe(_send(), self.loop)

    def send_repair_request(self, sections: List[Tuple[int, int, int]]) -> None:
        """Send Section Repair Requests (0x81) in batches to keep frames lightweight."""
        if not self.is_connected or not self.websocket or not self.loop or not sections:
            return

        # Chunk into batches of at most 64 sections per packet
        batch_size = 64
        batches = [sections[i:i + batch_size] for i in range(0, len(sections), batch_size)]

        async def _send_batches():
            try:
                for batch in batches:
                    if not self.websocket or not self.is_connected:
                        break
                    packet = bytearray()
                    packet.extend(PROTOCOL_MAGIC)
                    packet.append(PROTOCOL_VERSION)
                    packet.append(PacketType.REPAIR_REQUEST)
                    packet.extend(struct.pack('<H', len(batch)))
                    for sx, sy, sz in batch:
                        packet.extend(struct.pack('<iii', sx, sy, sz))
                    await self.websocket.send(bytes(packet))
            except Exception as e:
                logger.error(f"Failed to send repair request batch: {e}")

        asyncio.run_coroutine_threadsafe(_send_batches(), self.loop)

    def send_sync_config(self, throttle_mode: int = 0, target_fps: int = 60, is_active: bool = True) -> None:
        """Send a Sync Config (0x82) to adapt server-side broadcast and throttle delivery."""
        if not self.is_connected or not self.websocket or not self.loop:
            return

        packet = bytearray()
        packet.extend(PROTOCOL_MAGIC)
        packet.append(PROTOCOL_VERSION)
        packet.append(PacketType.SYNC_CONFIG)
        flags = 1 if is_active else 0
        packet.extend(struct.pack('<BBB', throttle_mode & 0xFF, target_fps & 0xFF, flags & 0xFF))

        async def _send():
            try:
                if self.websocket:
                    await self.websocket.send(bytes(packet))
            except Exception as e:
                logger.debug(f"Failed to send sync config: {e}")

        asyncio.run_coroutine_threadsafe(_send(), self.loop)

    def _parse_binary_packet(self, data: bytes) -> None:
        if len(data) < HEADER_SIZE:
            return

        magic, version, packet_type = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
        if magic != PROTOCOL_MAGIC:
            logger.warning(f"Invalid magic header: {magic}")
            return

        offset = HEADER_SIZE
        if packet_type == PacketType.SELECTION_INFO:
            if len(data) < offset + SELECTION_INFO_SIZE:
                return
            min_x, min_y, min_z, size_x, size_y, size_z = struct.unpack(SELECTION_INFO_FORMAT, data[offset:offset + SELECTION_INFO_SIZE])
            self.on_selection_info(min_x, min_y, min_z, size_x, size_y, size_z)

        elif packet_type == PacketType.FULL_SNAPSHOT:
            if len(data) < offset + SELECTION_INFO_SIZE + 2:
                return
            min_x, min_y, min_z, size_x, size_y, size_z = struct.unpack(SELECTION_INFO_FORMAT, data[offset:offset + SELECTION_INFO_SIZE])
            offset += SELECTION_INFO_SIZE

            palette_count = struct.unpack('<H', data[offset:offset + 2])[0]
            offset += 2

            palette = []
            for _ in range(palette_count):
                if len(data) < offset + 2:
                    return
                str_len = struct.unpack('<H', data[offset:offset + 2])[0]
                offset += 2
                if len(data) < offset + str_len:
                    return
                item_str = data[offset:offset + str_len].decode('utf-8', errors='replace')
                offset += str_len
                palette.append(item_str)

            if len(data) < offset + 1:
                return
            index_bytes_per_block = data[offset]
            offset += 1

            total_blocks = size_x * size_y * size_z
            grid_indices_raw = data[offset:]
            if index_bytes_per_block == 1:
                grid_indices = list(grid_indices_raw[:total_blocks])
                offset += total_blocks
            else:
                grid_indices = list(struct.unpack(f'<{total_blocks}H', grid_indices_raw[:total_blocks * 2]))
                offset += total_blocks * 2

            biome_palette = []
            biome_indices = []
            if len(data) >= offset + 2:
                b_count = struct.unpack('<H', data[offset:offset + 2])[0]
                offset += 2
                for _ in range(b_count):
                    if len(data) < offset + 2:
                        break
                    b_str_len = struct.unpack('<H', data[offset:offset + 2])[0]
                    offset += 2
                    if len(data) < offset + b_str_len:
                        break
                    b_str = data[offset:offset + b_str_len].decode('utf-8', errors='replace')
                    offset += b_str_len
                    biome_palette.append(b_str)

                if b_count == 1:
                    biome_indices = [0] * total_blocks
                elif b_count > 1 and len(data) >= offset + 1:
                    b_idx_bytes = data[offset]
                    offset += 1
                    b_raw = data[offset:]
                    if b_idx_bytes == 1:
                        biome_indices = list(b_raw[:total_blocks])
                    else:
                        biome_indices = list(struct.unpack(f'<{total_blocks}H', b_raw[:total_blocks * 2]))

            try:
                self.on_full_snapshot(min_x, min_y, min_z, size_x, size_y, size_z, palette, grid_indices, biome_palette, biome_indices)
            except TypeError:
                self.on_full_snapshot(min_x, min_y, min_z, size_x, size_y, size_z, palette, grid_indices)

        elif packet_type == PacketType.DELTA_UPDATE:
            if len(data) < offset + DELTA_HEADER_SIZE:
                return
            seq_id, min_x, min_y, min_z, change_count = struct.unpack(DELTA_HEADER_FORMAT, data[offset:offset + DELTA_HEADER_SIZE])
            offset += DELTA_HEADER_SIZE

            changes = []
            for _ in range(change_count):
                if len(data) < offset + DELTA_CHANGE_PREFIX_SIZE:
                    return
                rel_x, rel_y, rel_z, str_len = struct.unpack(DELTA_CHANGE_PREFIX_FORMAT, data[offset:offset + DELTA_CHANGE_PREFIX_SIZE])
                offset += DELTA_CHANGE_PREFIX_SIZE
                if len(data) < offset + str_len:
                    return
                state_str = data[offset:offset + str_len].decode('utf-8', errors='replace')
                offset += str_len
                abs_x, abs_y, abs_z = min_x + rel_x, min_y + rel_y, min_z + rel_z
                changes.append((abs_x, abs_y, abs_z, state_str))

            self.on_delta_update(min_x, min_y, min_z, changes, seq_id)

        elif packet_type == PacketType.SECTION_MANIFEST:
            if len(data) < offset + MANIFEST_HEADER_SIZE:
                return
            current_seq_id, section_count = struct.unpack(MANIFEST_HEADER_FORMAT, data[offset:offset + MANIFEST_HEADER_SIZE])
            offset += MANIFEST_HEADER_SIZE

            sections = []
            for _ in range(section_count):
                if len(data) < offset + MANIFEST_ENTRY_SIZE:
                    return
                sec_x, sec_y, sec_z, crc32 = struct.unpack(MANIFEST_ENTRY_FORMAT, data[offset:offset + MANIFEST_ENTRY_SIZE])
                offset += MANIFEST_ENTRY_SIZE
                sections.append((sec_x, sec_y, sec_z, crc32))

            if self.on_section_manifest:
                self.on_section_manifest(current_seq_id, sections)

        elif packet_type == PacketType.SECTION_SNAPSHOT:
            if len(data) < offset + SECTION_SNAPSHOT_HEADER_SIZE:
                return
            sec_x, sec_y, sec_z, start_x, start_y, start_z, size_x, size_y, size_z, palette_count = struct.unpack(
                SECTION_SNAPSHOT_HEADER_FORMAT, data[offset:offset + SECTION_SNAPSHOT_HEADER_SIZE]
            )
            offset += SECTION_SNAPSHOT_HEADER_SIZE

            palette = []
            for _ in range(palette_count):
                if len(data) < offset + 2:
                    return
                str_len = struct.unpack('<H', data[offset:offset + 2])[0]
                offset += 2
                if len(data) < offset + str_len:
                    return
                item_str = data[offset:offset + str_len].decode('utf-8', errors='replace')
                offset += str_len
                palette.append(item_str)

            if len(data) < offset + 1:
                return
            index_bytes_per_block = data[offset]
            offset += 1

            total_blocks = size_x * size_y * size_z
            grid_indices_raw = data[offset:]
            if index_bytes_per_block == 1:
                grid_indices = list(grid_indices_raw[:total_blocks])
                offset += total_blocks
            else:
                grid_indices = list(struct.unpack(f'<{total_blocks}H', grid_indices_raw[:total_blocks * 2]))
                offset += total_blocks * 2

            biome_palette = []
            biome_indices = []
            if len(data) >= offset + 2:
                b_count = struct.unpack('<H', data[offset:offset + 2])[0]
                offset += 2
                for _ in range(b_count):
                    if len(data) < offset + 2:
                        break
                    b_str_len = struct.unpack('<H', data[offset:offset + 2])[0]
                    offset += 2
                    if len(data) < offset + b_str_len:
                        break
                    b_str = data[offset:offset + b_str_len].decode('utf-8', errors='replace')
                    offset += b_str_len
                    biome_palette.append(b_str)

                if b_count == 1:
                    biome_indices = [0] * total_blocks
                elif b_count > 1 and len(data) >= offset + 1:
                    b_idx_bytes = data[offset]
                    offset += 1
                    b_raw = data[offset:]
                    if b_idx_bytes == 1:
                        biome_indices = list(b_raw[:total_blocks])
                    else:
                        biome_indices = list(struct.unpack(f'<{total_blocks}H', b_raw[:total_blocks * 2]))

            if self.on_section_snapshot:
                try:
                    self.on_section_snapshot(sec_x, sec_y, sec_z, start_x, start_y, start_z, size_x, size_y, size_z, palette, grid_indices, biome_palette, biome_indices)
                except TypeError:
                    self.on_section_snapshot(sec_x, sec_y, sec_z, start_x, start_y, start_z, size_x, size_y, size_z, palette, grid_indices)

        elif packet_type == PacketType.HANDSHAKE_INFO:
            if len(data) < offset + HANDSHAKE_INFO_HEADER_SIZE:
                return
            total_sections, non_empty_sections, total_volume, dim_len = struct.unpack(
                HANDSHAKE_INFO_HEADER_FORMAT, data[offset:offset + HANDSHAKE_INFO_HEADER_SIZE]
            )
            offset += HANDSHAKE_INFO_HEADER_SIZE
            if len(data) < offset + dim_len + 2:
                return
            dimension = data[offset:offset + dim_len].decode('utf-8', errors='replace')
            offset += dim_len
            flags = struct.unpack('<H', data[offset:offset + 2])[0]

            if self.on_handshake_info:
                self.on_handshake_info(total_sections, non_empty_sections, total_volume, dimension, flags)

        elif packet_type == PacketType.STREAM_BEGIN:
            if len(data) < offset + STREAM_BEGIN_SIZE:
                return
            stream_id, total_sections, flags = struct.unpack(STREAM_BEGIN_FORMAT, data[offset:offset + STREAM_BEGIN_SIZE])
            if self.on_stream_begin:
                self.on_stream_begin(stream_id, total_sections, flags)

        elif packet_type == PacketType.STREAM_END:
            if len(data) < offset + STREAM_END_SIZE:
                return
            stream_id, sent_sections, status = struct.unpack(STREAM_END_FORMAT, data[offset:offset + STREAM_END_SIZE])
            if self.on_stream_end:
                self.on_stream_end(stream_id, sent_sections, status)

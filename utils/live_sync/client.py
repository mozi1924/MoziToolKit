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
    ) -> None:
        super().__init__(daemon=True)
        self.url = url
        self.on_status_change = on_status_change
        self.on_selection_info = on_selection_info
        self.on_full_snapshot = on_full_snapshot
        self.on_delta_update = on_delta_update
        self.on_section_manifest = on_section_manifest
        self.on_section_snapshot = on_section_snapshot
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
        """Signal thread and event loop to cleanly disconnect and terminate."""
        self.running = False
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

        self.on_status_change("CONNECTING...")
        logger.info(f"Connecting to Minecraft Live Sync WebSocket at: {self.url}")

        try:
            async with websockets.connect(self.url) as websocket:
                self.websocket = websocket
                self.is_connected = True
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
        except Exception as e:
            logger.error(f"Failed to connect to Live Sync WebSocket: {e}")
            self.on_status_change(f"ERROR: {e}")
        finally:
            self.is_connected = False
            self.websocket = None
            self.on_status_change("DISCONNECTED")

    def send_repair_request(self, sections: List[Tuple[int, int, int]]) -> None:
        """Send a Section Repair Request (0x04) back to server on background loop."""
        if not self.is_connected or not self.websocket or not self.loop:
            return

        packet = bytearray()
        packet.extend(PROTOCOL_MAGIC)
        packet.append(PROTOCOL_VERSION)
        packet.append(PacketType.REPAIR_REQUEST)
        packet.extend(struct.pack('<H', len(sections)))
        for sx, sy, sz in sections:
            packet.extend(struct.pack('<iii', sx, sy, sz))

        async def _send():
            try:
                if self.websocket:
                    await self.websocket.send(bytes(packet))
            except Exception as e:
                logger.error(f"Failed to send repair request: {e}")

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
            else:
                grid_indices = list(struct.unpack(f'<{total_blocks}H', grid_indices_raw[:total_blocks * 2]))

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
            else:
                grid_indices = list(struct.unpack(f'<{total_blocks}H', grid_indices_raw[:total_blocks * 2]))

            if self.on_section_snapshot:
                self.on_section_snapshot(sec_x, sec_y, sec_z, start_x, start_y, start_z, size_x, size_y, size_z, palette, grid_indices)

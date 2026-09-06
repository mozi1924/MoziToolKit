"""
Container SyncSession for Live Sync world root containers.
"""

from __future__ import annotations

import json
import logging
import queue
import time
from typing import Any, List, Optional, Set, Tuple
import bpy

from ..protocol.client import SyncClientThread
from ...mc_baker import clear_shared_baker_cache
from ..meshing import clear_mesh_builder_caches
from ..storage.voxel_storage import VoxelStorage
from ....pipeline.progress import ProgressBar
from .material_cache import extract_atlas_params
from .persistence import _MANIFEST_DICT_CACHE
from .props import (
    REBUILD_DEBOUNCE_SECONDS,
    get_active_sync_props,
    sync_palette_to_props,
)

logger = logging.getLogger("MoziToolKit.LiveSync.Session")


class SyncSession:
    """Manages the connection, storage, event queues, and build state for a specific world container."""

    def __init__(self, target_object_name: str, url: str = "ws://localhost:8765"):
        self.target_object_name: str = target_object_name
        self.url: str = url
        # Use dedicated VoxelStorage per container session
        self.storage: VoxelStorage = VoxelStorage()
        self.client_thread: Optional[SyncClientThread] = None

        self.delta_queue: queue.Queue = queue.Queue()
        self.stream_section_queue: queue.Queue = queue.Queue()
        self.accumulated_stream_palettes: Set[str] = set()

        self.last_seq_id: int = 0
        self.stream_total_sections: int = 0
        self.stream_received_sections: int = 0
        self.stream_last_drain_time: float = 0.0
        self.server_stream_finished: bool = False
        self.current_stream_id: int = 0

        self.is_streaming: bool = False
        self.is_initial_handshake: bool = True
        self.is_repairing_partial: bool = False
        self.pending_full_sync_request: bool = False
        self.force_next_full_rebuild: bool = False
        self.skip_next_full_snapshot: bool = False

        self.rebuild_timer_registered: bool = False
        self.pending_full_rebuild: bool = False

        self.cached_atlas_params: Optional[dict] = None
        self.cached_mat_signature: Optional[tuple] = None

        self._stream_state_cache: Optional[dict] = None
        self._existing_sections_cache: Optional[dict] = None

    def clear_caches(self) -> None:
        self.cached_atlas_params = None
        self.cached_mat_signature = None
        self._stream_state_cache = None
        self._existing_sections_cache = None
        clear_mesh_builder_caches()
        clear_shared_baker_cache()

    def get_cached_atlas_params(self, mat: Optional[bpy.types.Material] = None) -> dict:
        mat_id = mat.as_pointer() if mat and hasattr(mat, "as_pointer") else (id(mat) if mat else 0)
        if self.cached_atlas_params is not None and self.cached_mat_signature == mat_id:
            return self.cached_atlas_params

        self.cached_mat_signature = mat_id
        self.cached_atlas_params = extract_atlas_params(mat)
        return self.cached_atlas_params

    def schedule_mesh_sync(self, force_full_rebuild: bool = False) -> None:
        self.pending_full_rebuild = self.pending_full_rebuild or force_full_rebuild
        if self.rebuild_timer_registered:
            return

        self.rebuild_timer_registered = True

        def flush():
            try:
                if self.storage.size_x and self.storage.size_y and self.storage.size_z:
                    full_rebuild = self.pending_full_rebuild
                    self.pending_full_rebuild = False
                    target_obj = bpy.data.objects.get(self.target_object_name)
                    if target_obj:
                        from .event_pump import trigger_mesh_sync
                        trigger_mesh_sync(bpy.context, force_full_rebuild=full_rebuild, target_obj=target_obj, storage=self.storage)
                        for window in bpy.context.window_manager.windows:
                            for area in window.screen.areas:
                                if area.type in ('VIEW_3D', 'PROPERTIES'):
                                    area.tag_redraw()
            except Exception as e:
                logger.error(f"Deferred mesh sync error for {self.target_object_name}: {e}", exc_info=True)
            finally:
                self.rebuild_timer_registered = False
            return None

        bpy.app.timers.register(flush, first_interval=REBUILD_DEBOUNCE_SECONDS)

    def persist_sync_state_to_scene(self, target_obj: Optional[bpy.types.Object] = None) -> None:
        try:
            obj = target_obj or bpy.data.objects.get(self.target_object_name)
            if obj is not None:
                manifest_dict = self.storage.export_manifest_metadata()
                _MANIFEST_DICT_CACHE[obj.name] = manifest_dict
                obj["mtk:sync_manifest"] = json.dumps(manifest_dict)
                obj["mtk_block_bounds"] = [
                    self.storage.min_x, self.storage.min_y, self.storage.min_z,
                    self.storage.size_x, self.storage.size_y, self.storage.size_z,
                ]
        except Exception as e:
            logger.warning(f"Failed to persist live sync state to {self.target_object_name}: {e}")

    def restore_sync_state_from_scene(self, target_obj: Optional[bpy.types.Object] = None) -> bool:
        try:
            obj = target_obj or bpy.data.objects.get(self.target_object_name)
            if obj is None:
                return False

            manifest_data = _MANIFEST_DICT_CACHE.get(obj.name)
            if manifest_data is None:
                manifest_raw = obj.get("mtk:sync_manifest", "")
                if manifest_raw:
                    if isinstance(manifest_raw, dict):
                        manifest_data = manifest_raw
                    elif isinstance(manifest_raw, str) and manifest_raw.strip():
                        try:
                            manifest_data = json.loads(manifest_raw)
                        except Exception:
                            manifest_data = None
                    if manifest_data and isinstance(manifest_data, dict):
                        _MANIFEST_DICT_CACHE[obj.name] = manifest_data

            restored = False
            if manifest_data and isinstance(manifest_data, dict) and manifest_data.get("size_x", 0) > 0:
                restored = self.storage.import_manifest_metadata(manifest_data)

            # Fallback 1: Check mtk_block_bounds or container mozi_sync properties if manifest size was 0
            if not restored or self.storage.size_x == 0:
                bounds = obj.get("mtk_block_bounds")
                if bounds and len(bounds) == 6 and bounds[3] > 0 and bounds[4] > 0 and bounds[5] > 0:
                    self.storage.set_bounds(int(bounds[0]), int(bounds[1]), int(bounds[2]), int(bounds[3]), int(bounds[4]), int(bounds[5]))
                    restored = True
                elif hasattr(obj, "mozi_sync") and obj.mozi_sync.has_selection and obj.mozi_sync.size_x > 0:
                    props = obj.mozi_sync
                    self.storage.set_bounds(int(props.min_x), int(props.min_y), int(props.min_z), int(props.size_x), int(props.size_y), int(props.size_z))
                    restored = True

            # Fallback 2: Always ensure section_crc_map is populated with existing child section mesh CRCs
            from ..meshing import find_root_section_children
            existing_sections = find_root_section_children(obj)
            if existing_sections:
                for (sx, sy, sz), sec_obj in existing_sections.items():
                    if (sx, sy, sz) not in self.storage.section_crc_map:
                        stored_crc = sec_obj.get("mtk:section_crc")
                        if stored_crc is not None:
                            try:
                                self.storage.section_crc_map[(sx, sy, sz)] = int(stored_crc) & 0xFFFFFFFF
                            except Exception:
                                pass
                restored = True

            if restored and self.storage.size_x > 0:
                props = get_active_sync_props(bpy.context, target_obj=obj)
                if props:
                    props.has_selection = True
                    props.min_x, props.min_y, props.min_z = self.storage.min_x, self.storage.min_y, self.storage.min_z
                    props.max_x = self.storage.min_x + self.storage.size_x - 1
                    props.max_y = self.storage.min_y + self.storage.size_y - 1
                    props.max_z = self.storage.min_z + self.storage.size_z - 1
                    props.size_x, props.size_y, props.size_z = self.storage.size_x, self.storage.size_y, self.storage.size_z
                    props.total_blocks = self.storage.size_x * self.storage.size_y * self.storage.size_z
                    props.last_update_info = f"Restored from scene object ({props.total_blocks:,} blocks in bounds)"
                    sync_palette_to_props(props, self.storage)
                logger.info(f"Restored Live Sync metadata for {self.target_object_name} ({self.storage.size_x}x{self.storage.size_y}x{self.storage.size_z}, {len(self.storage.section_crc_map)} sections)")
                return True
        except Exception as e:
            logger.warning(f"Failed to restore live sync state from {self.target_object_name}: {e}")
        return False

    def start_connection(self, context: Optional[bpy.types.Context] = None) -> bool:
        """Start the live sync client thread for this session with structured lifecycle callbacks."""
        if self.client_thread and self.client_thread.is_alive():
            return True

        target_obj = bpy.data.objects.get(self.target_object_name)
        if target_obj and (self.storage.size_x == 0 or not self.storage.section_crc_map):
            self.restore_sync_state_from_scene(target_obj)

        self.is_initial_handshake = True
        self.skip_next_full_snapshot = False

        ProgressBar.begin(title=f"Live Sync ({self.target_object_name})", total=100.0, message="Connecting to Minecraft...", context=context)

        self.client_thread = SyncClientThread(
            url=self.url,
            on_status_change=self.handle_status_change,
            on_selection_info=self.handle_selection_info,
            on_full_snapshot=self.handle_full_snapshot,
            on_delta_update=self.handle_delta_update,
            on_section_manifest=self.handle_section_manifest,
            on_section_snapshot=self.handle_section_snapshot,
            on_handshake_info=self.handle_handshake_info,
            on_stream_begin=self.handle_stream_begin,
            on_stream_end=self.handle_stream_end,
        )
        self.client_thread.start()
        from .event_pump import start_main_thread_pump
        start_main_thread_pump()
        return True

    def handle_status_change(self, status: str) -> None:
        """Handle connection lifecycle status changes."""
        from .event_pump import _run_in_main_thread, start_main_thread_pump, stop_main_thread_pump
        from .registry import get_active_session_manager

        def update():
            cur_obj = bpy.data.objects.get(self.target_object_name)
            cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)
            if cur_props:
                cur_props.connection_status = status
                cur_props.is_connected = (status == "CONNECTED")

            if status == "CONNECTED":
                ProgressBar.update(current=20.0, total=100.0, message="Handshake established...")
                try:
                    from ..material.binding import validate_and_sync_scene_materials
                    validate_and_sync_scene_materials(cur_obj)
                except Exception as e:
                    logger.debug(f"Deferred material sync note: {e}")

                if self.storage.size_x == 0 or not self.storage.section_crc_map:
                    self.restore_sync_state_from_scene(cur_obj)

                if self.client_thread:
                    self.client_thread.send_sync_config(throttle_mode=0, target_fps=60, is_active=True)
                start_main_thread_pump()
            else:
                if status.startswith("ERROR") or "failed" in status.lower() or "refused" in status.lower():
                    ProgressBar.cancel(message=status)
                else:
                    mgr = get_active_session_manager()
                    if not any(s.client_thread and s.client_thread.is_connected for s in (mgr.get_all_sessions() if mgr else [])):
                        stop_main_thread_pump()
                        ProgressBar.end()

            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type in ('PROPERTIES', 'VIEW_3D'):
                        area.tag_redraw()
        _run_in_main_thread(update)

    def handle_handshake_info(self, total_sections: int, non_empty_sections: int, total_volume: int, dimension: str, flags: int) -> None:
        """Handle server handshake metadata packet."""
        from .event_pump import _run_in_main_thread

        def update():
            self.stream_total_sections = max(1, non_empty_sections)
            self.stream_received_sections = 0
            cur_obj = bpy.data.objects.get(self.target_object_name)
            cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)
            if cur_props:
                cur_props.last_update_info = f"Handshake: {dimension} ({non_empty_sections} chunks, {total_volume:,} blocks)"
            ProgressBar.update(current=25.0, total=100.0, message=f"Handshake: {dimension} ({non_empty_sections} chunks)")
        _run_in_main_thread(update)

    def handle_selection_info(self, min_x: int, min_y: int, min_z: int, size_x: int, size_y: int, size_z: int) -> None:
        """Handle selection bounding box updates from server."""
        from .event_pump import _run_in_main_thread

        if self.storage.size_x == 0 or not self.storage.section_crc_map:
            cur_obj_check = bpy.data.objects.get(self.target_object_name)
            if cur_obj_check:
                self.restore_sync_state_from_scene(cur_obj_check)

        bounds_changed = self.storage.set_bounds(min_x, min_y, min_z, size_x, size_y, size_z)
        if bounds_changed:
            while not self.stream_section_queue.empty():
                try:
                    self.stream_section_queue.get_nowait()
                except queue.Empty:
                    break
            self.accumulated_stream_palettes.clear()
            self.stream_received_sections = 0
            self.is_streaming = False
            self.clear_caches()
            self.skip_next_full_snapshot = False
            self.is_initial_handshake = True

        def update():
            cur_obj = bpy.data.objects.get(self.target_object_name)
            if cur_obj:
                from ..meshing import prune_out_of_bounds_section_objects
                prune_out_of_bounds_section_objects(cur_obj, self.storage)
            cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)
            if cur_props:
                cur_props.has_selection = True
                cur_props.min_x, cur_props.min_y, cur_props.min_z = min_x, min_y, min_z
                cur_props.max_x = min_x + size_x - 1
                cur_props.max_y = min_y + size_y - 1
                cur_props.max_z = min_z + size_z - 1
                cur_props.size_x, cur_props.size_y, cur_props.size_z = size_x, size_y, size_z
                cur_props.total_blocks = size_x * size_y * size_z
                if bounds_changed:
                    cur_props.update_counter += 1
                    cur_props.last_update_info = f"Selection: {size_x}x{size_y}x{size_z} ({size_x*size_y*size_z:,} blocks)"
                else:
                    cur_props.last_update_info = f"Attached to selection ({size_x}x{size_y}x{size_z})"
            if bounds_changed:
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == 'PROPERTIES':
                            area.tag_redraw()
        _run_in_main_thread(update)

    def handle_full_snapshot(
        self,
        min_x: int,
        min_y: int,
        min_z: int,
        size_x: int,
        size_y: int,
        size_z: int,
        palette: List[str],
        grid_indices: List[int],
        biome_palette: Optional[List[str]] = None,
        biome_indices: Optional[List[int]] = None,
    ) -> None:
        """Handle full snapshot data arriving on background client thread."""
        from .event_pump import _run_in_main_thread, _finalize_stream_sync

        if self.skip_next_full_snapshot:
            self.skip_next_full_snapshot = False
            return

        if not self.force_next_full_rebuild and self.storage.is_snapshot_identical(
            min_x, min_y, min_z, size_x, size_y, size_z, palette, grid_indices
        ):
            def on_identical():
                cur_obj = bpy.data.objects.get(self.target_object_name)
                if cur_obj:
                    from ..meshing import prune_out_of_bounds_section_objects
                    prune_out_of_bounds_section_objects(cur_obj, self.storage)
                cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)
                if cur_props:
                    cur_props.sync_verified = True
                    cur_props.validation_info = "Verified (100% in sync)"
                ProgressBar.finish(message="Sync Verified (data identical)", auto_dismiss_delay=0.8)
            _run_in_main_thread(on_identical)
            return

        self.storage.set_full_snapshot(
            min_x, min_y, min_z, size_x, size_y, size_z,
            palette, grid_indices, biome_palette=biome_palette, biome_indices=biome_indices
        )

        def step_progressive_stream():
            cur_obj = bpy.data.objects.get(self.target_object_name)
            cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)
            try:
                self.last_seq_id = 0
                if cur_props:
                    cur_props.has_selection = True
                    cur_props.min_x, cur_props.min_y, cur_props.min_z = min_x, min_y, min_z
                    cur_props.max_x = min_x + size_x - 1
                    cur_props.max_y = min_y + size_y - 1
                    cur_props.max_z = min_z + size_z - 1
                    cur_props.size_x, cur_props.size_y, cur_props.size_z = size_x, size_y, size_z
                    cur_props.palette_count = len(palette)
                    cur_props.total_blocks = size_x * size_y * size_z
                    cur_props.update_counter += 1
                    cur_props.sync_verified = True
                    cur_props.validation_info = "Verified (100% in sync)"
                    sync_palette_to_props(cur_props, self.storage)

                self.skip_next_full_snapshot = False
                self.force_next_full_rebuild = False
                self.clear_caches()

                if cur_obj:
                    from ..meshing import prune_out_of_bounds_section_objects, find_root_section_children
                    prune_out_of_bounds_section_objects(cur_obj, self.storage)
                    existing_sections = find_root_section_children(cur_obj)
                else:
                    existing_sections = {}

                all_sections = self.storage.get_all_sections()
                sections_to_rebuild = set()

                for (sx, sy, sz) in all_sections:
                    sec_blocks = self.storage.get_section_blocks(sx, sy, sz)
                    if not sec_blocks or all(s.startswith("minecraft:air") or s == "air" for s in sec_blocks.values()):
                        continue

                    sec_obj = existing_sections.get((sx, sy, sz))
                    if sec_obj is None:
                        sections_to_rebuild.add((sx, sy, sz))
                    else:
                        stored_crc = str(sec_obj.get("mtk:section_crc", ""))
                        expected_crc = str(self.storage.section_crc_map.get((sx, sy, sz), 0))
                        if stored_crc != expected_crc:
                            sections_to_rebuild.add((sx, sy, sz))

                for s in self.storage.get_dirty_sections():
                    if s in all_sections:
                        sections_to_rebuild.add(s)

                boundary_neighbors = set()
                for (sx, sy, sz) in sections_to_rebuild:
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            for dz in (-1, 0, 1):
                                neighbor = (sx + dx, sy + dy, sz + dz)
                                if neighbor in all_sections and neighbor in existing_sections:
                                    boundary_neighbors.add(neighbor)
                sections_to_rebuild.update(boundary_neighbors)

                if not sections_to_rebuild:
                    logger.info(f"Live Sync ({self.target_object_name}): All {len(existing_sections)} section meshes verified up to date. Skipping rebuild.")
                    _finalize_stream_sync(self, cur_props, cur_obj, 0)
                    return None

                self.is_streaming = True
                self.stream_total_sections = len(sections_to_rebuild)
                self.stream_received_sections = 0
                self.stream_last_drain_time = time.time()

                for (sx, sy, sz) in sorted(sections_to_rebuild):
                    self.stream_section_queue.put((sx, sy, sz, palette))

                ProgressBar.begin(title=f"Live Sync ({self.target_object_name})", total=100.0, message=f"Updating {len(sections_to_rebuild)} chunks...")
            except Exception as e:
                logger.error(f"Snapshot progressive streaming error: {e}", exc_info=True)
                self.is_streaming = False
                if cur_props:
                    cur_props.is_locked = False
            return None

        _run_in_main_thread(step_progressive_stream)

    def handle_delta_update(self, min_x: int, min_y: int, min_z: int, changes: List[Tuple[int, int, int, str]], seq_id: int) -> None:
        """Handle incremental block update stream."""
        self.delta_queue.put((min_x, min_y, min_z, changes, seq_id))

    def handle_section_snapshot(
        self,
        sec_x: int, sec_y: int, sec_z: int,
        start_x: int, start_y: int, start_z: int,
        size_x: int, size_y: int, size_z: int,
        palette: List[str],
        grid_indices: List[int],
        biome_palette: Optional[List[str]] = None,
        biome_indices: Optional[List[int]] = None,
    ) -> None:
        """Handle individual chunk section repair/stream snapshot."""
        if self.storage.size_x > 0 and self.storage.size_y > 0 and self.storage.size_z > 0:
            if not (self.storage.contains(start_x, start_y, start_z) or self.storage.contains(start_x + size_x - 1, start_y + size_y - 1, start_z + size_z - 1)):
                logger.debug("Live Sync: Dropped out-of-bounds section snapshot for (%d, %d, %d)", sec_x, sec_y, sec_z)
                return

        self.is_streaming = True
        self.stream_last_drain_time = time.time()
        updated = self.storage.set_section_snapshot(
            sec_x, sec_y, sec_z, start_x, start_y, start_z,
            size_x, size_y, size_z, palette, grid_indices,
            biome_palette=biome_palette, biome_indices=biome_indices
        )
        if updated:
            self.stream_section_queue.put((sec_x, sec_y, sec_z, palette))

    def handle_section_manifest(self, server_seq_id: int, sections: List[Tuple[int, int, int, int]]) -> None:
        """Handle section CRC manifest check for deterministic verification and partial repair."""
        from .event_pump import _run_in_main_thread, _finalize_stream_sync

        def update():
            try:
                cur_obj = bpy.data.objects.get(self.target_object_name)
                cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)
                non_empty_manifest_count = sum(
                    1 for _sx, _sy, _sz, _crc in sections if not self.storage.is_empty_section_crc(_sx, _sy, _sz, _crc)
                )

                if self.pending_full_sync_request or self.force_next_full_rebuild:
                    self.pending_full_sync_request = False
                    self.skip_next_full_snapshot = False
                    self.is_streaming = True
                    self.stream_total_sections = max(1, non_empty_manifest_count)
                    self.stream_received_sections = 0
                    if cur_props:
                        cur_props.validation_info = f"Syncing ({non_empty_manifest_count} chunks)..."
                    if non_empty_manifest_count == 0:
                        _finalize_stream_sync(self, cur_props, cur_obj, 0)
                    else:
                        ProgressBar.begin(title=f"Live Sync ({self.target_object_name})", total=100.0, message=f"Receiving {non_empty_manifest_count} chunks...")
                        ProgressBar.update(current=30.0, total=100.0, message=f"Receiving {non_empty_manifest_count} chunks...")
                        if self.client_thread and self.client_thread.is_connected:
                            logger.info(f"Live Sync ({self.target_object_name}): Requesting full sync on manifest ({non_empty_manifest_count} sections)...")
                            self.client_thread.send_full_sync_request()
                    return

                if self.is_streaming:
                    logger.debug("Live Sync: Ignoring periodic manifest check while streaming is in progress.")
                    return

                from ..meshing import find_root_section_children
                existing_sections = find_root_section_children(cur_obj) if cur_obj else {}
                existing_mesh_coords = set(existing_sections.keys()) if existing_sections else None

                if not self.is_initial_handshake:
                    # Runtime heartbeat validation check:
                    if not self.delta_queue.empty() or self.storage.get_dirty_sections():
                        return

                    mismatched_crc = self.storage.validate_manifest(sections, existing_section_meshes=existing_mesh_coords)
                    if cur_props:
                        cur_props.sync_verified = (len(mismatched_crc) == 0)
                        if len(mismatched_crc) == 0 and cur_props.validation_info != "Verified (100% in sync)":
                            cur_props.validation_info = "Verified (100% in sync)"

                    if len(mismatched_crc) > 0 and not self.is_streaming and self.client_thread and self.client_thread.is_connected:
                        logger.info(f"Live Sync ({self.target_object_name}): Background manifest detected {len(mismatched_crc)} out-of-sync sections. Requesting repair...")
                        self.is_repairing_partial = True
                        self.is_streaming = True
                        self.stream_total_sections = len(mismatched_crc)
                        self.stream_received_sections = 0
                        if cur_props:
                            cur_props.validation_info = f"Repairing {len(mismatched_crc)} section(s)..."
                        self.client_thread.send_repair_request(mismatched_crc)
                    return

                # Initial Handshake / Reconnect Validation
                mismatched_crc = self.storage.validate_manifest(sections, existing_section_meshes=existing_mesh_coords)
                if cur_props:
                    cur_props.sync_verified = (len(mismatched_crc) == 0)

                if len(mismatched_crc) == 0:
                    self.skip_next_full_snapshot = True
                    self.is_repairing_partial = False
                    if cur_props:
                        if cur_props.validation_info != "Verified (100% in sync)":
                            cur_props.validation_info = "Verified (100% in sync)"
                        if not cur_props.palette_list and self.storage.block_map:
                            sync_palette_to_props(cur_props, self.storage)
                    ProgressBar.finish(message="Verified: 100% in sync with scene", auto_dismiss_delay=0.8)
                    self.is_initial_handshake = False

                elif (len(mismatched_crc) >= non_empty_manifest_count) or (not self.storage.section_crc_map and not existing_mesh_coords):
                    # Full sync needed (no existing mesh/CRC or complete mismatch)
                    self.skip_next_full_snapshot = False
                    self.is_repairing_partial = False
                    self.pending_full_sync_request = True
                    self.is_initial_handshake = False
                    self.is_streaming = True
                    self.stream_total_sections = max(1, non_empty_manifest_count)
                    self.stream_received_sections = 0
                    if cur_props:
                        cur_props.validation_info = f"Full sync ({non_empty_manifest_count} chunks)..."
                    ProgressBar.begin(title=f"Live Sync ({self.target_object_name})", total=100.0, message=f"Full sync ({non_empty_manifest_count} chunks)...")
                    ProgressBar.update(current=30.0, total=100.0, message="Requesting full world data...")
                    if self.client_thread and self.client_thread.is_connected:
                        logger.info(f"Live Sync ({self.target_object_name}): Requesting full sync ({non_empty_manifest_count} sections)...")
                        self.client_thread.send_full_sync_request()

                else:
                    # Existing local scene with partial differences on reconnect
                    logger.info(f"Live Sync ({self.target_object_name}): Detected {len(mismatched_crc)} out-of-sync sections on reconnect. Requesting incremental repair...")
                    self.skip_next_full_snapshot = True
                    self.is_repairing_partial = True
                    self.is_initial_handshake = False
                    self.is_streaming = True
                    self.stream_total_sections = len(mismatched_crc)
                    self.stream_received_sections = 0
                    if cur_props:
                        cur_props.validation_info = f"Repairing {len(mismatched_crc)} section(s)..."
                    ProgressBar.begin(title=f"Live Sync ({self.target_object_name})", total=100.0, message=f"Repairing {len(mismatched_crc)} section(s)...")
                    ProgressBar.update(current=30.0, total=100.0, message=f"Syncing {len(mismatched_crc)} modified chunks...")
                    if self.client_thread and self.client_thread.is_connected:
                        self.client_thread.send_repair_request(mismatched_crc)
            except Exception as e:
                logger.error(f"Live Sync manifest error for {self.target_object_name}: {e}", exc_info=True)
                ProgressBar.cancel(message=f"Manifest check error: {e}")
        _run_in_main_thread(update)

    def handle_stream_begin(self, stream_id: int, total_sections: int, flags: int) -> None:
        """Handle progressive stream beginning notice."""
        from .event_pump import _run_in_main_thread

        self.current_stream_id = stream_id
        self.is_streaming = True
        self.server_stream_finished = False
        self.stream_total_sections = max(1, total_sections)
        self.stream_received_sections = 0
        self.stream_last_drain_time = time.time()
        self._stream_state_cache = None
        self._existing_sections_cache = None

        # Purge any lingering section items from previous streams instantly
        while not self.stream_section_queue.empty():
            try:
                self.stream_section_queue.get_nowait()
            except queue.Empty:
                break

        def update():
            cur_obj = bpy.data.objects.get(self.target_object_name)
            if cur_obj:
                from ..meshing import prune_out_of_bounds_section_objects
                prune_out_of_bounds_section_objects(cur_obj, self.storage)
            cur_props = get_active_sync_props(bpy.context, target_obj=cur_obj)
            if cur_props:
                cur_props.validation_info = f"Streaming {total_sections} chunks..."
            ProgressBar.begin(title=f"Live Sync ({self.target_object_name})", total=100.0, message=f"Streaming {total_sections} chunks...")
            ProgressBar.update(current=30.0, total=100.0, message=f"Streaming chunk (0/{total_sections})")
        _run_in_main_thread(update)

    def handle_stream_end(self, stream_id: int, sent_sections: int, status: int) -> None:
        """Handle progressive stream end notice."""
        from ..constants import StreamStatus
        if stream_id != self.current_stream_id:
            logger.debug("Live Sync: Ignoring stream_end for stale stream %d (current: %d)", stream_id, self.current_stream_id)
            return
        if status == StreamStatus.CANCELLED:
            logger.info("Live Sync (%s): Server confirmed stream %d was cancelled.", self.target_object_name, stream_id)
            self.is_streaming = False
            self.server_stream_finished = False
            return
        self.server_stream_finished = True
        self.stream_last_drain_time = time.time()

    def stop(self) -> None:
        if self.client_thread:
            try:
                self.client_thread.stop()
            except Exception:
                pass
            self.client_thread = None
        self.is_streaming = False
        self.is_repairing_partial = False
        self.pending_full_sync_request = False
        self.rebuild_timer_registered = False
        self.pending_full_rebuild = False
        while not self.delta_queue.empty():
            try:
                self.delta_queue.get_nowait()
            except queue.Empty:
                break
        while not self.stream_section_queue.empty():
            try:
                self.stream_section_queue.get_nowait()
            except queue.Empty:
                break
        self.accumulated_stream_palettes.clear()

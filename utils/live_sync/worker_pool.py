"""
Multi-Process Section Mesh Generation Worker Pool for MoziToolKit Live Sync.
Distributes decoupled pure-Python RawSectionGeometryBuffer calculation across all available CPU cores.
"""

from __future__ import annotations

import os
import sys
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, Future
from typing import Any, Dict, List, Optional, Tuple, Set

from .geometry_builder import RawSectionGeometryBuffer, generate_section_geometry_buffer
from .mesh_cache import CachedStateMeta, get_cached_state_meta
from .material_manager import LiveSyncMaterialManager
from .storage import VoxelStorage
from ..mc_baker import get_shared_state_baker

logger = logging.getLogger("MoziToolKit.WorkerPool")

# Process-local singletons inside each worker subprocess
_WORKER_STORAGE: Optional[VoxelStorage] = None
_WORKER_BAKER: Optional[Any] = None
_WORKER_MAT_MANAGERS: dict[int, LiveSyncMaterialManager] = {}
_WORKER_STATE_CACHES: dict[int, dict[str, CachedStateMeta]] = {}


def compute_section_geometry_task(
    sec_coords: tuple[int, int, int],
    sec_blocks: dict[tuple[int, int, int], str],
    halo_blocks: dict[tuple[int, int, int], str],
    biome_map: dict[tuple[int, int, int], str],
    bounds: tuple[int, int, int, int, int, int],
    atlas_params: Optional[dict[str, Any]],
    chunk_to_slot: Optional[dict[int, int]] = None,
    origin_centered: bool = True,
    weld_vertices: bool = True,
) -> tuple[tuple[int, int, int], RawSectionGeometryBuffer]:
    """
    Top-level standalone task function executed inside worker processes.
    Generates a RawSectionGeometryBuffer completely decoupled from Blender bpy/bmesh.
    """
    global _WORKER_STORAGE, _WORKER_BAKER, _WORKER_MAT_MANAGERS, _WORKER_STATE_CACHES

    if _WORKER_STORAGE is None:
        _WORKER_STORAGE = VoxelStorage()
    if _WORKER_BAKER is None:
        from ..mc_baker import StateBaker
        _WORKER_BAKER = StateBaker()

    min_x, min_y, min_z, size_x, size_y, size_z = bounds
    half_x = size_x / 2.0 - 0.5
    half_z = size_z / 2.0 - 0.5

    # Reconstruct worker local storage with section + halo blocks
    storage = _WORKER_STORAGE
    storage.block_map.clear()
    storage.biome_map.clear()
    storage._smoothed_biome_cache.clear()

    storage.min_x = min_x
    storage.min_y = min_y
    storage.min_z = min_z
    storage.size_x = size_x
    storage.size_y = size_y
    storage.size_z = size_z

    combined_map = dict(halo_blocks)
    combined_map.update(sec_blocks)
    storage.block_map = combined_map
    storage.biome_map = dict(biome_map)

    # Worker-cached Material Manager
    param_key = (atlas_params.get("pack_hash") if isinstance(atlas_params, dict) else None) or "default"
    mat_mgr = _WORKER_MAT_MANAGERS.get(param_key)
    if mat_mgr is None:
        mat_mgr = LiveSyncMaterialManager(world_obj=None, atlas_params=atlas_params)
        if chunk_to_slot:
            mat_mgr.chunk_to_slot.update(chunk_to_slot)
        _WORKER_MAT_MANAGERS[param_key] = mat_mgr
    elif chunk_to_slot:
        mat_mgr.chunk_to_slot.update(chunk_to_slot)

    # Worker-cached State Meta Cache
    state_cache = _WORKER_STATE_CACHES.setdefault(param_key, {})
    unique_states = set(sec_blocks.values())
    for s in unique_states:
        if s not in state_cache:
            state_cache[s] = get_cached_state_meta(s, mat_mgr, _WORKER_BAKER)

    # Pure computation geometry generation
    buffer = generate_section_geometry_buffer(
        voxel_items=list(sec_blocks.items()),
        block_map=storage.block_map,
        state_cache=state_cache,
        origin_centered=origin_centered,
        min_x=min_x, min_y=min_y, min_z=min_z,
        half_x=half_x, half_z=half_z,
        mat_manager=mat_mgr,
        baker=_WORKER_BAKER,
        voxel_storage=storage,
        weld_vertices=weld_vertices,
    )

    return sec_coords, buffer


def extract_section_payload(
    storage: VoxelStorage,
    sx: int, sy: int, sz: int,
) -> tuple[
    dict[tuple[int, int, int], str],
    dict[tuple[int, int, int], str],
    dict[tuple[int, int, int], str],
    tuple[int, int, int, int, int, int],
]:
    """
    Extract isolated section blocks, 1-block neighbor halo, and local biomes from storage
    to form a compact, lightweight IPC payload.
    """
    sec_blocks = storage.get_section_blocks(sx, sy, sz)

    min_sec_x = sx << 4
    max_sec_x = min_sec_x + 15
    min_sec_y = sy << 4
    max_sec_y = min_sec_y + 15
    min_sec_z = sz << 4
    max_sec_z = min_sec_z + 15

    # Extract 1-block halo around section bounds for 6-face culling and fluid heights
    halo_blocks: dict[tuple[int, int, int], str] = {}
    for (x, y, z), state in storage.block_map.items():
        if (
            (min_sec_x - 1 <= x <= max_sec_x + 1)
            and (min_sec_y - 2 <= y <= max_sec_y + 2)
            and (min_sec_z - 1 <= z <= max_sec_z + 1)
        ):
            if not (min_sec_x <= x <= max_sec_x and min_sec_y <= y <= max_sec_y and min_sec_z <= z <= max_sec_z):
                halo_blocks[(x, y, z)] = state

    # Extract local column biome map
    biome_map: dict[tuple[int, int, int], str] = {}
    for (x, y, z), b in storage.biome_map.items():
        if (min_sec_x - 3 <= x <= max_sec_x + 3) and (min_sec_z - 3 <= z <= max_sec_z + 3):
            biome_map[(x, y, z)] = b

    bounds = (storage.min_x, storage.min_y, storage.min_z, storage.size_x, storage.size_y, storage.size_z)
    return sec_blocks, halo_blocks, biome_map, bounds


class SectionMesherProcessPool:
    """
    Singleton ProcessPoolExecutor manager for multi-core section geometry building.
    """
    def __init__(self, max_workers: Optional[int] = None) -> None:
        self.max_workers = max_workers or min(32, max(1, os.cpu_count() or 4))
        self._pool: Optional[ProcessPoolExecutor] = None
        # On POSIX/Linux, fork is instant and avoids __main__ reload issues in Blender
        start_method = "fork" if hasattr(os, "fork") else "spawn"
        self._ctx = multiprocessing.get_context(start_method)

    def get_pool(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(
                max_workers=self.max_workers,
                mp_context=self._ctx,
            )
            logger.info("Initialized SectionMesherProcessPool with %d workers (start_method=%s)", self.max_workers, self._ctx.get_start_method())
        return self._pool

    def submit_section(
        self,
        storage: VoxelStorage,
        sx: int, sy: int, sz: int,
        atlas_params: Optional[dict[str, Any]],
        chunk_to_slot: Optional[dict[int, int]] = None,
        origin_centered: bool = True,
        weld_vertices: bool = True,
    ) -> Future[tuple[tuple[int, int, int], RawSectionGeometryBuffer]]:
        sec_blocks, halo_blocks, biome_map, bounds = extract_section_payload(storage, sx, sy, sz)
        pool = self.get_pool()

        # Sanitize atlas_params to ensure 100% pickle safety across processes
        clean_atlas_params = None
        if isinstance(atlas_params, dict):
            clean_atlas_params = {
                k: v for k, v in atlas_params.items()
                if k != "material" and not str(type(v)).startswith("<class 'bpy")
            }

        return pool.submit(
            compute_section_geometry_task,
            sec_coords=(sx, sy, sz),
            sec_blocks=sec_blocks,
            halo_blocks=halo_blocks,
            biome_map=biome_map,
            bounds=bounds,
            atlas_params=clean_atlas_params,
            chunk_to_slot=chunk_to_slot,
            origin_centered=origin_centered,
            weld_vertices=weld_vertices,
        )

    def shutdown(self, wait: bool = False) -> None:
        if self._pool is not None:
            try:
                self._pool.shutdown(wait=wait, cancel_futures=True)
            except Exception as e:
                logger.debug("Process pool shutdown note: %s", e)
            self._pool = None


_GLOBAL_SECTION_POOL: Optional[SectionMesherProcessPool] = None


def get_shared_section_pool(max_workers: Optional[int] = None) -> SectionMesherProcessPool:
    """Retrieve or instantiate global SectionMesherProcessPool singleton."""
    global _GLOBAL_SECTION_POOL
    if _GLOBAL_SECTION_POOL is None:
        _GLOBAL_SECTION_POOL = SectionMesherProcessPool(max_workers=max_workers)
    return _GLOBAL_SECTION_POOL


def shutdown_section_pool() -> None:
    """Clean up and terminate global SectionMesherProcessPool workers."""
    global _GLOBAL_SECTION_POOL
    if _GLOBAL_SECTION_POOL is not None:
        _GLOBAL_SECTION_POOL.shutdown(wait=False)
        _GLOBAL_SECTION_POOL = None

"""
Scene state persistence and manifest metadata restoration for Live Sync.
"""

from __future__ import annotations

import json
import logging
from typing import Optional
import bpy

from ..storage.voxel_storage import VoxelStorage, voxel_storage
from .props import get_active_sync_props, get_target_world_object, sync_palette_to_props

logger = logging.getLogger("MoziToolKit.LiveSync.Persistence")

_MANIFEST_DICT_CACHE: dict[str, dict] = {}


def clear_manifest_dict_cache(obj_name: Optional[str] = None) -> None:
    """Clear memory cached manifest dictionary for live sync objects."""
    if obj_name is not None:
        _MANIFEST_DICT_CACHE.pop(obj_name, None)
    else:
        _MANIFEST_DICT_CACHE.clear()


def persist_sync_state_to_scene(context: Optional[bpy.types.Context] = None, target_obj: Optional[bpy.types.Object] = None) -> None:
    """Persist bounds, generation, and section CRC manifest onto target world object."""
    try:
        world_obj = target_obj or get_target_world_object(context)
        if world_obj is not None:
            from .registry import get_active_session_manager
            mgr = get_active_session_manager()
            sess = mgr.get_session(world_obj.name) if mgr else None
            storage = sess.storage if sess else voxel_storage
            manifest_dict = storage.export_manifest_metadata()
            _MANIFEST_DICT_CACHE[world_obj.name] = manifest_dict
            world_obj["mtk:sync_manifest"] = json.dumps(manifest_dict)
            world_obj["mtk_block_bounds"] = [
                storage.min_x, storage.min_y, storage.min_z,
                storage.size_x, storage.size_y, storage.size_z,
            ]
    except Exception as e:
        logger.warning(f"Failed to persist live sync state to scene object: {e}")


def restore_sync_state_from_scene(context: Optional[bpy.types.Context] = None, target_obj: Optional[bpy.types.Object] = None) -> bool:
    """Attempt to restore live sync voxel metadata from existing scene object."""
    try:
        world_obj = target_obj or get_target_world_object(context)
        if world_obj is None:
            return False

        from .registry import get_active_session_manager
        mgr = get_active_session_manager()
        sess = mgr.get_session(world_obj.name) if mgr else None
        storage = sess.storage if sess else voxel_storage

        manifest_data = _MANIFEST_DICT_CACHE.get(world_obj.name)
        if manifest_data is None:
            manifest_raw = world_obj.get("mtk:sync_manifest", "")
            if manifest_raw:
                if isinstance(manifest_raw, dict):
                    manifest_data = manifest_raw
                elif isinstance(manifest_raw, str) and manifest_raw.strip():
                    try:
                        manifest_data = json.loads(manifest_raw)
                    except Exception:
                        manifest_data = None
                if manifest_data and isinstance(manifest_data, dict):
                    _MANIFEST_DICT_CACHE[world_obj.name] = manifest_data

        if manifest_data and storage.import_manifest_metadata(manifest_data):
            props = get_active_sync_props(context, target_obj=world_obj)
            if props:
                props.has_selection = True
                props.min_x, props.min_y, props.min_z = storage.min_x, storage.min_y, storage.min_z
                props.max_x = storage.min_x + storage.size_x - 1
                props.max_y = storage.min_y + storage.size_y - 1
                props.max_z = storage.min_z + storage.size_z - 1
                props.size_x, props.size_y, props.size_z = storage.size_x, storage.size_y, storage.size_z
                props.total_blocks = storage.size_x * storage.size_y * storage.size_z
                props.last_update_info = f"Restored from scene object ({props.total_blocks:,} blocks in bounds)"
                sync_palette_to_props(props, storage)
            logger.info(f"Restored Live Sync metadata for {world_obj.name} ({storage.size_x}x{storage.size_y}x{storage.size_z})")
            return True
    except Exception as e:
        logger.warning(f"Failed to restore live sync state from scene object: {e}")
    return False

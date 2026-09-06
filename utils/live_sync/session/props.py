"""
Property synchronization and scene context resolution for Live Sync.
"""

from __future__ import annotations

import time
from typing import Any, List, Optional, Tuple
import bpy

from ..constants import DEFAULT_WORLD_OBJECT_NAME
from ..meshing import (
    resolve_world_root_object,
    is_yefira_root_object,
    is_yefira_object,
)
from ..storage.voxel_storage import VoxelStorage

REBUILD_DEBOUNCE_SECONDS: float = 0.05
_PUMP_INTERVAL_ACTIVE: float = 0.015  # 15ms (~66 Hz when processing active deltas/chunks)
_PUMP_INTERVAL_IDLE: float = 0.035    # 35ms (~28 Hz idle throttle to save CPU)
_SETTLE_TIMEOUT_SECONDS: float = 8.0
MAX_DELTA_HISTORY: int = 100


def get_active_sync_props(context: Optional[bpy.types.Context] = None, target_obj: Optional[bpy.types.Object] = None):
    """Retrieve mozi_sync properties safely, preferring the container object's properties."""
    ctx = context or (bpy.context if hasattr(bpy, "context") else None)

    # 1. If target_obj is explicitly provided
    if target_obj is not None:
        root = resolve_world_root_object(target_obj) or target_obj
        if hasattr(root, "mozi_sync"):
            return root.mozi_sync

    # 2. Check context active / selected object
    active_obj = getattr(ctx, "active_object", None) if ctx else None
    if active_obj is not None:
        root = resolve_world_root_object(active_obj) or active_obj
        if hasattr(root, "mozi_sync") and (is_yefira_object(active_obj) or root.get("mtk:is_yefira_world")):
            return root.mozi_sync

    # 3. Fallback to Scene mozi_sync
    if ctx and hasattr(ctx, "scene") and hasattr(ctx.scene, "mozi_sync"):
        return ctx.scene.mozi_sync
    if hasattr(bpy, "context") and hasattr(bpy.context, "scene") and hasattr(bpy.context.scene, "mozi_sync"):
        return bpy.context.scene.mozi_sync
    return None


def get_target_world_object(context: Optional[bpy.types.Context] = None, obj_name: Optional[str] = None) -> Optional[bpy.types.Object]:
    """Retrieve the target Yefira World container object for a session or active context."""
    if obj_name and obj_name in bpy.data.objects:
        obj = bpy.data.objects[obj_name]
        return resolve_world_root_object(obj) or obj

    ctx = context or (bpy.context if hasattr(bpy, "context") else None)
    active_obj = getattr(ctx, "active_object", None) if ctx else None
    if active_obj:
        root = resolve_world_root_object(active_obj)
        if root:
            return root

    if ctx and hasattr(ctx, "selected_objects"):
        for sel in ctx.selected_objects:
            root = resolve_world_root_object(sel)
            if root:
                return root

    world_obj = bpy.data.objects.get(DEFAULT_WORLD_OBJECT_NAME)
    if world_obj is not None:
        return resolve_world_root_object(world_obj) or world_obj

    for obj in bpy.data.objects:
        if is_yefira_root_object(obj):
            return obj
    return None


def get_current_world_object(context: Optional[bpy.types.Context] = None) -> Optional[bpy.types.Object]:
    """Retrieve the currently active or existing Yefira World container object."""
    return get_target_world_object(context)


def sync_palette_to_props(props: Any, storage: VoxelStorage) -> None:
    """Sync unique block states from VoxelStorage to props.palette_list and update palette_count."""
    if not props or not storage:
        return
    unique_states = sorted(storage.get_unique_states())
    props.palette_count = len(unique_states)
    props.palette_list.clear()
    for state in unique_states:
        item = props.palette_list.add()
        item.state_str = state


def append_delta_history(props: Any, applied_changes: List[Tuple[int, int, int, str, str]]) -> None:
    """Append block change delta records to props.delta_history and scroll to newest item."""
    if not props or not applied_changes:
        return

    cur_time = time.strftime("%H:%M:%S")
    if len(applied_changes) <= 12:
        for x, y, z, old_state, new_state in applied_changes:
            item = props.delta_history.add()
            item.timestamp = cur_time
            item.pos_str = f"({x}, {y}, {z})"
            if new_state.endswith(":air") or new_state == "air" or new_state.startswith("minecraft:air"):
                old_name = old_state.split("[")[0].split(":")[-1] if old_state else "block"
                item.block_state = f"{old_name} (broken)"
            elif not old_state or old_state.endswith(":air") or old_state == "air" or old_state.startswith("minecraft:air"):
                item.block_state = new_state
            else:
                old_name = old_state.split("[")[0].split(":")[-1]
                new_name = new_state.split("[")[0].split(":")[-1]
                item.block_state = f"{old_name} -> {new_name}"
    else:
        for x, y, z, old_state, new_state in applied_changes[:10]:
            item = props.delta_history.add()
            item.timestamp = cur_time
            item.pos_str = f"({x}, {y}, {z})"
            if new_state.endswith(":air") or new_state == "air" or new_state.startswith("minecraft:air"):
                old_name = old_state.split("[")[0].split(":")[-1] if old_state else "block"
                item.block_state = f"{old_name} (broken)"
            else:
                item.block_state = new_state
        item = props.delta_history.add()
        item.timestamp = cur_time
        item.pos_str = f"+{len(applied_changes) - 10} more"
        item.block_state = f"Batch ({len(applied_changes)} total edits)"

    while len(props.delta_history) > MAX_DELTA_HISTORY:
        props.delta_history.remove(0)

    props.delta_active_index = max(0, len(props.delta_history) - 1)

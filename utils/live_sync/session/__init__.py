"""Live Sync Session Subsystem."""

from .props import (
    MAX_DELTA_HISTORY,
    REBUILD_DEBOUNCE_SECONDS,
    get_active_sync_props,
    get_target_world_object,
    get_current_world_object,
    sync_palette_to_props,
    append_delta_history,
)

from .material_cache import (
    get_cached_atlas_params,
    clear_sync_caches,
)

from .persistence import (
    persist_sync_state_to_scene,
    restore_sync_state_from_scene,
    clear_manifest_dict_cache,
)

from .session import SyncSession

from .registry import (
    SyncSessionManager,
    _session_manager,
    get_active_session_manager,
    reset_active_session_manager,
)

from .event_pump import (
    trigger_mesh_sync,
    schedule_mesh_sync,
    _finalize_stream_sync,
    _pump_main_thread_events,
    start_main_thread_pump,
    stop_main_thread_pump,
    cleanup_sync_state,
    _delta_queue,
    _stream_section_queue,
    _accumulated_stream_palettes,
)

from .session_manager import *

__all__ = (
    "MAX_DELTA_HISTORY",
    "REBUILD_DEBOUNCE_SECONDS",
    "SyncSession",
    "SyncSessionManager",
    "_MANIFEST_DICT_CACHE",
    "_accumulated_stream_palettes",
    "_delta_queue",
    "_extract_atlas_params",
    "_finalize_stream_sync",
    "_find_bound_atlas_material",
    "_pump_main_thread_events",
    "_pump_timer_registered",
    "_run_in_main_thread",
    "_session_manager",
    "_stream_section_queue",
    "append_delta_history",
    "cleanup_sync_state",
    "clear_manifest_dict_cache",
    "clear_sync_caches",
    "get_active_session_manager",
    "get_active_sync_props",
    "get_cached_atlas_params",
    "get_current_world_object",
    "get_target_world_object",
    "persist_sync_state_to_scene",
    "reset_active_session_manager",
    "restore_sync_state_from_scene",
    "schedule_mesh_sync",
    "start_main_thread_pump",
    "stop_main_thread_pump",
    "sync_palette_to_props",
    "trigger_mesh_sync",
)

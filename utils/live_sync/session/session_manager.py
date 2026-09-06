"""
Session management and main thread runtime engine for Minecraft Live Sync.
Decomposed facade preserving full backward compatibility.
"""

from __future__ import annotations
import sys

# Re-export core constants and types
from .props import (
    MAX_DELTA_HISTORY,
    REBUILD_DEBOUNCE_SECONDS,
    _PUMP_INTERVAL_ACTIVE,
    _PUMP_INTERVAL_IDLE,
    _SETTLE_TIMEOUT_SECONDS,
    get_active_sync_props,
    get_target_world_object,
    get_current_world_object,
    sync_palette_to_props,
    append_delta_history,
)

from .material_cache import (
    extract_atlas_params as _extract_atlas_params,
    find_bound_atlas_material as _find_bound_atlas_material,
    get_cached_atlas_params,
    clear_sync_caches,
)

from .persistence import (
    _MANIFEST_DICT_CACHE,
    clear_manifest_dict_cache,
    persist_sync_state_to_scene,
    restore_sync_state_from_scene,
)

from .session import SyncSession

from . import registry
from .registry import (
    SyncSessionManager,
    get_active_session_manager,
    reset_active_session_manager,
)

from . import event_pump
from .event_pump import (
    _run_in_main_thread,
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

# Legacy aliases and module-level backward compatibility attributes
_client_thread = None
_last_seq_id: int = 0
_stream_total_sections: int = 0
_stream_received_sections: int = 0
_is_streaming: bool = False
_is_initial_handshake: bool = False
_rebuild_timer_registered: bool = False
_pending_full_rebuild: bool = False
_cached_atlas_params = None
_cached_mat_signature = None
_is_repairing_partial: bool = False

# Transparent module property redirection for legacy module-level variables (e.g. _pump_timer_registered, _session_manager)
class _SessionManagerModule(sys.modules[__name__].__class__):
    @property
    def _pump_timer_registered(self):
        return event_pump._pump_timer_registered

    @_pump_timer_registered.setter
    def _pump_timer_registered(self, val):
        event_pump._pump_timer_registered = val

    @property
    def _session_manager(self):
        return get_active_session_manager()

    @_session_manager.setter
    def _session_manager(self, val):
        registry._session_manager = val

sys.modules[__name__].__class__ = _SessionManagerModule

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

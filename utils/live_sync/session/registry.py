"""
Session registry and multi-container session manager for Live Sync.
"""

from __future__ import annotations

from typing import Dict, List, Optional
import bpy

from .persistence import clear_manifest_dict_cache
from .session import SyncSession


class SyncSessionManager:
    """Manages all active sync sessions keyed by container object name."""

    def __init__(self):
        self._sessions: Dict[str, SyncSession] = {}

    def get_session(self, obj_name: str) -> Optional[SyncSession]:
        return self._sessions.get(obj_name)

    def get_or_create_session(self, obj_name: str, url: str = "ws://localhost:8765") -> SyncSession:
        if obj_name not in self._sessions:
            session = SyncSession(target_object_name=obj_name, url=url)
            self._sessions[obj_name] = session
            # Synchronously restore persistent state from the target scene object if present
            target_obj = bpy.data.objects.get(obj_name)
            if target_obj:
                session.restore_sync_state_from_scene(target_obj)
        else:
            session = self._sessions[obj_name]
            if url:
                session.url = url
        return session

    def remove_session(self, obj_name: str) -> None:
        if obj_name in self._sessions:
            session = self._sessions.pop(obj_name)
            session.stop()
        clear_manifest_dict_cache(obj_name)

    def get_all_sessions(self) -> List[SyncSession]:
        return list(self._sessions.values())

    def clear_all(self) -> None:
        for session in list(self._sessions.values()):
            session.stop()
        self._sessions.clear()
        clear_manifest_dict_cache()


_session_manager = SyncSessionManager()


def get_active_session_manager() -> SyncSessionManager:
    if hasattr(bpy.types, "_mozi_session_manager"):
        return bpy.types._mozi_session_manager
    bpy.types._mozi_session_manager = _session_manager
    return _session_manager


def reset_active_session_manager() -> SyncSessionManager:
    global _session_manager
    if _session_manager is not None:
        _session_manager.clear_all()
    _session_manager = SyncSessionManager()
    bpy.types._mozi_session_manager = _session_manager
    return _session_manager

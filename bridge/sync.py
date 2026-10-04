"""
MoziToolKit Live Sync Bridge Module.

Encapsulates all interaction with native libmtk LiveSyncSession and
VoxelStorage engines. Provides clean data-in / data-out APIs for Blender
operators and panels.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("MoziToolKit.Bridge.Sync")

from .engine import get_libmtk, has_libmtk, require_libmtk


def __getattr__(name: str) -> Any:
    if name == "HAS_LIBMTK":
        return is_sync_available()
    if name == "mtk_py":
        return get_libmtk()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


try:
    from .assets import (
        get_cache_dir,
        load_baked_model_database,
        load_baked_atlas_from_cache,
        load_biome_resolver_from_cache,
    )
except (ImportError, ValueError):
    from bridge.assets import (
        get_cache_dir,
        load_baked_model_database,
        load_baked_atlas_from_cache,
        load_biome_resolver_from_cache,
    )


def is_sync_available() -> bool:
    """Checks whether the native libmtk Live Sync backend is loaded and ready."""
    mtk = get_libmtk()
    return bool(mtk and hasattr(mtk, "LiveSyncSession"))


class SyncBridgeSession:
    """
    Session wrapper managing the native background LiveSyncSession client thread
    and event queue.
    """

    def __init__(self):
        self._session: Optional[Any] = None
        self._is_active: bool = False
        self._current_url: str = ""
        self._model_db: Optional[Any] = None
        self._atlas: Optional[Any] = None
        self._unified_mesh: bool = True
        self._last_error: str = ""

    @property
    def is_active(self) -> bool:
        """Whether a background synchronization session is running."""
        return self._is_active and self._session is not None

    @property
    def current_url(self) -> str:
        """Currently connected or target WebSocket URL."""
        return self._current_url

    @property
    def last_error(self) -> str:
        """Last error message recorded during session operations."""
        return self._last_error

    def start(
        self,
        url: str = "ws://127.0.0.1:8765",
        auto_reconnect: bool = True,
        max_reconnect_attempts: int = 5,
        model_db: Optional[Any] = None,
        atlas: Optional[Any] = None,
        unified_mesh: bool = True,
        enable_ao: bool = True,
        mesh_fluids: bool = True,
        biome_resolver: Optional[Any] = None,
        custom_aliases: Optional[Any] = None,
        num_threads: Optional[int] = None,
    ) -> bool:
        """
        Starts the background LiveSync client thread connecting to `url`.
        """
        mtk = get_libmtk()
        if mtk is None or not hasattr(mtk, "LiveSyncSession"):
            self._last_error = "Native libmtk_py core is not available."
            logger.error("Cannot start Live Sync: native libmtk_py core is not available.")
            return False

        self.stop()
        self._last_error = ""

        self._model_db = model_db
        self._atlas = atlas
        self._unified_mesh = unified_mesh
        self._current_url = url

        if num_threads is None:
            try:
                from ..utils.system import get_prefs
                prefs = get_prefs()
                num_threads = getattr(prefs, "thread_count", 0) or None
            except Exception:
                num_threads = None

        try:
            # Construct MesherConfig with target Z-up coordinates for Blender, origin centered, and welded vertices
            try:
                config = mtk.MesherConfig(
                    enable_ao=enable_ao,
                    mesh_fluids=mesh_fluids,
                    z_up_coordinates=True,
                    origin_centered=True,
                    weld_vertices=True,
                    num_threads=num_threads,
                    atlas=atlas,
                    biome_resolver=biome_resolver,
                    custom_aliases=custom_aliases,
                )
            except (TypeError, AttributeError):
                # Backwards-compatible fallback for older wheel binaries
                try:
                    config = mtk.MesherConfig(
                        enable_ao=enable_ao,
                        mesh_fluids=mesh_fluids,
                        z_up_coordinates=True,
                        origin_centered=True,
                        weld_vertices=True,
                        atlas=atlas,
                        biome_resolver=biome_resolver,
                        custom_aliases=custom_aliases,
                    )
                except (TypeError, AttributeError):
                    config = mtk.MesherConfig(
                        enable_ao=enable_ao,
                        mesh_fluids=mesh_fluids,
                        z_up_coordinates=True,
                        atlas=atlas,
                    )
                if biome_resolver is not None and hasattr(config, "set_biome_resolver"):
                    try:
                        config.set_biome_resolver(biome_resolver)
                    except Exception:
                        pass
                if custom_aliases is not None and hasattr(config, "set_custom_aliases"):
                    try:
                        config.set_custom_aliases(custom_aliases)
                    except Exception:
                        pass

            # Face culler instance
            culler = mtk.FaceCuller() if hasattr(mtk, "FaceCuller") else None

            # Instantiate native LiveSyncSession
            self._session = mtk.LiveSyncSession(
                config=config,
                culler=culler,
                model_db=model_db,
                unified_mesh=unified_mesh,
            )

            self._session.start(url, auto_reconnect, max_reconnect_attempts)
            self._is_active = True
            logger.info(f"LiveSyncSession started connecting to {url} (unified_mesh={unified_mesh})")
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"Failed to start LiveSyncSession: {e}")
            self._session = None
            self._is_active = False
            return False

    def stop(self) -> None:
        """Cleanly stops background sync client and frees session resources."""
        if self._session is not None:
            try:
                self._session.stop()
            except Exception as e:
                logger.debug(f"Error during LiveSyncSession shutdown: {e}")
        self._session = None
        self._is_active = False
        logger.info("LiveSyncSession stopped.")

    def poll_events(self) -> List[Dict[str, Any]]:
        """
        Polls all pending events from the background Rust engine (non-blocking).
        Returns a list of event dictionaries.
        """
        if self._session is None or not self._is_active:
            return []
        try:
            return self._session.poll_events()
        except Exception as e:
            logger.error(f"Error polling Live Sync events: {e}")
            return []

    def get_world_mesh(self) -> Optional[Any]:
        """
        Queries the current full merged world geometry directly as a PyMeshData buffer.
        """
        if self._session is None:
            return None
        try:
            return self._session.get_world_mesh()
        except Exception as e:
            logger.error(f"Error querying get_world_mesh: {e}")
            return None

    def get_storage(self) -> Optional[Any]:
        """
        Returns a copy of the underlying PyVoxelStorage from the active live sync session.
        """
        if self._session is None:
            return None
        try:
            return self._session.get_storage()
        except Exception as e:
            logger.error(f"Error querying get_storage: {e}")
            return None

    def send_full_sync_request(self) -> bool:
        """Requests server to resend the entire active selection snapshot (0x80)."""
        if self._session is None:
            return False
        try:
            self._session.send_full_sync_request()
            return True
        except Exception as e:
            logger.error(f"Failed to send Full Sync Request: {e}")
            return False

    def send_repair_request(self, sections: List[Tuple[int, int, int]]) -> bool:
        """Requests server to resend specific chunk sections (0x81)."""
        if self._session is None:
            return False
        try:
            self._session.send_repair_request(sections)
            return True
        except Exception as e:
            logger.error(f"Failed to send Repair Request: {e}")
            return False

    def send_sync_config(self, throttle_mode: int = 0, target_fps: int = 60, is_active: bool = True) -> bool:
        """Sends client synchronization configuration packet (0x82)."""
        if self._session is None:
            return False
        try:
            self._session.send_sync_config(throttle_mode, target_fps, is_active)
            return True
        except Exception as e:
            logger.error(f"Failed to send Sync Config: {e}")
            return False


# Global singleton bridge instance
_global_sync_session = SyncBridgeSession()


def get_sync_bridge_session() -> SyncBridgeSession:
    """Returns the shared global SyncBridgeSession singleton."""
    return _global_sync_session


def load_model_database_from_cache(prefs=None) -> Optional[Any]:
    """
    Attempts to deserialize prebaked BakedModelDatabase from compact binary bytes (bincode).
    Returns None if cache is missing or corrupt.
    """
    if not is_sync_available():
        return None
    return load_baked_model_database(prefs)


def load_atlas_from_cache(prefs=None) -> Optional[Any]:
    """
    Loads precompiled BakedAtlas from cache into memory.
    Returns None if cache is missing or libmtk is unavailable.
    """
    if not is_sync_available():
        return None
    return load_baked_atlas_from_cache(prefs)


def load_biome_resolver_from_cache(prefs=None) -> Optional[Any]:
    """
    Loads precompiled BiomeResolver from cache into memory.
    Returns None if cache is missing or libmtk is unavailable.
    """
    if not is_sync_available():
        return None
    from .assets import load_biome_resolver_from_cache as _load
    return _load(prefs)


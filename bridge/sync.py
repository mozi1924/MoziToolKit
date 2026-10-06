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
        check_cache_dirty,
        get_cache_fingerprint,
        get_cache_timestamp,
        reload_atlas_images,
    )
except (ImportError, ValueError):
    from bridge.assets import (
        get_cache_dir,
        load_baked_model_database,
        load_baked_atlas_from_cache,
        load_biome_resolver_from_cache,
        check_cache_dirty,
        get_cache_fingerprint,
        get_cache_timestamp,
        reload_atlas_images,
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
        self._is_connected: bool = False
        self._connection_status: str = "DISCONNECTED"
        self._current_url: str = ""
        self._model_db: Optional[Any] = None
        self._atlas: Optional[Any] = None
        self._biome_resolver: Optional[Any] = None
        self._custom_aliases: Optional[Any] = None
        self._config_params: Dict[str, Any] = {}
        self._cached_manifest_fingerprint: Optional[str] = None
        self._cached_manifest_timestamp: float = 0.0
        self._unified_mesh: bool = True
        self._last_error: str = ""

    @property
    def is_active(self) -> bool:
        """Whether a background synchronization session is running."""
        if self._session is not None and hasattr(self._session, "is_active"):
            return bool(self._session.is_active)
        return self._is_active and self._session is not None

    @property
    def is_connected(self) -> bool:
        """Whether the session is currently connected to the server."""
        if self._session is not None and hasattr(self._session, "is_connected"):
            return bool(self._session.is_connected)
        return self._is_connected

    @property
    def connection_status(self) -> str:
        """Current connection status string ('DISCONNECTED', 'CONNECTING...', 'CONNECTED', etc.)."""
        if self._session is not None and hasattr(self._session, "status"):
            return str(self._session.status)
        return self._connection_status

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
        self._biome_resolver = biome_resolver
        self._custom_aliases = custom_aliases
        self._config_params = {
            "enable_ao": enable_ao,
            "mesh_fluids": mesh_fluids,
            "num_threads": num_threads,
        }
        self._cached_manifest_fingerprint = get_cache_fingerprint()
        self._cached_manifest_timestamp = get_cache_timestamp()
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
            self._is_connected = False
            self._connection_status = "CONNECTING..."
            logger.info(f"LiveSyncSession started connecting to {url} (unified_mesh={unified_mesh})")
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"Failed to start LiveSyncSession: {e}")
            self._session = None
            self._is_active = False
            self._is_connected = False
            self._connection_status = "DISCONNECTED"
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
        self._is_connected = False
        self._connection_status = "DISCONNECTED"
        logger.info("LiveSyncSession stopped.")

    def reset(self) -> None:
        """
        Stops the session and thoroughly frees references (model_db, atlas, errors),
        preventing memory leaks or stale scene references across file operations.
        """
        self.stop()
        self._current_url = ""
        self._model_db = None
        self._atlas = None
        self._biome_resolver = None
        self._custom_aliases = None
        self._config_params = {}
        self._cached_manifest_fingerprint = None
        self._cached_manifest_timestamp = 0.0
        self._last_error = ""

    def clear_cache(self) -> bool:
        """
        Purges cached section meshes on the underlying VoxelWorld, marking all sections dirty.
        """
        if self._session is not None and hasattr(self._session, "clear_cache"):
            try:
                self._session.clear_cache()
                return True
            except Exception as e:
                logger.warning("Failed clearing native session mesh cache: %s", e)
        return False

    def check_and_reload_dirty_cache(self, prefs=None, force: bool = False) -> bool:
        """
        Checks whether the on-disk asset cache has been modified or recompiled.
        If dirty (or force=True):
        1. Reloads latest BakedAtlas, BakedModelDatabase, and BiomeResolver from disk.
        2. Updates the native LiveSyncSession config and model database.
        3. Clears dirty section mesh cache in Rust.
        4. Triggers reload on Blender image datablocks for updated atlas PNGs.
        Returns True if cache was dirty and reloaded, False otherwise.
        """
        is_dirty, current_fp, current_ts = check_cache_dirty(
            self._cached_manifest_fingerprint,
            self._cached_manifest_timestamp,
            prefs=prefs,
        )

        if not is_dirty and not force:
            return False

        logger.info(
            "Dirty cache detected (fp: %s -> %s, ts: %s -> %s). Hot-reloading assets...",
            self._cached_manifest_fingerprint,
            current_fp,
            self._cached_manifest_timestamp,
            current_ts,
        )

        # 1. Reload assets from disk
        new_model_db = load_model_database_from_cache(prefs)
        new_atlas = load_atlas_from_cache(prefs)
        new_biome_resolver = load_biome_resolver_from_cache(prefs)

        self._model_db = new_model_db
        self._atlas = new_atlas
        self._biome_resolver = new_biome_resolver
        self._cached_manifest_fingerprint = current_fp
        self._cached_manifest_timestamp = current_ts

        # 2. Reconfigure active native LiveSyncSession
        if self._session is not None:
            mtk = get_libmtk()
            if mtk is not None and hasattr(mtk, "MesherConfig"):
                enable_ao = self._config_params.get("enable_ao", True)
                mesh_fluids = self._config_params.get("mesh_fluids", True)
                num_threads = self._config_params.get("num_threads", None)
                try:
                    new_config = mtk.MesherConfig(
                        enable_ao=enable_ao,
                        mesh_fluids=mesh_fluids,
                        z_up_coordinates=True,
                        origin_centered=True,
                        weld_vertices=True,
                        num_threads=num_threads,
                        atlas=new_atlas,
                        biome_resolver=new_biome_resolver,
                        custom_aliases=self._custom_aliases,
                    )
                except Exception:
                    new_config = None

                if hasattr(self._session, "hot_reload"):
                    try:
                        self._session.hot_reload(new_config, new_model_db)
                    except Exception as e:
                        logger.warning("Session hot_reload failed: %s", e)
                else:
                    if new_config and hasattr(self._session, "set_config"):
                        try:
                            self._session.set_config(new_config)
                        except Exception:
                            pass
                    if hasattr(self._session, "set_model_db"):
                        try:
                            self._session.set_model_db(new_model_db)
                        except Exception:
                            pass
                    if hasattr(self._session, "clear_cache"):
                        try:
                            self._session.clear_cache()
                        except Exception:
                            pass

        # 3. Reload Blender images in GPU/VRAM
        reloaded = reload_atlas_images(prefs)
        if reloaded > 0:
            logger.info("Reloaded %d atlas image datablock(s) in Blender.", reloaded)

        return True

    def poll_events(self) -> List[Dict[str, Any]]:
        """
        Polls all pending events from the background Rust engine (non-blocking).
        Updates internal connection status accordingly.
        """
        if self._session is None or not self.is_active:
            return []
        try:
            events = self._session.poll_events()
            for ev in events:
                if ev.get("type") == "STATUS_CHANGE":
                    status = ev.get("status", "DISCONNECTED")
                    self._connection_status = status
                    self._is_connected = (status == "CONNECTED")
                    if status == "DISCONNECTED" or status.startswith("DISCONNECTED"):
                        self._is_active = False
            return events
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


def reset_sync_bridge_session() -> SyncBridgeSession:
    """Stops and resets the global singleton session, returning the cleaned instance."""
    global _global_sync_session
    if _global_sync_session is not None:
        _global_sync_session.reset()
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


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

try:
    import libmtk_py as mtk_py
    HAS_LIBMTK = True
except (ImportError, AttributeError):
    try:
        import mtk_py
        HAS_LIBMTK = True
    except (ImportError, AttributeError):
        mtk_py = None
        HAS_LIBMTK = False


def is_sync_available() -> bool:
    """Checks whether the native libmtk Live Sync backend is loaded and ready."""
    return HAS_LIBMTK and hasattr(mtk_py, "LiveSyncSession")


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

    @property
    def is_active(self) -> bool:
        """Whether a background synchronization session is running."""
        return self._is_active and self._session is not None

    @property
    def current_url(self) -> str:
        """Currently connected or target WebSocket URL."""
        return self._current_url

    def start(
        self,
        url: str = "ws://127.0.0.1:8765",
        auto_reconnect: bool = True,
        max_reconnect_attempts: usize = 5,
        model_db: Optional[Any] = None,
        atlas: Optional[Any] = None,
        unified_mesh: bool = True,
        enable_ao: bool = True,
        mesh_fluids: bool = True,
    ) -> bool:
        """
        Starts the background LiveSync client thread connecting to `url`.
        """
        if not is_sync_available():
            logger.error("Cannot start Live Sync: native libmtk_py core is not available.")
            return False

        self.stop()

        self._model_db = model_db
        self._atlas = atlas
        self._unified_mesh = unified_mesh
        self._current_url = url

        try:
            # Construct MesherConfig with target Z-up coordinates for Blender
            config = mtk_py.MesherConfig(
                enable_ao=enable_ao,
                mesh_fluids=mesh_fluids,
                z_up_coordinates=True,
                atlas=atlas,
            )

            # Face culler instance
            culler = mtk_py.FaceCuller() if hasattr(mtk_py, "FaceCuller") else None

            # Instantiate native LiveSyncSession
            self._session = mtk_py.LiveSyncSession(
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


def load_model_database_from_cache(cache_dir_or_file: Optional[Path | str] = None) -> Optional[Any]:
    """
    Attempts to deserialize prebaked BakedModelDatabase from compact binary bytes (bincode).
    Returns None if cache is missing or corrupt.
    """
    if not is_sync_available() or not hasattr(mtk_py, "BakedModelDatabase"):
        return None

    target_path = None
    if cache_dir_or_file is not None:
        p = Path(cache_dir_or_file)
        if p.is_file():
            target_path = p
        elif p.is_dir():
            cand = p / "models.bin"
            if cand.exists():
                target_path = cand

    if target_path is None or not target_path.exists():
        # Default fallback location in user home or addon folder
        home_cand = Path.home() / ".cache" / "mozitoolkit" / "models.bin"
        if home_cand.exists():
            target_path = home_cand

    if target_path and target_path.exists():
        try:
            data = target_path.read_bytes()
            db = mtk_py.BakedModelDatabase.from_bincode_bytes(data)
            logger.info(f"Loaded {len(db)} prebaked models from {target_path}")
            return db
        except Exception as e:
            logger.warning(f"Failed to load binary model cache from {target_path}: {e}")

    return None

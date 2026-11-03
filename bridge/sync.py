"""
MoziToolKit Live Sync Bridge Module.

Encapsulates all interaction with native libmtk LiveSyncSession and
VoxelStorage engines. Provides clean data-in / data-out APIs for Blender
operators and panels.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("MoziToolKit.Bridge.Sync")

from .engine import get_libmtk, require_libmtk
from .assets import (
    load_biome_resolver_from_cache,
    check_cache_dirty,
    get_cache_fingerprint,
    get_cache_timestamp,
    get_configured_ctm_solver,
)


def is_sync_available() -> bool:
    """Checks whether the native libmtk Live Sync backend is loaded and ready."""
    mtk = get_libmtk()
    return bool(mtk and hasattr(mtk, "LiveSyncSession"))


def require_sync() -> None:
    """Ensures native libmtk Live Sync backend is loaded, raising RuntimeError otherwise."""
    require_libmtk("Live Sync")


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
        self._last_error: str = ""
        self._skin_cache_dir: Optional[str] = None

    @property
    def is_active(self) -> bool:
        """Whether a background synchronization session is running."""
        if not self._is_active:
            return False
        if self._session is not None:
            return bool(self._session.is_active)
        return False

    @property
    def is_connected(self) -> bool:
        """Whether the session is currently connected to the server."""
        if not self.is_active or self._session is None:
            return False
        return bool(self._session.is_connected)

    @property
    def connection_status(self) -> str:
        """Current connection status string ('DISCONNECTED', 'CONNECTING...', 'CONNECTED', etc.)."""
        if not self.is_active or self._session is None:
            return "DISCONNECTED"
        return str(self._session.status)

    @property
    def current_url(self) -> str:
        """Currently connected or target WebSocket URL."""
        return self._current_url

    @property
    def last_error(self) -> str:
        """Last error message recorded during session operations."""
        return self._last_error

    @property
    def atlas(self) -> Optional[Any]:
        """Currently loaded BakedAtlas in session memory."""
        return self._atlas

    @property
    def model_db(self) -> Optional[Any]:
        """Currently loaded BakedModelDatabase in session memory."""
        return self._model_db

    @property
    def biome_resolver(self) -> Optional[Any]:
        """Currently loaded BiomeResolver in session memory."""
        return self._biome_resolver

    @property
    def manifest_fingerprint(self) -> Optional[str]:
        """Fingerprint of the active asset cache package associated with this session."""
        return self._cached_manifest_fingerprint

    @property
    def client_generation(self) -> int:
        """Current client generation counter from native session."""
        if self._session is not None:
            return int(self._session.client_generation)
        return 0

    @property
    def current_sequence(self) -> int:
        """Current monotonic sequence ID from native session."""
        if self._session is not None:
            return int(self._session.current_sequence)
        return 0

    @property
    def current_epoch(self) -> int:
        """Current server epoch counter from native session."""
        if self._session is not None:
            return int(self._session.current_epoch)
        return 0

    @property
    def state_hash(self) -> int:
        """Server-confirmed canonical state hash from native session."""
        if self._session is not None:
            return int(self._session.state_hash)
        return 0

    @property
    def server_uuid(self) -> str:
        """Server UUID in hex format."""
        if self._session is not None:
            return str(self._session.server_uuid)
        return ""

    def start(
        self,
        url: str = "ws://127.0.0.1:8765",
        auto_reconnect: bool = True,
        max_reconnect_attempts: int = 5,
        model_db: Optional[Any] = None,
        atlas: Optional[Any] = None,
        enable_ao: bool = True,
        mesh_fluids: bool = True,
        biome_resolver: Optional[Any] = None,
        custom_aliases: Optional[Any] = None,
        num_threads: Optional[int] = None,
        auth_token: Optional[str] = None,
        enable_animated_textures: Optional[bool] = None,
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

        # The Yefira config parser trims auth tokens. Normalise here as well so a
        # token pasted with a trailing space/newline cannot look "identical" yet
        # still be rejected with "Authentication failed".
        auth_token = (auth_token or "").strip() or None

        prefs = None
        try:
            from ..utils.system import get_prefs
            prefs = get_prefs()
        except Exception:
            prefs = None

        if enable_animated_textures is None:
            raw_anim = getattr(prefs, "enable_animated_textures", True) if prefs is not None else True
            anim_enabled = raw_anim if isinstance(raw_anim, bool) else True
        else:
            anim_enabled = bool(enable_animated_textures)

        self._model_db = model_db
        self._atlas = atlas
        self._biome_resolver = biome_resolver
        self._custom_aliases = custom_aliases
        self._config_params = {
            "enable_ao": enable_ao,
            "mesh_fluids": mesh_fluids,
            "num_threads": num_threads,
            "enable_animated_textures": anim_enabled,
        }
        self._cached_manifest_fingerprint = get_cache_fingerprint()
        self._cached_manifest_timestamp = get_cache_timestamp()
        self._current_url = url

        if num_threads is None and prefs is not None:
            num_threads = getattr(prefs, "thread_count", 0) or None

        ctm_solver = get_configured_ctm_solver(prefs) if 'get_configured_ctm_solver' in globals() else None

        try:
            # Construct MesherConfig with target Z-up coordinates for Blender, origin centered, and welded vertices
            config_kwargs = {
                "enable_ao": enable_ao,
                "mesh_fluids": mesh_fluids,
                "z_up_coordinates": True,
                "origin_centered": True,
                "weld_vertices": True,
                "num_threads": num_threads,
                "atlas": atlas,
                "biome_resolver": biome_resolver,
                "custom_aliases": custom_aliases,
                "enable_animated_textures": anim_enabled,
            }
            if ctm_solver is not None:
                config_kwargs["ctm_solver"] = ctm_solver
            config = mtk.MesherConfig(**config_kwargs)

            def _start_native(session: Any) -> None:
                # The auth token always rides on the HELLO; omitting it would make a
                # token-protected server reject the connection with the opaque
                # "Authentication failed" message (RFC v3.1 §4.1).
                if auth_token:
                    session.start(url, auto_reconnect, max_reconnect_attempts, auth_token=auth_token)
                else:
                    session.start(url, auto_reconnect, max_reconnect_attempts)

            # If native session already exists, reuse it to preserve cached voxel storage & mesh cache
            if self._session is not None:
                try:
                    self._session.hot_reload(config, model_db)
                    if self._skin_cache_dir:
                        try:
                            self._session.set_skin_cache_dir(self._skin_cache_dir)
                        except Exception as e:
                            logger.debug("Failed setting skin cache dir on hot reload: %s", e)
                    _start_native(self._session)
                    self._is_active = True
                    self._is_connected = False
                    self._connection_status = "CONNECTING..."
                    logger.info(f"Reused existing LiveSyncSession connecting to {url}")
                    return True
                except Exception as e:
                    logger.debug(f"Failed reusing existing session, creating new: {e}")
                    self._session = None

            # Face culler instance
            culler = mtk.FaceCuller()

            # Instantiate native LiveSyncSession
            self._session = mtk.LiveSyncSession(
                config=config,
                culler=culler,
                model_db=model_db,
            )
            if self._skin_cache_dir:
                try:
                    self._session.set_skin_cache_dir(self._skin_cache_dir)
                except Exception as e:
                    logger.debug("Failed setting skin cache dir on new session: %s", e)

            _start_native(self._session)
            self._is_active = True
            self._is_connected = False
            self._connection_status = "CONNECTING..."
            logger.info(f"LiveSyncSession started connecting to {url}")
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"Failed to start LiveSyncSession: {e}")
            self._session = None
            self._is_active = False
            self._is_connected = False
            self._connection_status = "DISCONNECTED"
            return False

    def load_from_point_cloud(self, point_cloud: Any) -> bool:
        """Restores voxel storage in the native session from an existing point cloud without re-meshing."""
        if self._session is not None and hasattr(self._session, "load_from_point_cloud"):
            try:
                self._session.load_from_point_cloud(point_cloud)
                return True
            except Exception as e:
                logger.error("Failed loading from point cloud: %s", e)
        return False

    def start_with_cache(
        self,
        url: str = "ws://127.0.0.1:8765",
        auto_reconnect: bool = True,
        max_reconnect_attempts: int = 5,
        server_uuid: str = "",
        epoch: int = 0,
        sequence: int = 0,
        min_pos: tuple[int, int, int] = (0, 0, 0),
        size: tuple[int, int, int] = (0, 0, 0),
        state_hash: int = 0,
        dimension: str = "minecraft:overworld",
        point_cloud: Optional[Any] = None,
        model_db: Optional[Any] = None,
        atlas: Optional[Any] = None,
        enable_ao: bool = True,
        mesh_fluids: bool = True,
        biome_resolver: Optional[Any] = None,
        custom_aliases: Optional[Any] = None,
        num_threads: Optional[int] = None,
        auth_token: Optional[str] = None,
        enable_animated_textures: Optional[bool] = None,
    ) -> bool:
        """
        Starts the LiveSync client using cached handshake parameters for 0ms zero-rebuild reconnect.
        Restores VoxelStorage from `point_cloud` if provided.
        """
        mtk = get_libmtk()
        if mtk is None or not hasattr(mtk, "LiveSyncSession"):
            self._last_error = "Native libmtk_py core is not available."
            logger.error("Cannot start Live Sync: native libmtk_py core is not available.")
            return False

        self.stop()
        self._last_error = ""

        auth_token = (auth_token or "").strip() or None

        prefs = None
        try:
            from ..utils.system import get_prefs
            prefs = get_prefs()
        except Exception:
            prefs = None

        if enable_animated_textures is None:
            raw_anim = getattr(prefs, "enable_animated_textures", True) if prefs is not None else True
            anim_enabled = raw_anim if isinstance(raw_anim, bool) else True
        else:
            anim_enabled = bool(enable_animated_textures)

        self._model_db = model_db
        self._atlas = atlas
        self._biome_resolver = biome_resolver
        self._custom_aliases = custom_aliases
        self._config_params = {
            "enable_ao": enable_ao,
            "mesh_fluids": mesh_fluids,
            "num_threads": num_threads,
            "enable_animated_textures": anim_enabled,
        }
        self._cached_manifest_fingerprint = get_cache_fingerprint()
        self._cached_manifest_timestamp = get_cache_timestamp()
        self._current_url = url

        if num_threads is None and prefs is not None:
            num_threads = getattr(prefs, "thread_count", 0) or None

        ctm_solver = get_configured_ctm_solver(prefs) if 'get_configured_ctm_solver' in globals() else None

        try:
            config_kwargs = {
                "enable_ao": enable_ao,
                "mesh_fluids": mesh_fluids,
                "z_up_coordinates": True,
                "origin_centered": True,
                "weld_vertices": True,
                "num_threads": num_threads,
                "atlas": atlas,
                "biome_resolver": biome_resolver,
                "custom_aliases": custom_aliases,
                "enable_animated_textures": anim_enabled,
            }
            if ctm_solver is not None:
                config_kwargs["ctm_solver"] = ctm_solver
            config = mtk.MesherConfig(**config_kwargs)

            def _start_cached_native(session: Any) -> None:
                if point_cloud is not None and hasattr(session, "load_from_point_cloud"):
                    session.load_from_point_cloud(point_cloud)
                session.start_with_cache(
                    url=url,
                    auto_reconnect=auto_reconnect,
                    max_reconnect_attempts=max_reconnect_attempts,
                    server_uuid=server_uuid,
                    epoch=epoch,
                    sequence=sequence,
                    min_pos=min_pos,
                    size=size,
                    state_hash=state_hash,
                    dimension=dimension,
                    auth_token=auth_token,
                )

            if self._session is not None:
                try:
                    self._session.hot_reload(config, model_db)
                    if self._skin_cache_dir:
                        try:
                            self._session.set_skin_cache_dir(self._skin_cache_dir)
                        except Exception as e:
                            logger.debug("Failed setting skin cache dir on hot reload: %s", e)
                    _start_cached_native(self._session)
                    self._is_active = True
                    self._is_connected = False
                    self._connection_status = "CONNECTING..."
                    logger.info("Reused existing LiveSyncSession connecting with cache to %s", url)
                    return True
                except Exception as e:
                    logger.debug("Failed reusing existing session for start_with_cache, creating new: %s", e)
                    self._session = None

            culler = mtk.FaceCuller()
            self._session = mtk.LiveSyncSession(
                config=config,
                culler=culler,
                model_db=model_db,
            )
            if self._skin_cache_dir:
                try:
                    self._session.set_skin_cache_dir(self._skin_cache_dir)
                except Exception as e:
                    logger.debug("Failed setting skin cache dir on new session: %s", e)

            _start_cached_native(self._session)
            self._is_active = True
            self._is_connected = False
            self._connection_status = "CONNECTING..."
            logger.info("LiveSyncSession started with cache connecting to %s", url)
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error("Failed to start LiveSyncSession with cache: %s", e)
            self._session = None
            self._is_active = False
            self._is_connected = False
            self._connection_status = "DISCONNECTED"
            return False

    def stop(self, keep_session: bool = True) -> None:
        """Cleanly stops background sync client and pauses networking."""
        if self._session is not None:
            try:
                self._session.stop()
            except Exception as e:
                logger.debug(f"Error during LiveSyncSession shutdown: {e}")
        if not keep_session:
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
        self.stop(keep_session=False)
        self._current_url = ""
        self._model_db = None
        self._atlas = None
        self._biome_resolver = None
        self._custom_aliases = None
        self._config_params = {}
        self._cached_manifest_fingerprint = None
        self._cached_manifest_timestamp = 0.0
        self._last_error = ""
        for attr in ("get_world_mesh", "get_storage", "poll_events"):
            if attr in self.__dict__:
                del self.__dict__[attr]

    def clear_cache(self) -> bool:
        """
        Purges cached section meshes on the underlying VoxelWorld, marking all sections dirty.
        """
        if self._session is not None:
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
        Returns True if cache was dirty and reloaded, False otherwise.

        Refreshing `bpy.data.images` datablocks is deliberately *not* done here:
        that is DCC host business and belongs to the caller
        (`utils.materials.builder.atlas_refresh.reload_atlas_images`).
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
                anim_enabled = self._config_params.get("enable_animated_textures")
                if anim_enabled is None:
                    raw_anim = getattr(prefs, "enable_animated_textures", True) if prefs is not None else True
                    anim_enabled = raw_anim if isinstance(raw_anim, bool) else True
                ctm_solver = get_configured_ctm_solver(prefs) if 'get_configured_ctm_solver' in globals() else None
                try:
                    cfg_kwargs = {
                        "enable_ao": enable_ao,
                        "mesh_fluids": mesh_fluids,
                        "z_up_coordinates": True,
                        "origin_centered": True,
                        "weld_vertices": True,
                        "num_threads": num_threads,
                        "atlas": new_atlas,
                        "biome_resolver": new_biome_resolver,
                        "custom_aliases": self._custom_aliases,
                        "enable_animated_textures": anim_enabled,
                    }
                    if ctm_solver is not None:
                        cfg_kwargs["ctm_solver"] = ctm_solver
                    new_config = mtk.MesherConfig(**cfg_kwargs)
                except Exception:
                    new_config = None

                try:
                    self._session.hot_reload(new_config, new_model_db)
                except Exception as e:
                    logger.warning("Session hot_reload failed: %s", e)

        return True

    def poll_events(self) -> List[Dict[str, Any]]:
        """
        Polls all pending events from the background Rust engine (non-blocking).
        Updates internal connection status accordingly.
        """
        # Poll even when the worker has already stopped: the terminal DISCONNECTED
        # event is queued right before the worker exits, and dropping it leaves the
        # UI stuck on a stale "CONNECTED" state.
        if self._session is None:
            return []
        try:
            try:
                events = self._session.poll_events(coalesce_meshes=True)
            except TypeError:
                events = self._session.poll_events()
            for ev in events:
                if ev.get("type") == "STATUS_CHANGE":
                    status = ev.get("status", "DISCONNECTED")
                    self._connection_status = status
                    if status == "CONNECTED":
                        self._is_connected = True
                    elif status.startswith("DISCONNECTED"):
                        self._is_connected = False
                        self._is_active = False
                    else:
                        # Intermediate states (CONNECTING/RECONNECTING/errors) mean
                        # the socket is not usable, but the worker is still alive.
                        self._is_connected = False
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

    def request_resync(self) -> bool:
        """Sends RESYNC_REQUEST (opcode 0x0D) to request state recovery."""
        if self._session is None:
            return False
        try:
            if hasattr(self._session, "request_resync"):
                self._session.request_resync()
            return True
        except Exception as e:
            logger.error(f"Failed to send Resync Request: {e}")
            return False

    def get_dynamic_entity_atlases(self) -> Optional[dict[int, bytes]]:
        """Returns the `{chunk_id: RGBA bytes}` dynamic entity atlas map of the live session."""
        if self._session is None:
            return None
        try:
            atlases = self._session.get_dynamic_entity_atlases()
            if atlases:
                return atlases
        except Exception as e:
            logger.debug("Failed getting dynamic entity atlases from session: %s", e)
        return None

    def set_skin_cache_dir(self, cache_dir: Optional[str]) -> None:
        """Sets the player head skin disk cache path on the native session."""
        self._skin_cache_dir = cache_dir
        if self._session is not None and hasattr(self._session, "set_skin_cache_dir"):
            try:
                self._session.set_skin_cache_dir(cache_dir)
            except Exception as e:
                logger.debug("Failed setting skin cache dir on session: %s", e)



# Global singleton bridge instance (anchored in builtins to prevent dual-import split brain across packages)
import builtins
_GLOBAL_SESSION_ATTR = "_mozi_global_sync_bridge_session"
if not hasattr(builtins, _GLOBAL_SESSION_ATTR):
    setattr(builtins, _GLOBAL_SESSION_ATTR, SyncBridgeSession())

_global_sync_session = getattr(builtins, _GLOBAL_SESSION_ATTR)


def get_sync_bridge_session() -> SyncBridgeSession:
    """Returns the shared global SyncBridgeSession singleton."""
    return getattr(builtins, _GLOBAL_SESSION_ATTR, _global_sync_session)


def reset_sync_bridge_session() -> SyncBridgeSession:
    """Stops and resets the global singleton session, returning the cleaned instance."""
    session = get_sync_bridge_session()
    session.reset()
    return session


# Re-export cache loaders directly from bridge.assets to avoid duplicate wrappers
from .assets import (
    load_model_database_from_cache,
    load_atlas_from_cache,
    load_biome_resolver_from_cache,
)

__all__ = [
    "is_sync_available",
    "require_sync",
    "SyncBridgeSession",
    "get_sync_bridge_session",
    "reset_sync_bridge_session",
    "load_model_database_from_cache",
    "load_atlas_from_cache",
    "load_biome_resolver_from_cache",
]


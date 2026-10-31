"""
MoziToolKit Debug World Bridge Module.
Provides high-performance geometry generation and scene injection for the
embedded Minecraft debug world snapshot.
Uses the unified, network-free Voxel World Pipeline (bridge.world) to generate
fully modeled, textured, and shaded objects with Atlas PBR materials.
"""

from typing import Optional, Tuple, Any, Dict
import logging

logger = logging.getLogger("MoziToolKit.Bridge.Debug")

from .engine import get_libmtk, has_libmtk, require_libmtk


def _has_valid_vanilla_pack(prefs=None) -> bool:
    """Resolves the host-side vanilla-client gate, failing closed if the guard is unavailable."""
    from ..utils.assets.guard import has_valid_vanilla_pack
    return has_valid_vanilla_pack(prefs)


def is_debug_world_available(prefs=None) -> bool:
    """True when libmtk_py supports debug worlds and client assets are actually available."""
    if not has_libmtk():
        return False
    return _has_valid_vanilla_pack(prefs)


def clear_debug_world_cache() -> None:
    """Clears the internally cached debug storage in libmtk_py."""
    mtk = get_libmtk()
    if mtk is not None:
        mtk.VoxelStorage.clear_debug_world_cache()


def load_debug_world_storage(prefs=None, states=None, stack=None):
    """
    Loads or dynamically generates the canonical Minecraft debug world into a VoxelStorage instance.
    Fully driven by precompiled asset cache and configured resource pack stack:
    1. Explicit blockstates list (if provided);
    2. Active precompiled model database from cache (`.mtkcache`);
    3. Active configured resource pack stack containing a Vanilla Client base pack;
    4. Host-level asset root/archive validated by the same content gate.

    Strictly rejects generation with ValueError if no valid vanilla client assets are found.
    """
    mtk = require_libmtk("load_debug_world_storage")
    voxel_storage = mtk.VoxelStorage

    if states is not None:
        return voxel_storage.create_debug_world_from_states(states)

    if not _has_valid_vanilla_pack(prefs):
        clear_debug_world_cache()
        raise ValueError(
            "Cannot load debug world: no Minecraft Vanilla Client assets are configured"
        )

    # 1. Prefer driving directly from active precompiled asset cache (.mtkcache)
    try:
        from .assets.cache import load_model_database_from_cache
        cached_db = load_model_database_from_cache(prefs)
        if cached_db is not None and not cached_db.is_empty():
            return voxel_storage.create_debug_world_from_model_db(cached_db)
    except Exception as e:
        logger.debug(f"Could not load model_db from cache for debug world: {e}")

    # 2. Drive from active configured resource pack stack
    if stack is None:
        try:
            from .assets import get_configured_pack_stack
            stack = get_configured_pack_stack(prefs)
        except Exception:
            stack = None

    if stack is not None:
        pack_count = stack.get_pack_count()
        has_base = stack.has_vanilla_client_base()
        if pack_count > 0 and has_base:
            return voxel_storage.create_debug_world_from_pack_stack(stack)

    # 3. Direct backend creation; libmtk re-validates the host-level asset roots itself.
    return voxel_storage.create_debug_world()


def generate_debug_world_mesh(
    storage=None,
    config=None,
    culler=None,
    model_db=None,
    atlas=None,
    biome_resolver=None,
    prefs=None,
    num_threads: Optional[int] = None,
    with_models: bool = True,
    progress_callback: Optional[Any] = None,
) -> Tuple[Any, float]:
    """
    Meshes the debug world using VoxelWorld and returns (MeshData, elapsed_time_ms).
    When with_models is True (default), resolves baked models, atlas UVs, and biome tinting.
    """
    if storage is None:
        storage = load_debug_world_storage()

    if with_models:
        from .world import mesh_voxel_storage
        return mesh_voxel_storage(
            storage=storage,
            config=config,
            model_db=model_db,
            atlas=atlas,
            biome_resolver=biome_resolver,
            prefs=prefs,
            num_threads=num_threads,
            progress_callback=progress_callback,
        )
    else:
        import time
        mtk = require_libmtk("generate_debug_world_mesh")
        if config is None:
            config = mtk.MesherConfig(
                enable_ao=True,
                mesh_fluids=True,
                z_up_coordinates=True,
                origin_centered=True,
                num_threads=num_threads,
            )
        elif num_threads is not None:
            config.num_threads = num_threads
        t0 = time.perf_counter()
        world = mtk.VoxelWorld.from_storage(
            storage=storage,
            config=config,
            culler=culler,
            model_db=None,
            num_threads=num_threads,
        )
        mesh_data = world.rebuild_all()
        t1 = time.perf_counter()
        return mesh_data, (t1 - t0) * 1000.0


def build_debug_world_data(
    prefs=None,
    states=None,
    stack=None,
    model_db=None,
    atlas=None,
    biome_resolver=None,
    enable_ao: bool = True,
    mesh_fluids: bool = True,
    weld_vertices: bool = True,
    origin_centered: bool = True,
    num_threads: Optional[int] = None,
    progress_callback: Optional[Any] = None,
) -> Tuple[Any, Any, float]:
    """
    Pure data background worker target for debug world generation.
    Generates VoxelStorage and meshes it without calling any Blender host APIs.
    Returns (mesh_data, storage, elapsed_ms).
    """
    from .world import mesh_voxel_storage

    storage = load_debug_world_storage(prefs=prefs, states=states, stack=stack)

    # Asset cache gate: resolve and strictly require model_db and atlas
    if model_db is None or atlas is None or biome_resolver is None:
        from .world import get_world_pipeline_assets
        cached_mdb, cached_atlas, cached_resolver = get_world_pipeline_assets(prefs)
        model_db = model_db or cached_mdb
        atlas = atlas or cached_atlas
        biome_resolver = biome_resolver or cached_resolver

    if model_db is None:
        raise ValueError("Active asset cache (model_db) is strictly required to mesh Minecraft debug world")
    if atlas is None:
        raise ValueError("Active asset cache (atlas) is strictly required to mesh Minecraft debug world")

    mesh_data, elapsed_ms = mesh_voxel_storage(
        storage=storage,
        model_db=model_db,
        atlas=atlas,
        biome_resolver=biome_resolver,
        prefs=prefs,
        enable_ao=enable_ao,
        mesh_fluids=mesh_fluids,
        weld_vertices=weld_vertices,
        origin_centered=origin_centered,
        num_threads=num_threads,
        progress_callback=progress_callback,
    )
    return mesh_data, storage, elapsed_ms


__all__ = [
    "is_debug_world_available",
    "clear_debug_world_cache",
    "load_debug_world_storage",
    "generate_debug_world_mesh",
    "build_debug_world_data",
]

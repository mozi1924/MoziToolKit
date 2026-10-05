"""
MoziToolKit Debug World Bridge Module.
Provides high-performance geometry generation and scene injection for the
embedded Minecraft debug world snapshot.
Uses the unified, network-free Voxel World Pipeline (bridge.world) to generate
fully modeled, textured, and shaded objects with Atlas PBR materials.
"""

from typing import Optional, Tuple, Any, Dict
import logging

from .mesh import inject_mesh_data

logger = logging.getLogger("MoziToolKit.Bridge.Debug")

from .engine import get_libmtk, has_libmtk, require_libmtk


def __getattr__(name: str) -> Any:
    if name == "libmtk_py":
        return get_libmtk()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def is_debug_world_available() -> bool:
    """Checks if libmtk_py has the embedded debug world capability."""
    mtk = get_libmtk()
    return mtk is not None and hasattr(getattr(mtk, "VoxelStorage", None), "create_debug_world")


def load_debug_world_storage(prefs=None, states=None, stack=None):
    """
    Loads or dynamically generates the canonical Minecraft debug world into a VoxelStorage instance.
    Supports pure-code layout from:
    1. Explicit blockstates list;
    2. Active configured resource pack stack (including any mod packs);
    3. Canonical unpack directory (/home/mozi/mc);
    4. Builtin pure-code fallback generator.
    """
    mtk = require_libmtk("load_debug_world_storage")
    voxel_storage = getattr(mtk, "VoxelStorage", None)
    if voxel_storage is None:
        raise RuntimeError("libmtk_py does not support VoxelStorage")

    if states is not None:
        if hasattr(voxel_storage, "create_debug_world_from_states"):
            return voxel_storage.create_debug_world_from_states(states)
        return voxel_storage.create_debug_world(states=states)

    if stack is None:
        try:
            from .assets import get_configured_pack_stack
            stack = get_configured_pack_stack(prefs)
        except Exception:
            stack = None

    if stack is not None and hasattr(voxel_storage, "create_debug_world_from_pack_stack"):
        pack_count = getattr(stack, "get_pack_count", lambda: 0)()
        if pack_count > 0:
            return voxel_storage.create_debug_world_from_pack_stack(stack)

        # Fallback to local dev unpack directory if configured stack has no packs
        from pathlib import Path
        mc_path = Path("/home/mozi/mc")
        if mc_path.exists() and (mc_path / "assets").exists():
            stack.add_directory_pack(str(mc_path.resolve()), "VanillaMC")
            return voxel_storage.create_debug_world_from_pack_stack(stack)

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
) -> Tuple[Any, float]:
    """
    Meshes the debug world using SectionMesher and returns (MeshData, elapsed_time_ms).
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
        elif num_threads is not None and hasattr(config, "num_threads"):
            config.num_threads = num_threads
        t0 = time.perf_counter()
        mesh_data = mtk.SectionMesher.mesh_world(storage, config, culler, None)
        t1 = time.perf_counter()
        return mesh_data, (t1 - t0) * 1000.0


def create_debug_world_object(
    context=None,
    name: str = "MTK_Debug_World",
    prefs=None,
    model_db=None,
    atlas=None,
    biome_resolver=None,
    enable_ao: bool = True,
    mesh_fluids: bool = True,
    weld_vertices: bool = True,
    origin_centered: bool = True,
    reuse_existing: bool = True,
    config=None,
    culler=None,
    states=None,
    stack=None,
) -> Tuple[Any, Dict[str, Any]]:
    """
    Meshes the canonical debug world and creates/updates a Blender Mesh Object in the active scene,
    binding all precompiled Atlas chunk PBR materials and shaders.
    Returns (bpy_object, stats_dict).
    """
    from .world import ingest_voxel_world

    storage = load_debug_world_storage(prefs=prefs, states=states, stack=stack)

    obj, stats = ingest_voxel_world(
        storage=storage,
        context=context,
        name=name,
        prefs=prefs,
        model_db=model_db,
        atlas=atlas,
        biome_resolver=biome_resolver,
        enable_ao=enable_ao,
        mesh_fluids=mesh_fluids,
        weld_vertices=weld_vertices,
        origin_centered=origin_centered,
        reuse_existing=reuse_existing,
    )

    # Ensure backwards compatibility for dict keys
    if "elapsed_ms" not in stats and "meshing_time_ms" in stats:
        stats["elapsed_ms"] = stats["meshing_time_ms"]

    return obj, stats

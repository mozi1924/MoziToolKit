"""
MoziToolKit Debug World Bridge Module.
Provides high-performance geometry generation and scene injection for the
embedded Minecraft debug world snapshot.
"""

from typing import Optional, Tuple, Any
import logging

from .mesh import inject_mesh_data

logger = logging.getLogger("MoziToolKit.Bridge.Debug")

try:
    import libmtk_py
except ImportError:
    libmtk_py = None


def is_debug_world_available() -> bool:
    """Checks if libmtk_py has the embedded debug world capability."""
    return libmtk_py is not None and hasattr(libmtk_py.VoxelStorage, "create_debug_world")


def load_debug_world_storage():
    """Loads the canonical embedded Minecraft debug world into a VoxelStorage instance."""
    if not is_debug_world_available():
        raise RuntimeError("libmtk_py is not available or does not support create_debug_world")
    return libmtk_py.VoxelStorage.create_debug_world()


def generate_debug_world_mesh(
    storage=None,
    config=None,
    culler=None,
    model_db=None,
):
    """
    Meshes the debug world using SectionMesher and returns (MeshData, elapsed_time_ms).
    """
    import time

    if storage is None:
        storage = load_debug_world_storage()

    if config is None:
        config = libmtk_py.MesherConfig(
            enable_ao=True,
            mesh_fluids=True,
            z_up_coordinates=True,
            origin_centered=True,
        )

    t0 = time.perf_counter()
    mesh_data = libmtk_py.SectionMesher.mesh_world(storage, config, culler, model_db)
    t1 = time.perf_counter()

    elapsed_ms = (t1 - t0) * 1000.0
    return mesh_data, elapsed_ms


def create_debug_world_object(
    context=None,
    name: str = "MTK_Debug_World",
    config=None,
    culler=None,
    model_db=None,
) -> Tuple[Any, dict]:
    """
    Meshes the embedded debug world and creates/updates a Blender Mesh Object in the active scene.
    Returns (bpy_object, stats_dict).
    """
    try:
        import bpy
    except ImportError:
        raise RuntimeError("bpy is not available in headless non-Blender environment")

    if context is None:
        context = bpy.context

    mesh_data, elapsed_ms = generate_debug_world_mesh(config=config, culler=culler, model_db=model_db)

    # Create new mesh datablock
    b_mesh = bpy.data.meshes.new(name=name)
    inject_mesh_data(b_mesh, mesh_data)

    # Link to active collection
    obj = bpy.data.objects.new(name=name, object_data=b_mesh)
    target_coll = context.collection if context and context.collection else bpy.context.scene.collection
    target_coll.objects.link(obj)

    # Select object
    if context and hasattr(context, "view_layer"):
        obj.select_set(True)
        context.view_layer.objects.active = obj

    stats = {
        "vertex_count": mesh_data.vertex_count,
        "quad_count": mesh_data.quad_count,
        "elapsed_ms": elapsed_ms,
        "object_name": obj.name,
    }

    return obj, stats

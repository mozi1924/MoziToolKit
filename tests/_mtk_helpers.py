"""Small test helpers for native world meshing."""

from __future__ import annotations


def mesh_world(storage, config=None, culler=None, model_db=None):
    """Mesh a VoxelStorage through the 2.0 VoxelWorld path."""
    import libmtk_py

    world = libmtk_py.VoxelWorld.from_storage(
        storage,
        config,
        culler,
        model_db,
        True,
    )
    return world.rebuild_all()

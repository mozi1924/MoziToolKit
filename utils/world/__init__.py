"""
MoziToolKit Utils: Voxel World Scene Pipeline & Injection Subsystem.
"""

from __future__ import annotations

from .injector import (
    apply_voxel_mesh_to_blender,
    create_debug_world_object,
    ingest_voxel_world,
)
from .assembler import (
    VoxelWorldAssemblyRequest,
    assemble_voxel_world,
    safe_set_custom_prop,
    safe_get_custom_prop,
    persist_dynamic_entity_slots,
)

__all__ = [
    "apply_voxel_mesh_to_blender",
    "ingest_voxel_world",
    "create_debug_world_object",
    "VoxelWorldAssemblyRequest",
    "assemble_voxel_world",
    "safe_set_custom_prop",
    "safe_get_custom_prop",
    "persist_dynamic_entity_slots",
]

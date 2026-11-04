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
from .sync_container import (
    get_or_create_world_container,
    get_or_create_world_mesh_object,
    resolve_world_root_object,
    is_yefira_root_object,
    is_yefira_world_object,
    update_world_mesh,
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
    "get_or_create_world_container",
    "get_or_create_world_mesh_object",
    "resolve_world_root_object",
    "is_yefira_root_object",
    "is_yefira_world_object",
    "update_world_mesh",
]

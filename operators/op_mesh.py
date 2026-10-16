"""
Mesh and Normal Management Operators for MoziToolKit.

Backward compatibility module.
The operators have been modularized into the `operators.mesh` package:
  - `MOZI_OT_select_hard_edges`: `operators.mesh.op_select_hard_edges`
  - `MOZI_OT_clear_custom_normals`: `operators.mesh.op_clear_normals`
  - `MOZI_OT_rebuild_mesh`: `operators.mesh.op_rebuild_mesh`
"""

from __future__ import annotations

from .mesh import (
    MOZI_OT_select_hard_edges,
    MOZI_OT_clear_custom_normals,
    MOZI_OT_rebuild_mesh,
    resolve_mesh_rebuild_targets,
    _resolve_mesh_rebuild_targets_from_root,
    OPERATOR_CLASSES,
    OPERATORS_CLASSES,
)
from .mesh.op_rebuild_mesh import (
    extract_voxel_point_cloud,
    mesh_voxel_storage,
    inject_mesh_data,
    ensure_world_materials,
    get_sync_bridge_session,
    check_asset_cache_status,
    check_cache_dirty,
    ensure_pipeline_assets_ready_sync,
    invalidate_asset_cache_memory,
    reload_atlas_images,
    run_task_with_asset_guard,
    get_world_pipeline_assets,
    clear_world_sessions,
)
from .mesh.op_select_hard_edges import analyze_mesh_hard_edges

__all__ = [
    "MOZI_OT_select_hard_edges",
    "MOZI_OT_clear_custom_normals",
    "MOZI_OT_rebuild_mesh",
    "resolve_mesh_rebuild_targets",
    "_resolve_mesh_rebuild_targets_from_root",
    "OPERATOR_CLASSES",
    "OPERATORS_CLASSES",
    "extract_voxel_point_cloud",
    "mesh_voxel_storage",
    "inject_mesh_data",
    "ensure_world_materials",
    "get_sync_bridge_session",
    "analyze_mesh_hard_edges",
]

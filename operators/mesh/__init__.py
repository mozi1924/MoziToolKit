"""
Mesh operations and normal management operators package.
"""

from __future__ import annotations

from .op_select_hard_edges import MOZI_OT_select_hard_edges
from .op_clear_normals import MOZI_OT_clear_custom_normals
from .op_rebuild_mesh import (
    MOZI_OT_rebuild_mesh,
    resolve_mesh_rebuild_targets,
    _resolve_mesh_rebuild_targets_from_root,
)

OPERATOR_CLASSES = (
    MOZI_OT_select_hard_edges,
    MOZI_OT_clear_custom_normals,
    MOZI_OT_rebuild_mesh,
)
OPERATORS_CLASSES = OPERATOR_CLASSES

__all__ = [
    "MOZI_OT_select_hard_edges",
    "MOZI_OT_clear_custom_normals",
    "MOZI_OT_rebuild_mesh",
    "resolve_mesh_rebuild_targets",
    "_resolve_mesh_rebuild_targets_from_root",
    "OPERATOR_CLASSES",
    "OPERATORS_CLASSES",
]

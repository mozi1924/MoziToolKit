"""
MoziToolKit Blender DNA & Direct Memory Ingestion Adapter Subsystem.

Provides defensive, cross-version hardware-accelerated memory pointer extraction
and strict boundaries between unstable DNA layouts and standard Python APIs.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .base import BaseDnaResolver
from .detector import (
    get_blender_version,
    is_dna_available,
    is_dna_enabled,
    is_version_supported,
    set_dna_enabled,
)
from .guard import (
    check_pointer_alignment,
    is_valid_pointer,
    safe_as_pointer,
)
from .v4_2 import DnaResolverV42
from .v5_0 import DnaResolverV50

logger = logging.getLogger("MoziToolKit.Bridge.DNA")

_active_resolver: Optional[BaseDnaResolver] = None


def get_dna_resolver() -> BaseDnaResolver:
    """
    Returns the appropriate singleton DnaResolver instance for the active Blender version.
    """
    global _active_resolver
    if _active_resolver is not None:
        return _active_resolver

    major, minor, _ = get_blender_version()
    if major >= 5:
        _active_resolver = DnaResolverV50()
    else:
        _active_resolver = DnaResolverV42()

    return _active_resolver


def resolve_attribute_ptr(
    attr: Any, min_elements: int = 1, required_align: int = 4
) -> Optional[int]:
    """Resolves raw memory pointer for an attribute layer."""
    return get_dna_resolver().resolve_attribute_ptr(
        attr, min_elements=min_elements, required_align=required_align
    )


def resolve_positions_ptr(mesh: Any, expected_count: Optional[int] = None) -> Optional[int]:
    """Resolves raw memory pointer for vertex 3D positions."""
    return get_dna_resolver().resolve_positions_ptr(mesh, expected_count=expected_count)


def resolve_corner_verts_ptr(mesh: Any, expected_count: Optional[int] = None) -> Optional[int]:
    """Resolves raw memory pointer for corner vertex indices."""
    return get_dna_resolver().resolve_corner_verts_ptr(mesh, expected_count=expected_count)


def resolve_loop_uvs_ptr(
    mesh: Any,
    uv_name: Optional[str] = None,
    expected_count: Optional[int] = None,
) -> Optional[int]:
    """Resolves raw memory pointer for loop UV coordinates."""
    return get_dna_resolver().resolve_loop_uvs_ptr(
        mesh, uv_name=uv_name, expected_count=expected_count
    )


def resolve_materials_ptr(mesh: Any, expected_count: Optional[int] = None) -> Optional[int]:
    """Resolves raw memory pointer for polygon material indices."""
    return get_dna_resolver().resolve_materials_ptr(mesh, expected_count=expected_count)


def resolve_colors_ptr(
    mesh: Any,
    color_name: Optional[str] = None,
    expected_count: Optional[int] = None,
) -> Optional[int]:
    """Resolves raw memory pointer for vertex/loop colors."""
    return get_dna_resolver().resolve_colors_ptr(
        mesh, color_name=color_name, expected_count=expected_count
    )


def resolve_point_cloud_ptrs(
    cloud_data: Any, expected_count: Optional[int] = None
) -> Dict[str, Optional[int]]:
    """Resolves raw memory pointers for all available voxel point cloud attributes."""
    return get_dna_resolver().resolve_point_cloud_ptrs(
        cloud_data, expected_count=expected_count
    )


__all__ = [
    "BaseDnaResolver",
    "DnaResolverV42",
    "DnaResolverV50",
    "check_pointer_alignment",
    "get_blender_version",
    "get_dna_resolver",
    "is_dna_available",
    "is_dna_enabled",
    "is_valid_pointer",
    "is_version_supported",
    "resolve_attribute_ptr",
    "resolve_colors_ptr",
    "resolve_corner_verts_ptr",
    "resolve_loop_uvs_ptr",
    "resolve_materials_ptr",
    "resolve_point_cloud_ptrs",
    "resolve_positions_ptr",
    "safe_as_pointer",
    "set_dna_enabled",
]

"""
Abstract Base DNA Resolver protocol.

Defines the contract for resolving direct memory pointers across different
Blender version architectures.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseDnaResolver(ABC):
    """Abstract interface for resolving raw memory addresses from Blender datablocks."""

    @abstractmethod
    def resolve_attribute_ptr(
        self, attr: Any, min_elements: int = 1, required_align: int = 4
    ) -> Optional[int]:
        """Resolves the raw memory address of the first item in a Blender attribute layer."""
        raise NotImplementedError

    @abstractmethod
    def resolve_positions_ptr(
        self, mesh: Any, expected_count: Optional[int] = None
    ) -> Optional[int]:
        """Resolves the memory pointer for vertex 3D positions (`float32 * 3`)."""
        raise NotImplementedError

    @abstractmethod
    def resolve_corner_verts_ptr(
        self, mesh: Any, expected_count: Optional[int] = None
    ) -> Optional[int]:
        """Resolves the memory pointer for corner vertex indices (`uint32` or `int32`)."""
        raise NotImplementedError

    @abstractmethod
    def resolve_loop_uvs_ptr(
        self,
        mesh: Any,
        uv_name: Optional[str] = None,
        expected_count: Optional[int] = None,
    ) -> Optional[int]:
        """Resolves the memory pointer for loop UV coordinates (`float32 * 2`)."""
        raise NotImplementedError

    @abstractmethod
    def resolve_materials_ptr(
        self, mesh: Any, expected_count: Optional[int] = None
    ) -> Optional[int]:
        """Resolves the memory pointer for polygon material slot indices (`int32`)."""
        raise NotImplementedError

    @abstractmethod
    def resolve_colors_ptr(
        self,
        mesh: Any,
        color_name: Optional[str] = None,
        expected_count: Optional[int] = None,
    ) -> Optional[int]:
        """Resolves the memory pointer for vertex or loop colors (`float32 * 4`)."""
        raise NotImplementedError

    @abstractmethod
    def resolve_point_cloud_ptrs(
        self, cloud_data: Any, expected_count: Optional[int] = None
    ) -> Dict[str, Optional[int]]:
        """Resolves all available attribute pointers for a voxel point cloud."""
        raise NotImplementedError

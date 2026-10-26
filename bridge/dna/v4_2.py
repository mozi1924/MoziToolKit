"""
Blender 4.2 LTS DNA & CustomData pointer resolver implementation.

Resolves CustomData layer pointers via Blender 4.2's RNA attribute architecture
and memory offset layouts.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .base import BaseDnaResolver
from .guard import safe_as_pointer

logger = logging.getLogger("MoziToolKit.Bridge.DNA.V42")


class DnaResolverV42(BaseDnaResolver):
    """Blender 4.2 LTS CustomData & RNA attribute memory pointer resolver."""

    def resolve_attribute_ptr(
        self, attr: Any, min_elements: int = 1, required_align: int = 4
    ) -> Optional[int]:
        """
        Extracts the contiguous memory pointer from an Attribute's first element.
        Safe against empty collections and unallocated layers.
        """
        if attr is None or not hasattr(attr, "data"):
            return None

        data_seq = attr.data
        if len(data_seq) < min_elements:
            return None

        try:
            first_elem = data_seq[0]
            return safe_as_pointer(first_elem, required_align=required_align)
        except (IndexError, AttributeError, RuntimeError) as e:
            logger.debug("Failed to resolve attribute pointer: %s", e)
            return None

    def resolve_positions_ptr(
        self, mesh: Any, expected_count: Optional[int] = None
    ) -> Optional[int]:
        """Resolves pointer for the vertex 'position' attribute layer."""
        if mesh is None or not hasattr(mesh, "attributes"):
            return None

        pos_attr = mesh.attributes.get("position")
        if pos_attr is not None:
            if expected_count is None or len(pos_attr.data) == expected_count:
                ptr = self.resolve_attribute_ptr(pos_attr)
                if ptr is not None:
                    return ptr

        # Fallback to legacy vertices array if attributes['position'] resolution fails
        if hasattr(mesh, "vertices") and len(mesh.vertices) > 0:
            if expected_count is None or len(mesh.vertices) == expected_count:
                return safe_as_pointer(mesh.vertices[0])

        return None

    def resolve_corner_verts_ptr(
        self, mesh: Any, expected_count: Optional[int] = None
    ) -> Optional[int]:
        """Resolves pointer for the '.corner_vert' loop attribute layer."""
        if mesh is None or not hasattr(mesh, "attributes"):
            return None

        cvert_attr = mesh.attributes.get(".corner_vert")
        if cvert_attr is not None:
            if expected_count is None or len(cvert_attr.data) == expected_count:
                return self.resolve_attribute_ptr(cvert_attr)

        return None

    def resolve_loop_uvs_ptr(
        self,
        mesh: Any,
        uv_name: Optional[str] = None,
        expected_count: Optional[int] = None,
    ) -> Optional[int]:
        """Resolves pointer for the active or named Loop UV layer."""
        if mesh is None or not hasattr(mesh, "attributes"):
            return None

        target_name = uv_name
        if target_name is None:
            if hasattr(mesh, "uv_layers") and mesh.uv_layers.active:
                target_name = mesh.uv_layers.active.name
            else:
                target_name = "UVMap"

        uv_attr = mesh.attributes.get(target_name)
        if uv_attr is not None:
            if expected_count is None or len(uv_attr.data) == expected_count:
                return self.resolve_attribute_ptr(uv_attr)

        return None

    def resolve_materials_ptr(
        self, mesh: Any, expected_count: Optional[int] = None
    ) -> Optional[int]:
        """
        Polygon material indices are intentionally deferred to Phase 2 standard BPy foreach_set.
        Prevents CustomData corruption and ensures cross-version stability.
        """
        return None

    def resolve_colors_ptr(
        self,
        mesh: Any,
        color_name: Optional[str] = None,
        expected_count: Optional[int] = None,
    ) -> Optional[int]:
        """Resolves pointer for the active or named color attribute layer."""
        if mesh is None or not hasattr(mesh, "color_attributes"):
            return None

        # Verify mesh actually has dedicated color attributes (avoid aliasing 'position')
        if len(mesh.color_attributes) == 0:
            return None

        col_attr = None
        if color_name is not None:
            col_attr = mesh.color_attributes.get(color_name)
        else:
            active_col = mesh.color_attributes.active
            if active_col is not None and getattr(active_col, "name", "") in mesh.color_attributes:
                col_attr = active_col
            elif len(mesh.color_attributes) > 0:
                col_attr = mesh.color_attributes[0]

        if col_attr is not None and getattr(col_attr, "data_type", "") in ("FLOAT_COLOR", "BYTE_COLOR"):
            if expected_count is None or len(col_attr.data) == expected_count:
                return self.resolve_attribute_ptr(col_attr)

        return None

    def resolve_point_cloud_ptrs(
        self, cloud_data: Any, expected_count: Optional[int] = None
    ) -> Dict[str, Optional[int]]:
        """Resolves pointers for standard voxel point cloud attributes."""
        res: Dict[str, Optional[int]] = {
            "pos_ptr": None,
            "block_x_ptr": None,
            "block_y_ptr": None,
            "block_z_ptr": None,
            "state_idx_ptr": None,
            "biome_idx_ptr": None,
            "entity_idx_ptr": None,
            "light_ptr": None,
        }
        if cloud_data is None or not hasattr(cloud_data, "attributes"):
            return res

        attrs = cloud_data.attributes
        mapping = {
            "pos_ptr": ("position",),
            "block_x_ptr": ("mtk_block_x", "block_x"),
            "block_y_ptr": ("mtk_block_y", "block_y"),
            "block_z_ptr": ("mtk_block_z", "block_z"),
            "state_idx_ptr": ("mtk_state_idx", "state_index"),
            "biome_idx_ptr": ("mtk_biome_idx", "biome_index"),
            "entity_idx_ptr": ("mtk_entity_idx", "entity_index"),
            "light_ptr": ("mtk_light", "light_level"),
        }

        for out_key, candidates in mapping.items():
            for attr_name in candidates:
                attr = attrs.get(attr_name)
                if attr is not None:
                    if expected_count is None or len(attr.data) == expected_count:
                        res[out_key] = self.resolve_attribute_ptr(attr)
                        break

        return res

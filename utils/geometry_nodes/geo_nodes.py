"""Geometry Nodes World Tree Builder for Yefira Blender Plugin.

This module acts as a facade forwarding to `world_tree.py` and `groups/`
to maintain 100% backward compatibility for imports across the plugin.
"""

from __future__ import annotations

from .core import (
    ensure_socket,
    ensure_gn_group,
    finalize_group,
    prune_unlinked_nodes as _prune_unlinked_nodes,
)
from .groups import (
    get_or_create_face_selector_vector_group,
    get_or_create_face_selector_int_group,
    get_or_create_face_selector_color_group,
    get_or_create_atlas_uv_calculator_group,
    get_or_create_cube_surface_group,
    get_or_create_instance_attribute_transfer_group,
    GROUP_NAME_FACE_SELECTOR_VECTOR,
    GROUP_NAME_FACE_SELECTOR_INT,
    GROUP_NAME_FACE_SELECTOR_COLOR,
    GROUP_NAME_ATLAS_UV_CALCULATOR,
    GROUP_NAME_CUBE_SURFACE,
    GROUP_NAME_INSTANCE_ATTRIBUTES,
)
from .world_tree import (
    setup_world_geometry_nodes,
    WORLD_TREE_NAME,
    WORLD_MODIFIER_NAME,
    WORLD_TREE_SCHEMA_VERSION,
    WORLD_TREE_SCHEMA_PROPERTY,
    _update_tree_bindings,
    _remove_legacy_atlas_inputs,
    _create_world_geometry_node_tree,
    _build_tree_nodes_and_links,
)

# Backwards compatibility alias for _ensure_socket
_ensure_socket = ensure_socket

__all__ = (
    "setup_world_geometry_nodes",
    "WORLD_TREE_NAME",
    "WORLD_MODIFIER_NAME",
    "WORLD_TREE_SCHEMA_VERSION",
    "WORLD_TREE_SCHEMA_PROPERTY",
    "get_or_create_face_selector_vector_group",
    "get_or_create_face_selector_int_group",
    "get_or_create_face_selector_color_group",
    "get_or_create_atlas_uv_calculator_group",
    "get_or_create_cube_surface_group",
    "get_or_create_instance_attribute_transfer_group",
    "ensure_socket",
    "_ensure_socket",
    "_update_tree_bindings",
    "_remove_legacy_atlas_inputs",
    "_create_world_geometry_node_tree",
    "_build_tree_nodes_and_links",
    "_prune_unlinked_nodes",
)

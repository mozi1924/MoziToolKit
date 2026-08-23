"""
MoziToolKit Geometry Nodes World Engine.
Provides modular Geometry Node generators for procedural point-cloud Minecraft world instancing.
"""

from .core import (
    ensure_gn_group,
    ensure_socket,
    finalize_group,
    prune_unlinked_nodes,
)
from .groups import (
    GROUP_NAME_ATLAS_UV_CALCULATOR,
    GROUP_NAME_CUBE_SURFACE,
    GROUP_NAME_CULLING_MERGE,
    GROUP_NAME_FACE_SELECTOR_COLOR,
    GROUP_NAME_FACE_SELECTOR_FLOAT,
    GROUP_NAME_FACE_SELECTOR_INT,
    GROUP_NAME_FACE_SELECTOR_VECTOR,
    GROUP_NAME_INSTANCE_ATTRIBUTES,
    GROUP_NAME_MATERIAL_DISPATCHER,
    get_or_create_atlas_uv_calculator_group,
    get_or_create_cube_surface_group,
    get_or_create_culling_merge_group,
    get_or_create_face_selector_color_group,
    get_or_create_face_selector_float_group,
    get_or_create_face_selector_int_group,
    get_or_create_face_selector_vector_group,
    get_or_create_instance_attribute_transfer_group,
    get_or_create_material_dispatcher_group,
)
from .world_tree import (
    WORLD_MODIFIER_NAME,
    WORLD_TREE_NAME,
    WORLD_TREE_SCHEMA_PROPERTY,
    WORLD_TREE_SCHEMA_VERSION,
    setup_world_geometry_nodes,
)

__all__ = (
    "setup_world_geometry_nodes",
    "WORLD_TREE_NAME",
    "WORLD_MODIFIER_NAME",
    "WORLD_TREE_SCHEMA_VERSION",
    "WORLD_TREE_SCHEMA_PROPERTY",
    "ensure_socket",
    "ensure_gn_group",
    "finalize_group",
    "prune_unlinked_nodes",
    "get_or_create_cube_surface_group",
    "get_or_create_instance_attribute_transfer_group",
    "get_or_create_face_selector_vector_group",
    "get_or_create_face_selector_int_group",
    "get_or_create_face_selector_color_group",
    "get_or_create_face_selector_float_group",
    "get_or_create_atlas_uv_calculator_group",
    "get_or_create_material_dispatcher_group",
    "get_or_create_culling_merge_group",
    "GROUP_NAME_CUBE_SURFACE",
    "GROUP_NAME_INSTANCE_ATTRIBUTES",
    "GROUP_NAME_FACE_SELECTOR_VECTOR",
    "GROUP_NAME_FACE_SELECTOR_INT",
    "GROUP_NAME_FACE_SELECTOR_COLOR",
    "GROUP_NAME_FACE_SELECTOR_FLOAT",
    "GROUP_NAME_ATLAS_UV_CALCULATOR",
    "GROUP_NAME_MATERIAL_DISPATCHER",
    "GROUP_NAME_CULLING_MERGE",
)

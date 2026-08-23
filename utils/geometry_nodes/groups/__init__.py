"""Atomic Geometry Node groups for procedural Minecraft world construction."""

from .atlas_uv import (
    GROUP_NAME_ATLAS_UV_CALCULATOR,
    get_or_create_atlas_uv_calculator_group,
)
from .cube_surface import (
    GROUP_NAME_CUBE_SURFACE,
    get_or_create_cube_surface_group,
)
from .culling_merge import (
    GROUP_NAME_CULLING_MERGE,
    get_or_create_culling_merge_group,
)
from .face_selectors import (
    GROUP_NAME_FACE_SELECTOR_COLOR,
    GROUP_NAME_FACE_SELECTOR_FLOAT,
    GROUP_NAME_FACE_SELECTOR_INT,
    GROUP_NAME_FACE_SELECTOR_VECTOR,
    get_or_create_face_selector_color_group,
    get_or_create_face_selector_float_group,
    get_or_create_face_selector_int_group,
    get_or_create_face_selector_vector_group,
)
from .instance_attributes import (
    GROUP_NAME_INSTANCE_ATTRIBUTES,
    get_or_create_instance_attribute_transfer_group,
)
from .material_dispatcher import (
    GROUP_NAME_MATERIAL_DISPATCHER,
    get_or_create_material_dispatcher_group,
)

__all__ = (
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

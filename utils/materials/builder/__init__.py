"""
Material Builders for MoziToolKit.
"""

from .atlas_builder import build_atlas_chunk_material
from .pbr_graph import build_pbr_shading
from .layout import NodeLayoutEngine, auto_layout_material
from .template import (
    clone_atlas_chunk_material,
    find_archetype_material,
    get_template_key,
    register_archetype_material,
)
from .image_utils import (
    get_or_create_image,
    get_or_create_image_from_rgba,
    get_or_create_image_from_f32,
    set_material_displacement_method,
    ensure_material_node_tree,
)
from .dynamic_entities import (
    DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID,
    build_dynamic_entities_material,
    update_dynamic_entities_image,
)

__all__ = [
    "build_atlas_chunk_material",
    "build_pbr_shading",
    "NodeLayoutEngine",
    "auto_layout_material",
    "clone_atlas_chunk_material",
    "find_archetype_material",
    "get_template_key",
    "register_archetype_material",
    "get_or_create_image",
    "get_or_create_image_from_rgba",
    "get_or_create_image_from_f32",
    "set_material_displacement_method",
    "ensure_material_node_tree",
    "DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID",
    "build_dynamic_entities_material",
    "update_dynamic_entities_image",
]


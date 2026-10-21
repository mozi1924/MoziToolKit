"""
Material Builders for MoziToolKit.
"""

from .atlas_builder import build_atlas_chunk_material
from .pbr_graph import build_pbr_shading
from .image_utils import (
    get_or_create_image,
    get_or_create_image_from_rgba,
    get_or_create_image_from_f32,
    set_material_displacement_method,
    ensure_material_node_tree,
)
from .adaptation import (
    update_materials_render_engine_adaptation,
    register_render_engine_adaptation_handlers,
    unregister_render_engine_adaptation_handlers,
)

__all__ = [
    "build_atlas_chunk_material",
    "build_pbr_shading",
    "get_or_create_image",
    "get_or_create_image_from_rgba",
    "get_or_create_image_from_f32",
    "set_material_displacement_method",
    "ensure_material_node_tree",
    "update_materials_render_engine_adaptation",
    "register_render_engine_adaptation_handlers",
    "unregister_render_engine_adaptation_handlers",
]


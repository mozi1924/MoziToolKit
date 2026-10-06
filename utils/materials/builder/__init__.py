"""
Material Builders for MoziToolKit.
"""

from .atlas_builder import build_atlas_chunk_material
from .standalone_builder import (
    build_standalone_material,
    get_or_create_image,
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
    "build_standalone_material",
    "get_or_create_image",
    "set_material_displacement_method",
    "ensure_material_node_tree",
    "update_materials_render_engine_adaptation",
    "register_render_engine_adaptation_handlers",
    "unregister_render_engine_adaptation_handlers",
]


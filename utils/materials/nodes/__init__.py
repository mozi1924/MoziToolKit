"""
Shader node tree construction, Principled BSDF channel wiring, and interpolation.
"""

from .builder import (
    load_image_texture,
    set_material_displacement_method,
    build_channel_nodes,
    rebuild_material,
    inspect_material_nodes,
    repair_material_nodes,
)

from .interpolation import (
    set_materials_texture_interpolation_closest,
    process_node_tree_interpolation,
)

__all__ = [
    "load_image_texture",
    "set_material_displacement_method",
    "build_channel_nodes",
    "rebuild_material",
    "inspect_material_nodes",
    "repair_material_nodes",
    "set_materials_texture_interpolation_closest",
    "process_node_tree_interpolation",
]

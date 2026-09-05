"""
Shader node tree construction, Principled BSDF channel wiring, and interpolation.
"""

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

if HAS_BPY:
    from .builder import (
        load_image_texture,
        set_material_displacement_method,
        build_channel_nodes,
        build_material_from_descriptor,
        rebuild_material,
        inspect_material_nodes,
        repair_material_nodes,
    )

    from .interpolation import (
        set_materials_texture_interpolation_closest,
        process_node_tree_interpolation,
    )
else:
    load_image_texture = None
    set_material_displacement_method = None
    build_channel_nodes = None
    build_material_from_descriptor = None
    rebuild_material = None
    inspect_material_nodes = None
    repair_material_nodes = None
    set_materials_texture_interpolation_closest = None
    process_node_tree_interpolation = None

__all__ = [
    "load_image_texture",
    "set_material_displacement_method",
    "build_channel_nodes",
    "build_material_from_descriptor",
    "rebuild_material",
    "inspect_material_nodes",
    "repair_material_nodes",
    "set_materials_texture_interpolation_closest",
    "process_node_tree_interpolation",
]

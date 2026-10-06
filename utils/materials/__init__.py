"""
Materials utilities package.
"""

from .builder import build_atlas_chunk_material, build_standalone_material
from .pipeline import replace_materials, restore_materials_from_provenance
try:
    from ...bridge.material import (
        is_transmissive_block,
        get_block_transmission_weight,
        get_block_sticker_threshold,
        is_thin_wall_block,
        get_block_emission_strength,
        get_material_props,
        compute_mesh_material_props,
        compute_flat_material_props,
    )
except (ImportError, ValueError):
    from bridge.material import (
        is_transmissive_block,
        get_block_transmission_weight,
        get_block_sticker_threshold,
        is_thin_wall_block,
        get_block_emission_strength,
        get_material_props,
        compute_mesh_material_props,
        compute_flat_material_props,
    )

__all__ = [
    "build_atlas_chunk_material",
    "build_standalone_material",
    "replace_materials",
    "restore_materials_from_provenance",
    "is_transmissive_block",
    "get_block_transmission_weight",
    "get_block_sticker_threshold",
    "is_thin_wall_block",
    "get_block_emission_strength",
    "get_material_props",
    "compute_mesh_material_props",
    "compute_flat_material_props",
]

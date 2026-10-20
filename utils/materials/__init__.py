"""
Materials utilities package.
"""

from .builder import build_atlas_chunk_material
from .pipeline import replace_materials, restore_materials_from_provenance
from .properties_config import (
    get_default_material_properties_path,
    load_material_properties_config,
    reset_material_properties_config,
)
try:
    from ...bridge.material import (
        is_transmissive_block,
        get_block_transmission_weight,
        get_block_sticker_threshold,
        is_thin_wall_block,
        get_block_emission_strength,
        get_material_props,
    )
except (ImportError, ValueError):
    from bridge.material import (
        is_transmissive_block,
        get_block_transmission_weight,
        get_block_sticker_threshold,
        is_thin_wall_block,
        get_block_emission_strength,
        get_material_props,
    )

__all__ = [
    "build_atlas_chunk_material",
    "replace_materials",
    "restore_materials_from_provenance",
    "is_transmissive_block",
    "get_block_transmission_weight",
    "get_block_sticker_threshold",
    "is_thin_wall_block",
    "get_block_emission_strength",
    "get_material_props",
    "get_default_material_properties_path",
    "load_material_properties_config",
    "reset_material_properties_config",
]

"""
Material matching presets package.
"""

from .registry import (
    build_matching_context,
    build_material_alias_map,
    detect_material_origin,
    generate_candidates_for_name,
)
from .ice_cube import expand_ice_cube_candidates, is_ice_cube_internal_face
from .jmc2obj import expand_jmc2obj_candidates
from .mineways import build_mineways_grid_spec, expand_mineways_candidates
from .mineways_table import (
    MINEWAYS_ATLAS_NAME_PATTERNS,
    MINEWAYS_ATLAS_SUFFIX_PATTERNS,
    MINEWAYS_TILES_TABLE,
)

__all__ = [
    "build_matching_context",
    "build_material_alias_map",
    "detect_material_origin",
    "generate_candidates_for_name",
    "expand_ice_cube_candidates",
    "is_ice_cube_internal_face",
    "expand_jmc2obj_candidates",
    "expand_mineways_candidates",
    "build_mineways_grid_spec",
    "MINEWAYS_ATLAS_NAME_PATTERNS",
    "MINEWAYS_ATLAS_SUFFIX_PATTERNS",
    "MINEWAYS_TILES_TABLE",
]

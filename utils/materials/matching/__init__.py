"""
Material matching package.
"""

from .presets import (
    build_matching_context,
    build_material_alias_map,
    build_mineways_grid_spec,
    detect_material_origin,
    generate_candidates_for_name,
)

__all__ = [
    "build_matching_context",
    "build_material_alias_map",
    "build_mineways_grid_spec",
    "detect_material_origin",
    "generate_candidates_for_name",
]

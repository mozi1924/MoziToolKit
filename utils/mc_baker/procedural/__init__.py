"""
Minecraft Baker Procedural Models Submodule.
Provides pure-code 3D geometry and UV generators for Minecraft blocks without static JSON elements.
"""

from .common import make_box_element, get_facing_angle_y
from .chest import build_chest_elements, get_chest_texture_stem
from .shulker_box import build_shulker_box_elements, get_shulker_texture
from .banner import build_banner_elements
from .bed import build_bed_elements
from .skull import build_skull_elements, get_skull_texture
from .conduit import build_conduit_elements
from .decorated_pot import build_decorated_pot_elements
from .bell import build_bell_elements
from .end_portal import build_end_portal_elements
from .registry import (
    get_procedural_elements,
    is_chest_block,
    is_shulker_block,
    is_banner_block,
    is_bed_block,
    is_skull_block,
)

__all__ = [
    "make_box_element",
    "get_facing_angle_y",
    "build_chest_elements",
    "get_chest_texture_stem",
    "build_shulker_box_elements",
    "get_shulker_texture",
    "build_banner_elements",
    "build_bed_elements",
    "build_skull_elements",
    "get_skull_texture",
    "build_conduit_elements",
    "build_decorated_pot_elements",
    "build_bell_elements",
    "build_end_portal_elements",
    "get_procedural_elements",
    "is_chest_block",
    "is_shulker_block",
    "is_banner_block",
    "is_bed_block",
    "is_skull_block",
]

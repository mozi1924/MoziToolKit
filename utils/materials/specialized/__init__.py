"""
Specialized block material and geometry handlers for unique Minecraft blocks.
Isolated from core pipelines for high discoverability and zero-clutter maintenance.
"""

from .firefly_bush import (
    is_firefly_bush,
    sanitize_firefly_bush_elements,
    synthesize_firefly_bush_textures,
    is_firefly_bush_tint_exempt,
    handle_firefly_bush_texture_info,
    handle_firefly_bush_composite_map,
)

__all__ = [
    "is_firefly_bush",
    "sanitize_firefly_bush_elements",
    "synthesize_firefly_bush_textures",
    "is_firefly_bush_tint_exempt",
    "handle_firefly_bush_texture_info",
    "handle_firefly_bush_composite_map",
]

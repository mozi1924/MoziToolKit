"""
Standalone per-texture Material generation, channel alignment, and replacement engine.
"""

from .generator import (
    StandaloneGenerator,
    STANDALONE_FORMAT_VERSION,
)

from .aligner import (
    align_standalone_textures,
    is_channel_animated,
)

from .pipeline import (
    StandaloneReplacementEngine,
)

__all__ = [
    "StandaloneGenerator",
    "STANDALONE_FORMAT_VERSION",
    "align_standalone_textures",
    "is_channel_animated",
    "StandaloneReplacementEngine",
]

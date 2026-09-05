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

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

if HAS_BPY:
    from .pipeline import (
        StandaloneReplacementEngine,
    )
else:
    StandaloneReplacementEngine = None

__all__ = [
    "StandaloneGenerator",
    "STANDALONE_FORMAT_VERSION",
    "align_standalone_textures",
    "is_channel_animated",
    "StandaloneReplacementEngine",
]

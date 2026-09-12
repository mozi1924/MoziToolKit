"""
Standalone per-texture Material generation, channel alignment, and replacement engine.
"""

STANDALONE_FORMAT_VERSION = 1

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
    "STANDALONE_FORMAT_VERSION",
    "StandaloneReplacementEngine",
]

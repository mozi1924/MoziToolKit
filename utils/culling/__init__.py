"""
Unified Face Culling System for MoziToolKit.
Replicates Minecraft 1.21+ canonical Block.shouldRenderFace and BlockBehaviour.skipRendering rules.
"""

from __future__ import annotations

from .types import (
    CullCategory,
    LeavesCullMode,
    GlassCullMode,
    FaceOcclusionRect,
    BlockCullMeta,
    FULL_FACE_RECT,
    EMPTY_FACE_RECT,
    DIR_TO_MASK,
    OPPOSITE_DIR,
)
from .shapes import (
    subtract_rect,
    is_face_completely_occluded,
    extract_face_occlusion_from_elements,
)
from .rules import should_skip_rendering
from .engine import (
    FaceCuller,
    get_shared_face_culler,
)

__all__ = [
    "CullCategory",
    "LeavesCullMode",
    "GlassCullMode",
    "FaceOcclusionRect",
    "BlockCullMeta",
    "FULL_FACE_RECT",
    "EMPTY_FACE_RECT",
    "DIR_TO_MASK",
    "OPPOSITE_DIR",
    "subtract_rect",
    "is_face_completely_occluded",
    "extract_face_occlusion_from_elements",
    "should_skip_rendering",
    "FaceCuller",
    "get_shared_face_culler",
]

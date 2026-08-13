"""Composable shader-node group templates used by the material builder."""

from .animated import (
    ensure_animated_frame_blend,
    ensure_animated_uv_mapping,
    ensure_animation_scheduler,
)

__all__ = (
    "ensure_animated_frame_blend",
    "ensure_animated_uv_mapping",
    "ensure_animation_scheduler",
)

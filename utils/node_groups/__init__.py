"""Composable shader-node group templates used by the material builder."""

try:
    from .animated import (
        ensure_animated_frame_blend,
        ensure_animated_uv_mapping,
        ensure_animation_scheduler,
    )
    from .atlas_uv_tiling import ensure_atlas_uv_tiling
    from .labpbr import LABPBR_GROUP_NAME, LABPBR_TEMPLATE_VERSION, ensure_labpbr_decoder

    def ensure_all_templates():
        """Return every reusable shader-node template needed by materials."""
        return {
            "LabPBR 1.3 Decoder": ensure_labpbr_decoder(),
            "MC_Animated_UV_Mapping": ensure_animated_uv_mapping(),
            "MC_Animation_Scheduler_Default": ensure_animation_scheduler(),
            "MC_Animated_Frame_Blend": ensure_animated_frame_blend(),
            "MC_Atlas_UV_Tiling": ensure_atlas_uv_tiling(),
        }
except ImportError:
    pass


__all__ = (
    "ensure_all_templates",
    "ensure_animated_frame_blend",
    "ensure_animated_uv_mapping",
    "ensure_animation_scheduler",
    "ensure_atlas_uv_tiling",
    "LABPBR_GROUP_NAME",
    "LABPBR_TEMPLATE_VERSION",
    "ensure_labpbr_decoder",
)



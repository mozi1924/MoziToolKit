"""Composable shader-node group templates used by the material builder."""

try:
    from .animated import (
        ensure_animated_frame_blend,
        ensure_animated_uv_mapping,
        ensure_animation_scheduler,
    )
    from .atlas_uv_decoder import build_atlas_uv_decoder_node_group
    from .atlas_uv_tiling import ensure_atlas_uv_tiling
    from .biome import ensure_biome_tint, ensure_colormap_sampler, ensure_colormap_decoder
    from .labpbr import LABPBR_GROUP_NAME, LABPBR_TEMPLATE_VERSION, ensure_labpbr_decoder
    from .parallax import ensure_parallax_uv_offset

    def ensure_all_templates():
        """Return every reusable shader-node template needed by materials."""
        return {
            "LabPBR 1.3 Decoder": ensure_labpbr_decoder(),
            "MC_Animated_UV_Mapping": ensure_animated_uv_mapping(),
            "MC_Animation_Scheduler_Default": ensure_animation_scheduler(),
            "MC_Animated_Frame_Blend": ensure_animated_frame_blend(),
            "MC_Atlas_UV_Decoder": build_atlas_uv_decoder_node_group(),
            "MC_Atlas_UV_Tiling": ensure_atlas_uv_tiling(),
            "MC_Biome_Tint": ensure_biome_tint(),
            "MC_Biome_Colormap_Sampler": ensure_colormap_sampler(),
            "MC_Biome_Colormap_Decoder": ensure_colormap_decoder(),
            "MC_Parallax_UV_Offset": ensure_parallax_uv_offset(),
        }
except ImportError:
    pass


__all__ = (
    "build_atlas_uv_decoder_node_group",
    "ensure_all_templates",
    "ensure_animated_frame_blend",
    "ensure_animated_uv_mapping",
    "ensure_animation_scheduler",
    "ensure_atlas_uv_tiling",
    "ensure_biome_tint",
    "ensure_colormap_sampler",
    "ensure_colormap_decoder",
    "ensure_parallax_uv_offset",
    "LABPBR_GROUP_NAME",
    "LABPBR_TEMPLATE_VERSION",
    "ensure_labpbr_decoder",
)




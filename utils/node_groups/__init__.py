"""Composable shader-node group templates used by the material builder."""

try:
    from .animated import (
        ensure_animated_frame_blend,
        ensure_animated_normal_blend,
        ensure_animated_specular_blend,
        ensure_animated_pbr_blend,
        ensure_animated_uv_mapping,
        ensure_animation_scheduler,
    )
    from .atlas_uv_decoder import build_atlas_uv_decoder_node_group
    from .atlas_uv_tiling import ensure_atlas_uv_tiling
    from .biome import ensure_biome_tint
    from .parallax import ensure_parallax_uv_offset

    def ensure_all_templates():
        """Return every reusable shader-node template needed by materials."""
        return {
            "MC_Animated_UV_Mapping": ensure_animated_uv_mapping(),
            "MC_Animation_Scheduler_Default": ensure_animation_scheduler(),
            "MC_Animated_Frame_Blend": ensure_animated_frame_blend(),
            "MC_Animated_Normal_Blend": ensure_animated_normal_blend(),
            "MC_Animated_Specular_Blend": ensure_animated_specular_blend(),
            "MC_Animated_PBR_Blend": ensure_animated_pbr_blend(),
            "MC_Atlas_UV_Decoder": build_atlas_uv_decoder_node_group(),
            "MC_Atlas_UV_Tiling": ensure_atlas_uv_tiling(),
            "MC_Biome_Tint": ensure_biome_tint(),
            "MC_Parallax_UV_Offset": ensure_parallax_uv_offset(),
        }
except ImportError:
    pass


__all__ = (
    "build_atlas_uv_decoder_node_group",
    "ensure_all_templates",
    "ensure_animated_frame_blend",
    "ensure_animated_normal_blend",
    "ensure_animated_specular_blend",
    "ensure_animated_pbr_blend",
    "ensure_animated_uv_mapping",
    "ensure_animation_scheduler",
    "ensure_atlas_uv_tiling",
    "ensure_biome_tint",
    "ensure_parallax_uv_offset",
)




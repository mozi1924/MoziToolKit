"""
UV area, pixel resolution, and collapse detection utilities for extrusion repair.
"""

from __future__ import annotations

from typing import Tuple, Optional
try:
    import bpy
except ImportError:
    bpy = None



def get_face_pixel_step(
    face,
    obj=None,
    context=None,
    uv_layer=None,
    default_res: Tuple[int, int] = (64, 64),
) -> Tuple[float, float]:
    """Retrieve anisotropic 2D UV step (step_u, step_v) for 1 pixel on a face's texture.

    Supports:
    - ATLAS_UNIFIED (Local UVs corresponding to tile_size)
    - ATLAS_CHUNK (Baked Atlas UVs or Local UVs)
    - STANDALONE_BAKED (Animated strips with baked UVs)
    - STANDALONE / GENERIC (Non-square or square single textures)
    """
    active_obj = obj or (bpy.context.active_object if bpy and hasattr(bpy, "context") else None)

    if active_obj is not None:
        try:
            if hasattr(face, "material_index") and face.material_index < len(active_obj.material_slots):
                mat = active_obj.material_slots[face.material_index].material
                if mat and mat.use_nodes and mat.node_tree:
                    decoder_node = next(
                        (
                            n for n in mat.node_tree.nodes
                            if (n.type == "GROUP" and n.node_tree and "Atlas_UV_Decoder" in n.node_tree.name)
                            or n.name == "MC Atlas UV Decoder"
                        ),
                        None
                    )
                    if decoder_node and "Tile Size" in decoder_node.inputs:
                        ts = int(round(decoder_node.inputs["Tile Size"].default_value))
                        if ts > 0:
                            return (1.0 / ts, 1.0 / ts)

                    for n in mat.node_tree.nodes:
                        if n.type == "TEX_IMAGE" and n.image and n.image.size[0] > 0 and n.image.size[1] > 0:
                            raw_w, raw_h = int(n.image.size[0]), int(n.image.size[1])
                            if raw_h > raw_w and raw_h % raw_w == 0:
                                return (1.0 / max(1, raw_w), 1.0 / max(1, raw_w))
                            return (1.0 / max(1, raw_w), 1.0 / max(1, raw_h))
        except Exception:
            pass

    return (1.0 / float(default_res[0]), 1.0 / float(default_res[1]))


def get_active_texture_pixel_step(obj=None) -> float:
    """Legacy helper: Retrieve scalar UV step for active object's material."""
    return 1.0 / 64.0

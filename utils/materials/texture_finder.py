"""
Robust Albedo / Base Color texture image locator for materials and faces.
"""

from __future__ import annotations

import sys
from typing import Optional
import bpy


def find_albedo_image_from_material(mat: bpy.types.Material | None) -> Optional[bpy.types.Image]:
    """Search for the primary Albedo / Base Color Image datablock in a material node tree.

    Detection priority:
    1. TEX_IMAGE nodes explicitly named with 'albedo' (case-insensitive)
    2. TEX_IMAGE nodes linked into LabPBR Decoder ('Albedo Color'), Principled BSDF ('Base Color', 'Color'), or Frame Blend
    3. Active TEX_IMAGE node
    4. First valid TEX_IMAGE node with an assigned image
    """
    if not mat or not mat.use_nodes or not mat.node_tree:
        return None

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # 1. Prioritize nodes explicitly named Albedo
    for node in nodes:
        if node.type == "TEX_IMAGE" and node.image and "albedo" in node.name.lower():
            return node.image

    # 2. Check nodes linked into standard color sockets or blend groups
    for link in links:
        if link.to_socket and link.to_socket.name in ("Albedo Color", "Base Color", "Color"):
            if link.from_node and link.from_node.type == "TEX_IMAGE" and link.from_node.image:
                return link.from_node.image
            # If coming from Frame Blend group
            if (
                link.from_node
                and link.from_node.type == "GROUP"
                and link.from_node.node_tree
                and "Blend" in link.from_node.node_tree.name
            ):
                for b_link in links:
                    if (
                        b_link.to_node == link.from_node
                        and b_link.from_node
                        and b_link.from_node.type == "TEX_IMAGE"
                        and b_link.from_node.image
                    ):
                        return b_link.from_node.image

    # 3. Check active TEX_IMAGE node
    if nodes.active and nodes.active.type == "TEX_IMAGE" and nodes.active.image:
        return nodes.active.image

    # 4. Fallback to any TEX_IMAGE node with an image
    for node in nodes:
        if node.type == "TEX_IMAGE" and node.image:
            return node.image

    return None


def find_face_image(face, obj, context=None) -> Optional[bpy.types.Image]:
    """Find the Image object associated with a mesh face or active workspace context."""
    # 1. Try face's material
    if obj and obj.material_slots and face.material_index < len(obj.material_slots):
        mat = obj.material_slots[face.material_index].material
        img = find_albedo_image_from_material(mat)
        if img:
            return img

    # 2. Try Image Editor active image
    if context and hasattr(context, "space_data") and context.space_data and context.space_data.type == "IMAGE_EDITOR":
        if context.space_data.image:
            return context.space_data.image

    # 3. Fallback to first valid image in bpy.data.images
    if bpy and hasattr(bpy, "data"):
        for img in bpy.data.images:
            if img.source != "VIEWER" and img.size[0] > 0 and img.size[1] > 0:
                print(
                    f"[MoziToolKit] Face material has no image texture. Falling back to bpy.data.images: {img.name}",
                    file=sys.stderr,
                )
                return img

    return None


def get_material_pixel_step(mat: bpy.types.Material | None, default_size: int = 64) -> float:
    """Calculate the UV step corresponding to 1 pixel based on a material's albedo image."""
    img = find_albedo_image_from_material(mat)
    if img and img.size[0] > 0:
        return 1.0 / float(img.size[0])
    return 1.0 / float(max(1, default_size))

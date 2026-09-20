"""
Texture and Image lookup helpers for mesh faces and materials.
"""

from __future__ import annotations

from typing import Optional

try:
    import bpy
except ImportError:
    bpy = None


def find_albedo_image_from_material(mat) -> Optional[bpy.types.Image]:
    """Search for the primary Albedo / Base Color Image datablock in a material node tree."""
    if not mat or not getattr(mat, "use_nodes", False) or not mat.node_tree:
        return None

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # 1. Prioritize nodes explicitly named Albedo
    for node in nodes:
        if node.type == "TEX_IMAGE" and getattr(node, "image", None) and "albedo" in node.name.lower():
            return node.image

    # 2. Check nodes linked into standard color sockets or blend groups
    for link in links:
        if link.to_socket and link.to_socket.name in ("Albedo Color", "Base Color", "Color"):
            if link.from_node and link.from_node.type == "TEX_IMAGE" and getattr(link.from_node, "image", None):
                return link.from_node.image
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
                        and getattr(b_link.from_node, "image", None)
                    ):
                        return b_link.from_node.image

    # 3. Check active TEX_IMAGE node
    if nodes.active and nodes.active.type == "TEX_IMAGE" and getattr(nodes.active, "image", None):
        return nodes.active.image

    # 4. Fallback to any TEX_IMAGE node with an image
    for node in nodes:
        if node.type == "TEX_IMAGE" and getattr(node, "image", None):
            return node.image

    return None


def find_face_image(face, obj, context=None) -> Optional[bpy.types.Image]:
    """Find the Image object associated with a mesh face or active workspace context."""
    if obj and hasattr(obj, "material_slots") and face.material_index < len(obj.material_slots):
        mat = obj.material_slots[face.material_index].material
        img = find_albedo_image_from_material(mat)
        if img:
            return img

    if context and hasattr(context, "space_data") and context.space_data and getattr(context.space_data, "type", None) == "IMAGE_EDITOR":
        if getattr(context.space_data, "image", None):
            return context.space_data.image

    return None

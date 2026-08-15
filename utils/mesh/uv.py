"""
UV bounds, center calculations, and face image resolution.
"""

from dataclasses import dataclass
import sys
try:
    import bpy
    from mathutils import Vector
except ImportError:
    bpy = None
    Vector = None


@dataclass
class UVBounds:
    """Bounding box of UV coordinates for a face or group of faces."""
    min_u: float
    max_u: float
    min_v: float
    max_v: float

    @property
    def width(self) -> float:
        return self.max_u - self.min_u

    @property
    def height(self) -> float:
        return self.max_v - self.min_v


def get_face_uv_bounds(face, uv_layer) -> UVBounds:
    """Calculate min/max UV coordinates for a face."""
    if not face.loops:
        return UVBounds(0.0, 0.0, 0.0, 0.0)

    u_coords = [loop[uv_layer].uv.x for loop in face.loops]
    v_coords = [loop[uv_layer].uv.y for loop in face.loops]

    return UVBounds(
        min_u=min(u_coords),
        max_u=max(u_coords),
        min_v=min(v_coords),
        max_v=max(v_coords),
    )


def get_face_uv_center(face, uv_layer) -> Vector:
    """Calculate geometric center vector of a face's UV loop coordinates."""
    if not face.loops:
        return Vector((0.0, 0.0))

    uv_center = Vector((0.0, 0.0))
    for loop in face.loops:
        uv_center += loop[uv_layer].uv
    uv_center /= len(face.loops)
    return uv_center


def get_image_from_face(face, obj, context):
    """Find the Image object associated with a bmesh face."""
    # 1. Try face's material
    if face.material_index < len(obj.material_slots):
        mat = obj.material_slots[face.material_index].material
        if mat and mat.use_nodes:
            # Active node check
            active_node = mat.node_tree.nodes.active
            if active_node and active_node.type == "TEX_IMAGE" and active_node.image:
                return active_node.image

            # Find first Image Texture node with an image
            for node in mat.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image:
                    return node.image

    # 2. Try Image Editor active image
    if hasattr(context, "space_data") and context.space_data and context.space_data.type == "IMAGE_EDITOR":
        if context.space_data.image:
            return context.space_data.image

    # 3. Fallback to first image in bpy.data.images
    for img in bpy.data.images:
        if img.source != "VIEWER" and img.size[0] > 0 and img.size[1] > 0:
            print(f"[MoziToolKit Warning] Face material has no image texture. Falling back to active image in bpy.data.images: {img.name}", file=sys.stderr)
            return img

    return None

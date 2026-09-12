"""
UV bounds, center calculations, and face image resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
import sys
try:
    import bpy
    from mathutils import Vector
except ImportError:
    bpy = None
    Vector = None

def find_face_image(face, obj, context=None) -> bpy.types.Image | None:
    if not obj or not getattr(obj, "material_slots", None):
        return None
    mat_idx = getattr(face, "material_index", 0)
    if mat_idx < len(obj.material_slots):
        mat = obj.material_slots[mat_idx].material
        if mat and getattr(mat, "use_nodes", False) and mat.node_tree:
            for n in mat.node_tree.nodes:
                if n.type == 'TEX_IMAGE' and getattr(n, "image", None):
                    return n.image
    return None
from .uv_rotation import (
    is_orthogonal_angle,
    detect_face_uv_rotation,
    straighten_face_uv,
    process_mesh_uv_rotations,
    normalize_face_uv_for_atlas_tiling,
    face_uv_requires_atlas_tiling,
    restore_atlas_tiling_uv,
)
from .fluid_uv import (
    repair_face_fluid_uv,
    process_mesh_fluid_uv_repairs,
)


from .uv_math import (
    UVBounds,
    get_face_uv_bounds,
    get_face_uv_center,
    calculate_face_uv_area,
    is_face_uv_collapsed,
)



def get_image_from_face(face, obj, context=None) -> bpy.types.Image | None:
    """Find the Image object associated with a bmesh face."""
    return find_face_image(face, obj, context)

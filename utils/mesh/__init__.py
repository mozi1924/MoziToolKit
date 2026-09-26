"""
MoziToolKit Mesh & Geometry Manipulation Utilities.
"""

from .core import (
    SELECTION_ACTION_ITEMS,
    SELECTION_SCOPE_ITEMS,
    SELECT_MODES,
    apply_selection,
    bmesh_context,
    get_connected_faces,
    get_target_faces,
    is_hard_edge,
    poll_edit_mesh,
    poll_mesh_object,
    set_select_mode,
)
from .uv import (
    UVBounds,
    calculate_face_uv_area,
    get_face_uv_bounds,
    get_face_uv_center,
)
from .texture import (
    find_albedo_image_from_material,
    find_face_image,
)
from .fluid_uv import (
    is_fluid_texture_name,
    is_flowing_fluid_texture,
    repair_face_fluid_uv,
    repair_polygon_fluid_uv,
    process_mesh_fluid_uv_repairs,
)

from .random_extrude import (
    process_random_extrude,
)

__all__ = [
    "SELECTION_ACTION_ITEMS",
    "SELECTION_SCOPE_ITEMS",
    "SELECT_MODES",
    "apply_selection",
    "bmesh_context",
    "get_connected_faces",
    "get_target_faces",
    "is_hard_edge",
    "poll_edit_mesh",
    "poll_mesh_object",
    "set_select_mode",
    "UVBounds",
    "calculate_face_uv_area",
    "get_face_uv_bounds",
    "get_face_uv_center",
    "find_albedo_image_from_material",
    "find_face_image",
    "is_fluid_texture_name",
    "is_flowing_fluid_texture",
    "repair_face_fluid_uv",
    "repair_polygon_fluid_uv",
    "process_mesh_fluid_uv_repairs",
    "process_random_extrude",
]


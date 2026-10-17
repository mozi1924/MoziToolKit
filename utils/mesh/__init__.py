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
    process_bmesh_fluid_uv_repairs,
    process_raw_mesh_fluid_uv_repairs,
)

from .random_extrude import (
    process_random_extrude,
)
from .ownership import (
    ALL_ORIGINS,
    ORIGIN_EXTERNAL,
    ORIGIN_POINT_CLOUD,
    ORIGIN_PROP,
    ORIGIN_SAVE,
    ORIGIN_SYNC_SECTION,
    ORIGIN_SYNC_WORLD,
    ORIGIN_VOXEL,
    classify_origin,
    find_voxel_cloud,
    has_voxel_source,
    is_external_mesh,
    is_point_cloud,
    stamp_geometry_origin,
)

__all__ = [
    "SELECTION_ACTION_ITEMS",
    "SELECTION_SCOPE_ITEMS",
    "SELECT_MODES",
    "apply_selection",
    "bmesh_context",
    "get_connected_faces",
    "get_target_faces",
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
    "process_bmesh_fluid_uv_repairs",
    "process_raw_mesh_fluid_uv_repairs",
    "process_random_extrude",
    "ORIGIN_PROP",
    "ORIGIN_EXTERNAL",
    "ORIGIN_SAVE",
    "ORIGIN_SYNC_WORLD",
    "ORIGIN_SYNC_SECTION",
    "ORIGIN_VOXEL",
    "ORIGIN_POINT_CLOUD",
    "ALL_ORIGINS",
    "is_point_cloud",
    "stamp_geometry_origin",
    "classify_origin",
    "is_external_mesh",
    "find_voxel_cloud",
    "has_voxel_source",
]


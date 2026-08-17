"""
Mesh geometry, UV math, and topology processing subpackage.
"""

try:
    from .core import (
        SELECTION_ACTION_ITEMS,
        SELECTION_SCOPE_ITEMS,
        SELECT_MODES,
        poll_edit_mesh,
        poll_mesh_object,
        set_select_mode,
        bmesh_context,
        apply_selection,
        get_connected_faces,
        get_target_faces,
        is_hard_edge,
    )

    from .subdivide import (
        subdivide_quad_face,
        cleanup_mesh_topology,
    )

    from .random_extrude import (
        process_random_extrude,
    )

    from .uv import (
        UVBounds,
        get_face_uv_bounds,
        get_face_uv_center,
        get_image_from_face,
        is_orthogonal_angle,
        detect_face_uv_rotation,
        straighten_face_uv,
        process_mesh_uv_rotations,
        normalize_face_uv_for_atlas_tiling,
        face_uv_requires_atlas_tiling,
        restore_atlas_tiling_uv,
        repair_face_fluid_uv,
        process_mesh_fluid_uv_repairs,
    )
except ImportError:
    pass

__all__ = [
    "SELECTION_ACTION_ITEMS",
    "SELECTION_SCOPE_ITEMS",
    "SELECT_MODES",
    "poll_edit_mesh",
    "poll_mesh_object",
    "set_select_mode",
    "bmesh_context",
    "apply_selection",
    "get_connected_faces",
    "get_target_faces",
    "is_hard_edge",
    "UVBounds",
    "get_face_uv_bounds",
    "get_face_uv_center",
    "get_image_from_face",
    "is_orthogonal_angle",
    "detect_face_uv_rotation",
    "straighten_face_uv",
    "process_mesh_uv_rotations",
    "normalize_face_uv_for_atlas_tiling",
    "face_uv_requires_atlas_tiling",
    "restore_atlas_tiling_uv",
    "repair_face_fluid_uv",
    "process_mesh_fluid_uv_repairs",
    "process_random_extrude",
    "subdivide_quad_face",
    "cleanup_mesh_topology",
]

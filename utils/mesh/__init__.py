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

    from .uv import (
        UVBounds,
        get_face_uv_bounds,
        get_face_uv_center,
        get_image_from_face,
    )

    from .random_extrude import (
        process_random_extrude,
    )

    from .block_unmerge import (
        fast_unmerge_block_quads,
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
    "process_random_extrude",
    "fast_unmerge_block_quads",
]

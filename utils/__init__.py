# Utility functions package
from .mesh import (
    poll_edit_mesh,
    poll_mesh_object,
    set_select_mode,
    bmesh_context,
    apply_selection,
    get_connected_faces,
    get_target_faces,
    SELECTION_ACTION_ITEMS,
    SELECTION_SCOPE_ITEMS,
    SELECT_MODES,
)
from .uv import (
    UVBounds,
    get_face_uv_bounds,
    get_face_uv_center,
    get_image_from_face,
)
from .pixel_split import (
    process_adaptive_pixel_split,
    SplitConfig,
)
from .extrude_repair import (
    repair_extruded_side_faces,
    ExtrudeRepairConfig,
)
from .material import (
    set_materials_texture_interpolation_closest,
    process_node_tree_interpolation,
)
from .random_extrude import (
    process_random_extrude,
)

__all__ = [
    "poll_edit_mesh",
    "poll_mesh_object",
    "set_select_mode",
    "bmesh_context",
    "apply_selection",
    "get_connected_faces",
    "get_target_faces",
    "SELECTION_ACTION_ITEMS",
    "SELECTION_SCOPE_ITEMS",
    "SELECT_MODES",
    "UVBounds",
    "get_face_uv_bounds",
    "get_face_uv_center",
    "get_image_from_face",
    "process_adaptive_pixel_split",
    "SplitConfig",
    "repair_extruded_side_faces",
    "ExtrudeRepairConfig",
    "set_materials_texture_interpolation_closest",
    "process_node_tree_interpolation",
    "process_random_extrude",
]



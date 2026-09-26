"""
MoziToolKit Bridge Package.
Pure zero-computation data marshalling layer between Blender (bpy/bmesh) and libmtk (Rust).
"""

from .assets import (
    clear_cache,
    get_cache_dir,
    get_cache_stats,
    get_configured_pack_stack,
    open_cache_folder,
    precompile_stack,
)
from .mesh import (
    BLENDER_TO_MTK_DOMAIN,
    BLENDER_TO_MTK_TYPE,
    MTK_TO_BLENDER_DOMAIN,
    MTK_TO_BLENDER_TYPE,
    extract_mesh_data,
    inject_mesh_data,
)
from .cull import cull_mesh_faces
from .extrude import (
    generate_random_extrude_heights,
    process_random_extrude,
    repair_extruded_side_faces,
    repair_extruded_side_uv,
)
from .subdivide import adaptive_pixel_split_mesh, calculate_face_target_grid
from .texture import (
    batch_analyze_transparent_faces,
    is_face_transparent,
    sample_uv_alpha,
)
from .uv import (
    batch_repair_fluid_uv,
    calculate_uv_area,
    detect_uv_rotation,
    get_fluid_side_uvs,
    get_fluid_top_uvs,
    get_uv_bounds,
    get_uv_center,
    is_orthogonal_angle,
    is_uv_collapsed,
    normalize_uv_for_atlas_tiling,
    repair_quad_fluid_uv,
    restore_atlas_tiling_uv,
    scale_uv,
    straighten_uv,
    uv_requires_atlas_tiling,
)

__all__ = [
    "clear_cache",
    "get_cache_dir",
    "get_cache_stats",
    "get_configured_pack_stack",
    "open_cache_folder",
    "precompile_stack",
    "extract_mesh_data",
    "inject_mesh_data",
    "BLENDER_TO_MTK_DOMAIN",
    "BLENDER_TO_MTK_TYPE",
    "MTK_TO_BLENDER_DOMAIN",
    "MTK_TO_BLENDER_TYPE",
    "calculate_uv_area",
    "get_uv_bounds",
    "get_uv_center",
    "is_uv_collapsed",
    "is_orthogonal_angle",
    "detect_uv_rotation",
    "straighten_uv",
    "scale_uv",
    "normalize_uv_for_atlas_tiling",
    "uv_requires_atlas_tiling",
    "restore_atlas_tiling_uv",
    "repair_quad_fluid_uv",
    "batch_repair_fluid_uv",
    "get_fluid_top_uvs",
    "get_fluid_side_uvs",
    "batch_analyze_transparent_faces",
    "is_face_transparent",
    "sample_uv_alpha",
    "calculate_face_target_grid",
    "adaptive_pixel_split_mesh",
    "repair_extruded_side_uv",
    "repair_extruded_side_faces",
    "process_random_extrude",
    "generate_random_extrude_heights",
    "cull_mesh_faces",
]


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
from .texture import (
    HAS_LIBMTK_ALPHA,
    batch_analyze_transparent_faces,
    is_face_transparent,
    sample_uv_alpha,
)
from .uv import (
    HAS_LIBMTK_UV,
    calculate_uv_area,
    get_uv_bounds,
    get_uv_center,
    is_uv_collapsed,
    is_orthogonal_angle,
    detect_uv_rotation,
    straighten_uv,
    scale_uv,
    normalize_uv_for_atlas_tiling,
    uv_requires_atlas_tiling,
    restore_atlas_tiling_uv,
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
    "HAS_LIBMTK_UV",
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
    "HAS_LIBMTK_ALPHA",
    "batch_analyze_transparent_faces",
    "is_face_transparent",
    "sample_uv_alpha",
]


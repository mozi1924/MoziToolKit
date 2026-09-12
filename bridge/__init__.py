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
]


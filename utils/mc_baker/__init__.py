"""
Headless Minecraft Model Baker package for DCC/Blender integration.
"""

from .types import (
    MC_DIRECTIONS,
    DIR_TO_INDEX,
    INDEX_TO_DIR,
    DIR_NORMALS,
    BakedFace,
    BakedElement,
    BakedModel,
)
from .math_utils import (
    rotate_point,
    rotate_element_point,
    rotate_direction,
    calculate_uv_rotation,
    default_face_uv,
    get_face_raw_vertices,
    get_face_loop_uvs,
    apply_uvlock_to_uvs,
)
from .resource_loader import JarResourceLoader
from .model_parser import ModelParser
from .blockstate_resolver import BlockStateResolver, parse_block_state_string
from .state_baker import (
    StateBaker,
    EMISSIVE_BLOCKS,
    is_block_emissive,
    get_shared_state_baker,
    refresh_shared_baker_sources,
    clear_shared_baker_cache,
)
from .obj_loader import (
    resolve_obj_model_for_state,
    build_baked_model_from_obj,
)
try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

if HAS_BPY:
    from .mesh_generator import (
        mc_pos_to_blender,
        build_blender_mesh_from_baked_model,
        create_block_object,
    )
else:
    mc_pos_to_blender = None
    build_blender_mesh_from_baked_model = None
    create_block_object = None

__all__ = [
    "MC_DIRECTIONS",
    "DIR_TO_INDEX",
    "INDEX_TO_DIR",
    "DIR_NORMALS",
    "BakedFace",
    "BakedElement",
    "BakedModel",
    "rotate_point",
    "rotate_element_point",
    "rotate_direction",
    "calculate_uv_rotation",
    "default_face_uv",
    "get_face_raw_vertices",
    "get_face_loop_uvs",
    "apply_uvlock_to_uvs",
    "JarResourceLoader",
    "ModelParser",
    "BlockStateResolver",
    "parse_block_state_string",
    "StateBaker",
    "EMISSIVE_BLOCKS",
    "is_block_emissive",
    "get_shared_state_baker",
    "refresh_shared_baker_sources",
    "clear_shared_baker_cache",
    "resolve_obj_model_for_state",
    "build_baked_model_from_obj",
    "mc_pos_to_blender",
    "build_blender_mesh_from_baked_model",
    "create_block_object",
]

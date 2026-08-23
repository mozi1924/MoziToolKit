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
from .state_baker import StateBaker
from .atlas_bridge import AtlasBridge, ResolvedAtlasFace
from .mesh_generator import (
    mc_pos_to_blender,
    build_blender_mesh_from_baked_model,
    create_block_object,
)
from .template_updater import (
    update_mc_block_templates_from_pack,
    attach_yefira_template_attributes,
    TEMPLATE_COLLECTION_NAME,
)

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
    "AtlasBridge",
    "ResolvedAtlasFace",
    "mc_pos_to_blender",
    "build_blender_mesh_from_baked_model",
    "create_block_object",
    "update_mc_block_templates_from_pack",
    "attach_yefira_template_attributes",
    "TEMPLATE_COLLECTION_NAME",
]

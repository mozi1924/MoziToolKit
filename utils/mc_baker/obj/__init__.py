"""
OBJ Model Loading Subsystem for Minecraft Model Baker.
Separates Authoritative Built-in Entity Presets from Generic Mod OBJ Loaders.
"""

from .base_parser import WavefrontOBJParser, OBJRawFace
from .mod_obj_loader import ModOBJLoader
from .builtin_presets import (
    BuiltinOBJCache,
    SpecialModelRegistry,
    build_baked_model_from_obj,
    resolve_obj_model_for_state,
    resolve_chest_material,
    build_bell_model,
    build_shulker_box_model,
    build_conduit_model,
    build_end_portal_model,
    build_end_gateway_model,
    transform_obj_point,
)

__all__ = [
    "WavefrontOBJParser",
    "OBJRawFace",
    "ModOBJLoader",
    "BuiltinOBJCache",
    "SpecialModelRegistry",
    "build_baked_model_from_obj",
    "resolve_obj_model_for_state",
    "resolve_chest_material",
    "build_bell_model",
    "build_shulker_box_model",
    "build_conduit_model",
    "build_end_portal_model",
    "build_end_gateway_model",
    "transform_obj_point",
]

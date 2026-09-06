"""
OBJ Model Loader & Registry Facade for Minecraft Block Entity models and Modded models.
Re-exports from the modularized obj package for seamless backward compatibility.
"""

from __future__ import annotations
from pathlib import Path

from .obj.base_parser import WavefrontOBJParser, OBJRawFace
from .obj.mod_obj_loader import ModOBJLoader
from .obj.builtin_presets import (
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
    MODELS_DIR,
    _BUILTIN_CACHE,
)

# Backward-compatibility aliases
OBJModelCache = BuiltinOBJCache
_OBJ_CACHE = _BUILTIN_CACHE

__all__ = [
    "WavefrontOBJParser",
    "OBJRawFace",
    "ModOBJLoader",
    "BuiltinOBJCache",
    "OBJModelCache",
    "_OBJ_CACHE",
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
    "MODELS_DIR",
]

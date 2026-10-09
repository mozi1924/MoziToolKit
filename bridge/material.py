"""
MoziToolKit Material & Biome Bridge Module.
Encapsulates high-performance Rust core (libmtk_py) routines for material name resolution,
UV remapping, atlas metadata, and Biome color/tint generation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from .engine import get_libmtk, has_libmtk, require_libmtk

logger = logging.getLogger(__name__)


def is_material_bridge_available() -> bool:
    """Check if native libmtk_py material and biome functions are loaded."""
    mtk = get_libmtk()
    return bool(
        mtk is not None
        and hasattr(mtk, "MaterialResolver")
        and hasattr(mtk, "BiomeResolver")
    )


def require_material_bridge() -> None:
    """Raise RuntimeError if native libmtk_py material bridge is unavailable."""
    if not is_material_bridge_available():
        require_libmtk("material & biome bridge")


# ---------------------------------------------------------------------------
# Fallback Classes
# ---------------------------------------------------------------------------

class _FallbackBiomeResolver:
    """Fallback placeholder when libmtk is not loaded."""

    def __init__(self):
        pass

    @classmethod
    def from_file(cls, path: str):
        return cls()

    def load_from_pack_stack(self, stack: Any) -> None:
        pass

    def get_tint_info(
        self,
        texture_name: str,
        block_name: Optional[str] = None,
        tint_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        return {
            "tint_type": 0,
            "tint_category": "none",
            "tint_weight": 0.0,
            "base_tint_weight": 0.0,
            "overlay_tint_weight": 0.0,
            "is_hardcoded": False,
            "hardcoded_color": None,
        }

    def get_overlay_texture(self, texture_stem: str) -> Optional[str]:
        return None


class _FallbackMaterialResolver:
    """Fallback placeholder when libmtk is not loaded."""

    @staticmethod
    def clean_name(name: str) -> str:
        clean = name.split("/")[-1].split("\\")[-1]
        if "." in clean:
            clean = clean.split(".")[0]
        for suffix in ["_diffuse", "_d", "_albedo", "_col", "_basecolor"]:
            if clean.endswith(suffix):
                clean = clean[: -len(suffix)]
        return clean


class _FallbackGridAtlasSpec:
    """Fallback GridAtlasSpec descriptor."""

    def __init__(
        self,
        swatch_size: float = 18.0,
        tile_size: float = 16.0,
        border: float = 1.0,
        image_width: int = 1024,
        image_height: int = 1024,
        atlas_name_patterns: Optional[List[str]] = None,
        atlas_suffix_patterns: Optional[List[str]] = None,
        swatch_to_candidates: Optional[Dict[int, List[str]]] = None,
    ):
        self.swatch_size = swatch_size
        self.tile_size = tile_size
        self.border = border
        self.image_width = image_width
        self.image_height = image_height
        self.atlas_name_patterns = atlas_name_patterns or []
        self.atlas_suffix_patterns = atlas_suffix_patterns or []
        self.swatch_to_candidates = swatch_to_candidates or {}


def __getattr__(name: str) -> Any:
    mtk = get_libmtk()
    if name == "HAS_LIBMTK":
        return is_material_bridge_available()
    if name == "BiomeResolver":
        return getattr(mtk, "BiomeResolver", _FallbackBiomeResolver) if mtk else _FallbackBiomeResolver
    if name == "MaterialResolver":
        return getattr(mtk, "MaterialResolver", _FallbackMaterialResolver) if mtk else _FallbackMaterialResolver
    if name == "GridAtlasSpec":
        return getattr(mtk, "GridAtlasSpec", _FallbackGridAtlasSpec) if mtk else _FallbackGridAtlasSpec
    if name == "BakedAtlas":
        return getattr(mtk, "BakedAtlas", None) if mtk else None
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


# ---------------------------------------------------------------------------
# Biome Metadata & Colormap API
# ---------------------------------------------------------------------------

def load_biome_resolver_from_file(file_path: Union[str, Path]) -> Any:
    """Load a precompiled BiomeResolver instance from a biome_mapping.json file."""
    mtk = require_libmtk("load_biome_resolver_from_file")
    return mtk.BiomeResolver.from_file(str(file_path))


def get_biome_meta(biome_name: str) -> Dict[str, Any]:
    """Retrieve canonical metadata, temperature, humidity, and colors from Rust core."""
    mtk = get_libmtk()
    if mtk and hasattr(mtk, "get_biome_meta"):
        return mtk.get_biome_meta(biome_name)

    # Safe fallback if native module is absent
    return {
        "id": biome_name.lower(),
        "name": biome_name,
        "temperature": 0.8,
        "humidity": 0.4,
        "grass_hex": "#91BD59",
        "foliage_hex": "#77AB2F",
        "dry_foliage_hex": "#A37546",
        "water_hex": "#3F76E4",
        "grass_linear": [0.27, 0.50, 0.09, 1.0],
        "foliage_linear": [0.18, 0.40, 0.03, 1.0],
        "dry_foliage_linear": [0.36, 0.22, 0.06, 1.0],
        "water_linear": [0.05, 0.18, 0.78, 1.0],
        "colormap_uv": [0.2, 0.32],
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False,
    }


def get_colormap_uv(temperature: float, humidity: float) -> List[float]:
    """Compute 2D colormap UV coordinates for a given temperature and humidity."""
    mtk = get_libmtk()
    if mtk and hasattr(mtk, "get_colormap_uv"):
        return mtk.get_colormap_uv(temperature, humidity)

    t = max(0.0, min(1.0, temperature))
    h = max(0.0, min(1.0, humidity)) * t
    return [1.0 - t, h]


def get_all_biomes() -> List[Dict[str, Any]]:
    """Retrieve all standard vanilla Minecraft biomes with canonical metadata."""
    mtk = get_libmtk()
    if mtk and hasattr(mtk, "get_all_biomes"):
        return mtk.get_all_biomes()
    return [{"id": "plains", "name": "Plains", "temperature": 0.8, "humidity": 0.4}]


def compute_biome_tint_attributes(
    face_texture_keys: List[str],
    biome_preset: Union[str, List[Tuple[str, float]]] = "PLAINS",
    resolver: Optional[Any] = None,
    custom_temp: Optional[float] = None,
    custom_humidity: Optional[float] = None,
    custom_grass: Optional[List[float]] = None,
    custom_foliage: Optional[List[float]] = None,
    custom_dry_foliage: Optional[List[float]] = None,
    custom_water: Optional[List[float]] = None,
    has_custom_grass: bool = False,
    has_custom_foliage: bool = False,
    has_custom_dry_foliage: bool = False,
) -> Dict[str, Any]:
    """
    Compute packed tint weights, colors, and colormap UV coordinates using Rust core.
    Returns dictionary with keys: 'packed_tint_data', 'tint_colors', 'colormap_uvs'.
    """
    mtk = get_libmtk()
    if mtk is None or not hasattr(mtk, "compute_biome_tint_attributes"):
        n = len(face_texture_keys)
        temp = custom_temp if custom_temp is not None else 0.8
        hum = custom_humidity if custom_humidity is not None else 0.4
        uv = get_colormap_uv(temp, hum)
        return {
            "packed_tint_data": [[0.0, 0.0, 0.0, 0.0]] * n,
            "tint_colors": [[1.0, 1.0, 1.0, 1.0]] * n,
            "colormap_uvs": [[uv[0], uv[1], 0.0]] * n,
        }

    if isinstance(biome_preset, list):
        return mtk.compute_biome_tint_attributes(
            face_texture_keys,
            "PLAINS",
            multi_biomes=biome_preset,
            resolver=resolver,
        )

    return mtk.compute_biome_tint_attributes(
        face_texture_keys,
        str(biome_preset),
        multi_biomes=None,
        resolver=resolver,
        custom_temp=custom_temp,
        custom_humidity=custom_humidity,
        custom_grass=custom_grass,
        custom_foliage=custom_foliage,
        custom_dry_foliage=custom_dry_foliage,
        custom_water=custom_water,
        has_custom_grass=has_custom_grass,
        has_custom_foliage=has_custom_foliage,
        has_custom_dry_foliage=has_custom_dry_foliage,
    )


# ---------------------------------------------------------------------------
# Material Resolution & UV Remapping
# ---------------------------------------------------------------------------

def clean_material_name(name: str) -> str:
    """Normalize and clean a material or texture name into an identifier stem."""
    mtk = get_libmtk()
    if mtk and hasattr(mtk, "MaterialResolver"):
        return mtk.MaterialResolver.clean_name(name)
    return _FallbackMaterialResolver.clean_name(name)


def remap_mesh_multi_uvs(
    loop_uvs: Sequence[float],
    face_materials: Sequence[str],
    face_loop_ranges: Sequence[Tuple[int, int]],
    atlas: Any,
    alias_map: Optional[Dict[str, List[str]]] = None,
    grid_spec: Optional[Any] = None,
) -> Any:
    """
    Execute high-performance multi-threaded UV remapping and material slot resolution in Rust.
    """
    mtk = require_libmtk("remap_mesh_multi_uvs")
    return mtk.MaterialResolver.remap_mesh_multi_uvs(
        loop_uvs if isinstance(loop_uvs, (list, np.ndarray)) else list(loop_uvs),
        face_materials if isinstance(face_materials, list) else list(face_materials),
        face_loop_ranges if isinstance(face_loop_ranges, list) else list(face_loop_ranges),
        atlas,
        alias_map,
        grid_spec,
    )


def load_baked_atlas_from_json(json_str: str) -> Any:
    """Load a BakedAtlas instance from atlas_mapping.json string content."""
    mtk = require_libmtk("load_baked_atlas_from_json")
    return mtk.BakedAtlas.from_mapping_json(json_str)


# ---------------------------------------------------------------------------
# Material Physical Properties & Catalog API (Pure Rust libmtk_py)
# ---------------------------------------------------------------------------

def compute_mesh_material_props(
    face_source_keys: Sequence[str],
    block_names: Optional[Sequence[str]] = None,
) -> List[List[float]]:
    """
    Compute packed material properties `[emission, thin_wall, transmission, sticker_threshold]`
    for a list of face texture keys in parallel Rayon in Rust.
    """
    mtk = require_libmtk("compute_mesh_material_props")
    return mtk.compute_mesh_material_props(
        list(face_source_keys),
        list(block_names) if block_names is not None else None,
    )


def compute_flat_material_props(
    face_source_keys: Sequence[str],
    block_names: Optional[Sequence[str]] = None,
) -> List[float]:
    """
    Compute flat packed material properties (float array of length len * 4)
    for zero-copy memoryview / foreach_set injection into Blender Mesh.
    """
    mtk = require_libmtk("compute_flat_material_props")
    return mtk.compute_flat_material_props(
        list(face_source_keys),
        list(block_names) if block_names is not None else None,
    )


def get_material_props(
    block_name: str = "",
    texture_name: Optional[str] = None,
) -> Tuple[float, float, float, float]:
    """Query individual block material physical properties `[emission, thin_wall, transmission, sticker_threshold]`."""
    mtk = require_libmtk("get_material_props")
    props = mtk.get_material_props(block_name, texture_name)
    return (float(props[0]), float(props[1]), float(props[2]), float(props[3]))


def get_block_emission_strength(
    block_name: str = "",
    properties: Optional[Dict[str, Any]] = None,
    texture_name: Optional[str] = None,
) -> float:
    """Query canonical emission strength for a block / texture (0.0 .. 15.0)."""
    mtk = require_libmtk("get_block_emission_strength")
    str_props = {str(k): str(v) for k, v in properties.items()} if properties else None
    return float(mtk.get_block_emission_strength(block_name, str_props, texture_name))


def is_thin_wall_block(
    block_name: str = "",
    texture_name: Optional[str] = None,
) -> bool:
    """Query whether a block or texture is thin wall foliage / vegetation."""
    mtk = require_libmtk("is_thin_wall_block")
    return bool(mtk.is_thin_wall_block(block_name, texture_name))


def is_transmissive_block(
    block_name: str = "",
    texture_name: Optional[str] = None,
) -> bool:
    """Query whether a block or texture is a dielectric transmissive medium (glass, water, ice, etc.)."""
    mtk = require_libmtk("is_transmissive_block")
    return bool(mtk.is_transmissive_block(block_name, texture_name))


def get_block_transmission_weight(
    block_name: str = "",
    texture_name: Optional[str] = None,
) -> float:
    """Query transmission weight (1.0 for glass/water/ice, 0.0 otherwise)."""
    mtk = require_libmtk("get_block_transmission_weight")
    return float(mtk.get_block_transmission_weight(block_name, texture_name))


def get_block_sticker_threshold(
    block_name: str = "",
    texture_name: Optional[str] = None,
) -> float:
    """Query alpha sticker threshold (0.55 for glass, 0.95 for water/ice/slime/honey)."""
    mtk = require_libmtk("get_block_sticker_threshold")
    return float(mtk.get_block_sticker_threshold(block_name, texture_name))


def get_default_material_properties_path() -> Path:
    """Return default configuration path in MoziToolKit/configs/material_properties.json."""
    return Path(__file__).resolve().parent.parent / "configs" / "material_properties.json"


def load_material_properties_config(
    config: Optional[Union[str, Path, Dict[str, Any]]] = None,
    replace: bool = False,
) -> bool:
    """
    Load and send physical material properties (emission, thin wall, transmission, sticker threshold)
    into the Rust core registry.

    Args:
        config: Path to a JSON file, raw JSON string, or dict. If None, loads from `configs/material_properties.json`.
        replace: If True, completely replaces the Rust registry; if False, merges/overrides.
    """
    mtk = get_libmtk()
    if not mtk or not hasattr(mtk, "register_material_properties"):
        return False

    if config is None:
        cfg_path = get_default_material_properties_path()
        if not cfg_path.is_file():
            return False
        config = cfg_path

    if isinstance(config, (str, Path)):
        p = Path(config)
        if p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception as e:
                logger.error(f"Failed to read material properties JSON '{p}': {e}")
                return False
        else:
            if isinstance(config, str) and config.strip().startswith("{"):
                try:
                    payload = json.loads(config)
                except Exception as e:
                    logger.error(f"Failed to parse material properties JSON string: {e}")
                    return False
            else:
                logger.error(f"Material properties file not found: {p}")
                return False
    elif isinstance(config, dict):
        payload = config
    else:
        logger.error(f"Unsupported config type: {type(config)}")
        return False

    try:
        if replace and hasattr(mtk, "load_material_properties_replace"):
            mtk.load_material_properties_replace(payload)
        else:
            mtk.register_material_properties(payload)
        return True
    except Exception as e:
        logger.error(f"Failed to inject material properties into Rust core: {e}")
        return False


def reset_material_properties_config() -> bool:
    """Reset Rust core material properties to built-in vanilla defaults."""
    mtk = get_libmtk()
    if not mtk or not hasattr(mtk, "reset_material_properties_to_default"):
        return False
    mtk.reset_material_properties_to_default()
    return True


__all__ = [
    "HAS_LIBMTK",
    "is_material_bridge_available",
    "require_material_bridge",
    "BiomeResolver",
    "load_biome_resolver_from_file",
    "get_biome_meta",
    "get_colormap_uv",
    "get_all_biomes",
    "compute_biome_tint_attributes",
    "MaterialResolver",
    "clean_material_name",
    "remap_mesh_multi_uvs",
    "GridAtlasSpec",
    "BakedAtlas",
    "load_baked_atlas_from_json",
    "compute_mesh_material_props",
    "compute_flat_material_props",
    "get_material_props",
    "get_block_emission_strength",
    "is_thin_wall_block",
    "is_transmissive_block",
    "get_block_transmission_weight",
    "get_block_sticker_threshold",
    "get_default_material_properties_path",
    "load_material_properties_config",
    "reset_material_properties_config",
]



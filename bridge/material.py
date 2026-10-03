"""
MoziToolKit Material & Biome Bridge Module.
Encapsulates high-performance Rust core (libmtk_py) routines for material name resolution,
UV remapping, atlas metadata, and Biome color/tint generation.
"""

from __future__ import annotations

import array
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)



try:
    import libmtk_py
    HAS_LIBMTK = True
except ImportError:
    libmtk_py = None
    HAS_LIBMTK = False


def is_material_bridge_available() -> bool:
    """Check if native libmtk_py material and biome functions are loaded."""
    return bool(
        HAS_LIBMTK
        and hasattr(libmtk_py, "MaterialResolver")
        and hasattr(libmtk_py, "BiomeResolver")
    )


def require_material_bridge() -> None:
    """Raise RuntimeError if native libmtk_py material bridge is unavailable."""
    if not is_material_bridge_available():
        raise RuntimeError(
            "libmtk_py (Rust material & biome backend) is not installed or available. "
            "Please ensure the compiled extension wheel is present in MoziToolKit/wheels/."
        )


# ---------------------------------------------------------------------------
# BiomeResolver & Tinting
# ---------------------------------------------------------------------------

if HAS_LIBMTK and hasattr(libmtk_py, "BiomeResolver"):
    BiomeResolver = libmtk_py.BiomeResolver
else:
    class BiomeResolver:  # type: ignore
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


def load_biome_resolver_from_file(file_path: Union[str, Path]) -> BiomeResolver:
    """Load a precompiled BiomeResolver instance from a biome_mapping.json file."""
    require_material_bridge()
    return BiomeResolver.from_file(str(file_path))


def get_biome_meta(biome_name: str) -> Dict[str, Any]:
    """Retrieve canonical metadata, temperature, humidity, and colors from Rust core."""
    if HAS_LIBMTK and hasattr(libmtk_py, "get_biome_meta"):
        return libmtk_py.get_biome_meta(biome_name)

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
    if HAS_LIBMTK and hasattr(libmtk_py, "get_colormap_uv"):
        return libmtk_py.get_colormap_uv(temperature, humidity)

    t = max(0.0, min(1.0, temperature))
    h = max(0.0, min(1.0, humidity)) * t
    return [1.0 - t, h]


def get_all_biomes() -> List[Dict[str, Any]]:
    """Retrieve all standard vanilla Minecraft biomes with canonical metadata."""
    if HAS_LIBMTK and hasattr(libmtk_py, "get_all_biomes"):
        return libmtk_py.get_all_biomes()
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
    if not HAS_LIBMTK or not hasattr(libmtk_py, "compute_biome_tint_attributes"):
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
        return libmtk_py.compute_biome_tint_attributes(
            face_texture_keys,
            "PLAINS",
            multi_biomes=biome_preset,
            resolver=resolver,
        )

    return libmtk_py.compute_biome_tint_attributes(
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

if HAS_LIBMTK and hasattr(libmtk_py, "MaterialResolver"):
    MaterialResolver = libmtk_py.MaterialResolver
else:
    class MaterialResolver:  # type: ignore
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


def clean_material_name(name: str) -> str:
    """Normalize and clean a material or texture name into an identifier stem."""
    if HAS_LIBMTK and hasattr(libmtk_py, "MaterialResolver"):
        return libmtk_py.MaterialResolver.clean_name(name)
    return MaterialResolver.clean_name(name)


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
    require_material_bridge()
    return libmtk_py.MaterialResolver.remap_mesh_multi_uvs(
        loop_uvs if isinstance(loop_uvs, (list, array.array)) else list(loop_uvs),
        face_materials if isinstance(face_materials, list) else list(face_materials),
        face_loop_ranges if isinstance(face_loop_ranges, list) else list(face_loop_ranges),
        atlas,
        alias_map,
        grid_spec,
    )


# ---------------------------------------------------------------------------
# Atlas & Grid Spec
# ---------------------------------------------------------------------------

if HAS_LIBMTK and hasattr(libmtk_py, "GridAtlasSpec"):
    GridAtlasSpec = libmtk_py.GridAtlasSpec
else:
    class GridAtlasSpec:  # type: ignore
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


if HAS_LIBMTK and hasattr(libmtk_py, "BakedAtlas"):
    BakedAtlas = libmtk_py.BakedAtlas
else:
    BakedAtlas = None  # type: ignore


def load_baked_atlas_from_json(json_str: str) -> Any:
    """Load a BakedAtlas instance from atlas_mapping.json string content."""
    require_material_bridge()
    return libmtk_py.BakedAtlas.from_mapping_json(json_str)


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
]

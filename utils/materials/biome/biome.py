"""
Minecraft Biome & Tinting Bridge (Thin Glue Layer to Rust libmtk Core).
All mathematical calculations, colormap sampling coordinates, model JSON tint parsing,
and multi-threaded mesh attribute generation are executed inside libmtk_py.
"""

from __future__ import annotations

import array
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import libmtk_py
    HAS_LIBMTK = True
except ImportError:
    libmtk_py = None
    HAS_LIBMTK = False

from ..constants import (
    ATTR_BIOME_TINT_DATA,
    ATTR_BIOME_TINT_COLOR,
    ATTR_COLORMAP_UV,
)

# Canonical Tint Type Identifiers
TINT_TYPE_NONE = 0
TINT_TYPE_GRASS = 1
TINT_TYPE_FOLIAGE = 2
TINT_TYPE_WATER = 3
TINT_TYPE_HARDCODED = 4
TINT_TYPE_DRY_FOLIAGE = 5

# BiomeResolver class directly backed by Rust
if HAS_LIBMTK and hasattr(libmtk_py, "BiomeResolver"):
    BiomeResolver = libmtk_py.BiomeResolver
else:
    class BiomeResolver:
        """Fallback placeholder when libmtk is not loaded."""
        def __init__(self):
            pass
        @classmethod
        def from_file(cls, path: str):
            return cls()
        def get_tint_info(self, texture_name: str, block_name: Optional[str] = None, tint_index: Optional[int] = None) -> dict:
            return {"tint_type": 0, "tint_category": "none", "tint_weight": 0.0, "base_tint_weight": 0.0, "overlay_tint_weight": 0.0}
        def get_overlay_texture(self, texture_stem: str) -> Optional[str]:
            return None


def get_or_load_biome_resolver(
    cache_dir: Optional[Union[str, Path]] = None,
    prefs: Optional[Any] = None,
    pack_stack: Optional[Any] = None,
) -> Any:
    """
    Get a prebaked BiomeResolver instance.
    Prioritizes instant loading from `biome_mapping.json` in the compiled cache directory (< 0.2ms).
    Falls back to parsing the pack stack if cache is not yet compiled.
    """
    if not HAS_LIBMTK:
        return BiomeResolver()

    # 1. Try loading from cache directory if available
    target_cache = None
    if cache_dir is not None:
        target_cache = Path(cache_dir)
    else:
        try:
            from bridge.assets import get_cache_dir
            target_cache = get_cache_dir(prefs)
        except Exception:
            target_cache = None

    if target_cache:
        # Check standard cache mapping locations
        candidates = [
            target_cache / "biome_mapping.json",
            target_cache / "atlas" / "biome_mapping.json",
        ]
        for c in candidates:
            if c.exists() and c.is_file():
                try:
                    return BiomeResolver.from_file(str(c.resolve()))
                except Exception:
                    pass

    # 2. Fallback: Parse active pack stack if provided
    resolver = BiomeResolver()
    effective_stack = pack_stack
    if effective_stack is None:
        try:
            from bridge.assets import get_configured_pack_stack
            effective_stack = get_configured_pack_stack(prefs)
        except Exception:
            effective_stack = None

    if effective_stack:
        try:
            resolver.load_from_pack_stack(effective_stack)
        except Exception:
            pass

    return resolver


def get_biome_colors(
    biome_name: str,
    pack_stack: Any = None,
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
    """Retrieve canonical metadata, temperature, humidity, and Linear RGBA colors from Rust core."""
    if not HAS_LIBMTK:
        temp = custom_temp if custom_temp is not None else 0.8
        hum = custom_humidity if custom_humidity is not None else 0.4
        return {
            "id": biome_name.lower(),
            "name": biome_name,
            "temperature": temp,
            "humidity": hum,
            "grass_hex": "#91BD59",
            "foliage_hex": "#77AB2F",
            "dry_foliage_hex": "#A37546",
            "water_hex": "#3F76E4",
            "grass_linear": custom_grass or [0.27, 0.50, 0.09, 1.0],
            "foliage_linear": custom_foliage or [0.18, 0.40, 0.03, 1.0],
            "dry_foliage_linear": custom_dry_foliage or [0.36, 0.22, 0.06, 1.0],
            "water_linear": custom_water or [0.05, 0.18, 0.78, 1.0],
            "colormap_uv": [1.0 - max(0.0, min(1.0, temp)), max(0.0, min(1.0, hum)) * max(0.0, min(1.0, temp))],
            "has_custom_grass": has_custom_grass,
            "has_custom_foliage": has_custom_foliage,
            "has_custom_dry_foliage": has_custom_dry_foliage,
        }

    meta = libmtk_py.get_biome_meta(biome_name)
    if biome_name.upper() == "CUSTOM":
        temp = custom_temp if custom_temp is not None else meta.get("temperature", 0.8)
        hum = custom_humidity if custom_humidity is not None else meta.get("humidity", 0.4)
        meta["temperature"] = temp
        meta["humidity"] = hum
        if hasattr(libmtk_py, "get_colormap_uv"):
            meta["colormap_uv"] = libmtk_py.get_colormap_uv(temp, hum)
        else:
            meta["colormap_uv"] = [1.0 - max(0.0, min(1.0, temp)), max(0.0, min(1.0, hum)) * max(0.0, min(1.0, temp))]

        if custom_grass is not None:
            meta["grass_linear"] = list(custom_grass)
        if custom_foliage is not None:
            meta["foliage_linear"] = list(custom_foliage)
        if custom_dry_foliage is not None:
            meta["dry_foliage_linear"] = list(custom_dry_foliage)
        if custom_water is not None:
            meta["water_linear"] = list(custom_water)

        meta["has_custom_grass"] = has_custom_grass
        meta["has_custom_foliage"] = has_custom_foliage
        meta["has_custom_dry_foliage"] = has_custom_dry_foliage

    return meta


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
) -> Tuple[List[List[float]], List[List[float]], List[List[float]]]:
    """
    Compute packed tint weights, colors, and colormap UV coordinates for mesh faces using Rust core.
    Returns (packed_tint_data, tint_colors, colormap_uvs).
    """
    if not HAS_LIBMTK:
        n = len(face_texture_keys)
        temp = custom_temp if custom_temp is not None else 0.8
        hum = custom_humidity if custom_humidity is not None else 0.4
        u = 1.0 - max(0.0, min(1.0, temp))
        v = max(0.0, min(1.0, hum)) * max(0.0, min(1.0, temp))
        return (
            [[0.0, 0.0, 0.0, 0.0]] * n,
            [[1.0, 1.0, 1.0, 1.0]] * n,
            [[u, v, 0.0]] * n,
        )

    if isinstance(biome_preset, list):
        res = libmtk_py.compute_biome_tint_attributes(
            face_texture_keys,
            "PLAINS",
            multi_biomes=biome_preset,
            resolver=resolver,
        )
    else:
        res = libmtk_py.compute_biome_tint_attributes(
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

    return res["packed_tint_data"], res["tint_colors"], res["colormap_uvs"]


def apply_biome_tint_attributes(
    mesh: Any,
    packed_tint_data: List[List[float]],
    tint_colors: List[List[float]],
    colormap_uvs: Optional[List[List[float]]] = None,
) -> None:
    """Write Rust-computed biome tint data, color vectors, and colormap UVs directly to Blender mesh face attributes."""
    if not hasattr(mesh, "attributes"):
        return

    # 1. ATTR_BIOME_TINT_DATA (FLOAT_COLOR)
    attr_data = mesh.attributes.get(ATTR_BIOME_TINT_DATA)
    if attr_data is None:
        try:
            attr_data = mesh.attributes.new(name=ATTR_BIOME_TINT_DATA, type="FLOAT_COLOR", domain="FACE")
        except Exception:
            attr_data = None
    if attr_data and len(attr_data.data) * 4 == len(packed_tint_data) * 4:
        flat_data = [c for val in packed_tint_data for c in val]
        attr_data.data.foreach_set("color", array.array("f", flat_data))

    # 2. ATTR_BIOME_TINT_COLOR (FLOAT_COLOR)
    attr_col = mesh.attributes.get(ATTR_BIOME_TINT_COLOR)
    if attr_col is None:
        try:
            attr_col = mesh.attributes.new(name=ATTR_BIOME_TINT_COLOR, type="FLOAT_COLOR", domain="FACE")
        except Exception:
            attr_col = None
    if attr_col and len(attr_col.data) * 4 == len(tint_colors) * 4:
        flat_col = [c for val in tint_colors for c in val]
        attr_col.data.foreach_set("color", array.array("f", flat_col))

    # 3. ATTR_COLORMAP_UV (FLOAT_VECTOR)
    if colormap_uvs is not None:
        attr_uv = mesh.attributes.get(ATTR_COLORMAP_UV)
        if attr_uv is None:
            try:
                attr_uv = mesh.attributes.new(name=ATTR_COLORMAP_UV, type="FLOAT_VECTOR", domain="FACE")
            except Exception:
                attr_uv = None
        if attr_uv and len(attr_uv.data) * 3 == len(colormap_uvs) * 3:
            flat_uv = [v for val in colormap_uvs for v in (val[0], val[1], val[2] if len(val) > 2 else 0.0)]
            attr_uv.data.foreach_set("vector", array.array("f", flat_uv))


def read_face_string_attribute(mesh: Any, name: str) -> List[str]:
    """Read a FACE domain string attribute in bulk."""
    if not hasattr(mesh, "attributes") or not hasattr(mesh, "polygons"):
        return []
    attr = mesh.attributes.get(name)
    num_polys = len(mesh.polygons)
    if not attr or attr.domain != "FACE":
        return [""] * num_polys

    values = []
    for item in attr.data:
        value = item.value
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8", errors="replace")
        values.append(str(value).strip())
    return values if len(values) == num_polys else [""] * num_polys


# Canonical list of UI dropdown enum items generated from libmtk
def _get_biome_enum_items():
    items = [("CUSTOM", "Custom", "Custom Biome (Temperature / Humidity & Color Overrides)")]
    if not HAS_LIBMTK:
        return items + [("PLAINS", "Plains", "Plains Biome")]
    biomes = libmtk_py.get_all_biomes()
    return items + [(b["id"].upper(), b["name"], f"{b['name']} Biome ({b['temperature']} / {b['humidity']})") for b in biomes]

BIOME_ENUM_ITEMS = _get_biome_enum_items()

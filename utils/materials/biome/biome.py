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
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

from ....bridge.material import (
    BiomeResolver,
    get_biome_meta,
    get_all_biomes,
    compute_biome_tint_attributes as bridge_compute_biome_tint_attributes,
)
from ....bridge.engine import has_libmtk


def __getattr__(name: str) -> Any:
    if name == "HAS_LIBMTK":
        return has_libmtk()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

from ..cleaner import clean_obsolete_mesh_attributes
from ..constants import (
    ATTR_BIOME_TINT_DATA,
    ATTR_BIOME_TINT_COLOR,
    ATTR_SOURCE_TEXTURE_KEY,
)

# Canonical Tint Type Identifiers imported from Rust SSOT via bridge.material
from ....bridge.material import (
    TINT_TYPE_DRY_FOLIAGE,
    TINT_TYPE_FOLIAGE,
    TINT_TYPE_GRASS,
    TINT_TYPE_HARDCODED,
    TINT_TYPE_NONE,
    TINT_TYPE_WATER,
)


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
    if not has_libmtk():
        return BiomeResolver()

    # 1. Prioritize instant in-memory loading from .mtkcache package
    from ....bridge.assets import load_biome_resolver_from_cache

    if load_biome_resolver_from_cache is not None:
        cached_resolver = load_biome_resolver_from_cache(prefs)
        if cached_resolver is not None:
            return cached_resolver

    # Fallback: check loose biome_mapping.json if cache directory provided
    target_cache = None
    if cache_dir is not None:
        target_cache = Path(cache_dir)
    else:
        try:
            from ....bridge.assets import get_cache_dir
            target_cache = get_cache_dir(prefs)
        except Exception:
            target_cache = None

    if target_cache:
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
            from ....bridge.assets import get_configured_pack_stack
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
    if not has_libmtk():
        raise RuntimeError("libmtk is required for biome calculations")

    meta = get_biome_meta(biome_name)
    if biome_name.upper() == "CUSTOM":
        temp = custom_temp if custom_temp is not None else meta.get("temperature", 0.8)
        hum = custom_humidity if custom_humidity is not None else meta.get("humidity", 0.4)
        meta["temperature"] = temp
        meta["humidity"] = hum

        # Sample resident colormaps in Rust for base colors
        from ....bridge.material import sample_colormap_colors

        if sample_colormap_colors is not None:
            try:
                sampled = sample_colormap_colors(temp, hum)
                if "grass_linear" in sampled:
                    meta["grass_linear"] = sampled["grass_linear"]
                if "foliage_linear" in sampled:
                    meta["foliage_linear"] = sampled["foliage_linear"]
                if "dry_foliage_linear" in sampled:
                    meta["dry_foliage_linear"] = sampled["dry_foliage_linear"]
                if "grass_hex" in sampled:
                    meta["grass_hex"] = sampled["grass_hex"]
                if "foliage_hex" in sampled:
                    meta["foliage_hex"] = sampled["foliage_hex"]
                if "dry_foliage_hex" in sampled:
                    meta["dry_foliage_hex"] = sampled["dry_foliage_hex"]
            except Exception:
                pass

        if has_custom_grass and custom_grass is not None:
            meta["grass_linear"] = list(custom_grass)
        if has_custom_foliage and custom_foliage is not None:
            meta["foliage_linear"] = list(custom_foliage)
        if has_custom_dry_foliage and custom_dry_foliage is not None:
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
    face_biomes: Optional[List[str]] = None,
) -> Tuple[List[List[float]], List[List[float]]]:
    """
    Compute packed tint weights and resolved Linear RGBA colors for mesh faces using Rust core.
    Returns (packed_tint_data, tint_colors).
    """
    res = bridge_compute_biome_tint_attributes(
        face_texture_keys=face_texture_keys,
        biome_preset=biome_preset,
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
        face_biomes=face_biomes,
    )

    return res["packed_tint_data"], res["tint_colors"]


def compute_biome_tint_attributes_paletted(
    palette: List[str],
    face_indices: Any,
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
) -> Tuple[Any, Any]:
    """Palette-native biome tint computation; never expands per-face strings."""
    from ....bridge.material import compute_biome_tint_attributes_paletted as _native

    return _native(
        palette,
        face_indices,
        biome_preset=biome_preset,
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


def apply_biome_tint_attributes(
    mesh: Any,
    packed_tint_data: List[List[float]],
    tint_colors: List[List[float]],
) -> None:
    """Write Rust-computed biome tint data and color vectors directly to Blender mesh face attributes."""
    if not hasattr(mesh, "attributes") or not hasattr(mesh, "polygons"):
        return

    num_polys = len(mesh.polygons)
    target_len = len(packed_tint_data)
    if target_len == 0 or num_polys != target_len:
        return

    # 1. ATTR_BIOME_TINT_DATA (FLOAT_COLOR, domain=FACE)
    attr_data = mesh.attributes.get(ATTR_BIOME_TINT_DATA)
    if attr_data is not None and (getattr(attr_data, "domain", None) != "FACE" or len(attr_data.data) != target_len):
        try:
            mesh.attributes.remove(attr_data)
        except Exception:
            pass
        attr_data = None
    if attr_data is None:
        try:
            attr_data = mesh.attributes.new(name=ATTR_BIOME_TINT_DATA, type="FLOAT_COLOR", domain="FACE")
        except Exception:
            attr_data = None
    if attr_data and len(attr_data.data) == target_len:
        if HAS_NUMPY and isinstance(packed_tint_data, np.ndarray):
            flat_data = np.ascontiguousarray(packed_tint_data, dtype=np.float32).ravel()
        else:
            flat_data = array.array("f", [c for val in packed_tint_data for c in val])
        attr_data.data.foreach_set("color", flat_data)

    # 2. ATTR_BIOME_TINT_COLOR (FLOAT_COLOR, domain=FACE)
    attr_col = mesh.attributes.get(ATTR_BIOME_TINT_COLOR)
    if attr_col is not None and (getattr(attr_col, "domain", None) != "FACE" or len(attr_col.data) != target_len):
        try:
            mesh.attributes.remove(attr_col)
        except Exception:
            pass
        attr_col = None
    if attr_col is None:
        try:
            attr_col = mesh.attributes.new(name=ATTR_BIOME_TINT_COLOR, type="FLOAT_COLOR", domain="FACE")
        except Exception:
            attr_col = None
    if attr_col and len(attr_col.data) == target_len:
        if HAS_NUMPY and isinstance(tint_colors, np.ndarray):
            flat_col = np.ascontiguousarray(tint_colors, dtype=np.float32).ravel()
        else:
            flat_col = array.array("f", [c for val in tint_colors for c in val])
        attr_col.data.foreach_set("color", flat_col)

    # 3. Purge retired legacy attributes (e.g. mtk_colormap_uv).
    clean_obsolete_mesh_attributes(mesh)


def read_face_string_attribute(mesh: Any, name: str) -> List[str]:
    """Read a FACE domain string attribute in bulk."""
    if not hasattr(mesh, "attributes") or not hasattr(mesh, "polygons"):
        return []
    num_polys = len(mesh.polygons)
    if name == ATTR_SOURCE_TEXTURE_KEY:
        from ....bridge.mesh import resolve_source_texture_keys
        resolved = resolve_source_texture_keys(mesh) if resolve_source_texture_keys is not None else []
        return resolved if len(resolved) == num_polys else [""] * num_polys

    attr = mesh.attributes.get(name)
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
    items = [
        ("WORLD", "World Biome (3D)", "Use true 3D Minecraft world biomes with 5x5 smooth blending"),
        ("CUSTOM", "Custom", "Custom Biome (Temperature / Humidity & Color Overrides)"),
    ]
    if not has_libmtk():
        return items
    biomes = get_all_biomes()
    return items + [(b["id"].upper(), b["name"], f"{b['name']} Biome ({b['temperature']} / {b['humidity']})") for b in biomes]

BIOME_ENUM_ITEMS = _get_biome_enum_items()

"""
Minecraft Biome & Tinting Bridge (Thin Glue Layer to Rust libmtk Core).
All mathematical calculations, colormap sampling coordinates, model JSON tint parsing,
and multi-threaded mesh attribute generation are executed inside libmtk_py.
"""

from __future__ import annotations

import array
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
        def get_tint_info(self, texture_name: str, block_name: Optional[str] = None, tint_index: Optional[int] = None) -> dict:
            return {"tint_type": 0, "tint_category": "none", "tint_weight": 0.0, "base_tint_weight": 0.0, "overlay_tint_weight": 0.0}
        def get_overlay_texture(self, texture_stem: str) -> Optional[str]:
            return None


def get_biome_colors(biome_name: str, pack_stack: Any = None) -> Dict[str, Any]:
    """Retrieve canonical metadata, temperature, humidity, and Linear RGBA colors from Rust core."""
    if not HAS_LIBMTK:
        return {
            "id": biome_name.lower(),
            "name": biome_name,
            "temperature": 0.8,
            "humidity": 0.4,
            "grass_linear": [0.27, 0.50, 0.09, 1.0],
            "foliage_linear": [0.18, 0.40, 0.03, 1.0],
            "dry_foliage_linear": [0.36, 0.22, 0.06, 1.0],
            "water_linear": [0.05, 0.18, 0.78, 1.0],
            "colormap_uv": [0.2, 0.32],
            "has_custom_grass": False,
            "has_custom_foliage": False,
            "has_custom_dry_foliage": False,
        }
    return libmtk_py.get_biome_meta(biome_name)


def compute_biome_tint_attributes(
    face_texture_keys: List[str],
    biome_preset: Union[str, List[Tuple[str, float]]] = "PLAINS",
    resolver: Optional[Any] = None,
) -> Tuple[List[List[float]], List[List[float]], List[List[float]]]:
    """
    Compute packed tint weights, colors, and colormap UV coordinates for mesh faces using Rust core.
    Returns (packed_tint_data, tint_colors, colormap_uvs).
    """
    if not HAS_LIBMTK:
        n = len(face_texture_keys)
        return (
            [[0.0, 0.0, 0.0, 0.0]] * n,
            [[1.0, 1.0, 1.0, 1.0]] * n,
            [[0.2, 0.32, 0.0]] * n,
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
    if not HAS_LIBMTK:
        return [("PLAINS", "Plains", "Plains Biome")]
    biomes = libmtk_py.get_all_biomes()
    return [(b["id"].upper(), b["name"], f"{b['name']} Biome ({b['temperature']} / {b['humidity']})") for b in biomes]

BIOME_ENUM_ITEMS = _get_biome_enum_items()

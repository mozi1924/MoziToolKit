"""
Minecraft Biome Definitions, Tint Classification, and Block Model JSON Resolver.
Provides canonical vanilla 26.2 biome palettes, colormap sampling algorithms,
hardcoded block colors, and multi-biome transition blending.
"""

from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List, Union


# --- Color Conversion Utilities ---

def hex_to_rgb(hex_str: str) -> tuple[float, float, float]:
    """Convert hex color string (e.g. '#91BD59' or '91BD59') to sRGB float tuple (0..1)."""
    clean = hex_str.strip().lstrip("#")
    if len(clean) in (6, 8):
        r = int(clean[0:2], 16) / 255.0
        g = int(clean[2:4], 16) / 255.0
        b = int(clean[4:6], 16) / 255.0
        return (r, g, b)
    return (1.0, 1.0, 1.0)


def srgb_to_linear(c: float) -> float:
    """Convert sRGB component (0..1) to Linear RGB component."""
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def hex_to_linear_rgb(hex_str: str) -> tuple[float, float, float]:
    """Convert hex color string to Linear RGB float tuple for Blender shaders."""
    sr, sg, sb = hex_to_rgb(hex_str)
    return (srgb_to_linear(sr), srgb_to_linear(sg), srgb_to_linear(sb))


def hex_to_rgba(hex_str: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    """Convert hex color string to sRGB RGBA tuple."""
    clean = hex_str.strip().lstrip("#")
    if len(clean) == 8:
        r = int(clean[0:2], 16) / 255.0
        g = int(clean[2:4], 16) / 255.0
        b = int(clean[4:6], 16) / 255.0
        a = int(clean[6:8], 16) / 255.0
        return (r, g, b, a)
    r, g, b = hex_to_rgb(hex_str)
    return (r, g, b, alpha)


def hex_to_linear_rgba(hex_str: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    """Convert hex color string to Linear RGBA tuple for Blender shaders."""
    clean = hex_str.strip().lstrip("#")
    if len(clean) == 8:
        sr, sg, sb, a = hex_to_rgba(hex_str)
        return (srgb_to_linear(sr), srgb_to_linear(sg), srgb_to_linear(sb), a)
    lr, lg, lb = hex_to_linear_rgb(hex_str)
    return (lr, lg, lb, alpha)


def linear_to_srgb(c: float) -> float:
    """Convert Linear RGB component (0..1) to sRGB component."""
    if c <= 0.0031308:
        return c * 12.92
    return 1.055 * (c ** (1.0 / 2.4)) - 0.055


def linear_rgba_to_hex(rgba: tuple[float, ...]) -> str:
    """Convert Linear RGBA or Linear RGB tuple to hex color string."""
    r = max(0.0, min(1.0, linear_to_srgb(rgba[0])))
    g = max(0.0, min(1.0, linear_to_srgb(rgba[1])))
    b = max(0.0, min(1.0, linear_to_srgb(rgba[2])))
    return f"#{int(round(r * 255)):02X}{int(round(g * 255)):02X}{int(round(b * 255)):02X}"


# --- Minecraft Colormap Coordinates & Sampling ---

def get_colormap_uv(temperature: float, downfall: float) -> tuple[float, float]:
    """
    Calculate Minecraft standard triangular Colormap UV coordinates from Temperature and Downfall (Humidity).
    In Minecraft ColorMapColorUtil:
      temp = clamp(temp, 0.0, 1.0)
      downfall = clamp(downfall, 0.0, 1.0) * temp
      U = 1.0 - temp
      V (bottom-left origin) = downfall = hum * temp
    Returns (U, V) in range [0.0, 1.0].
    """
    temp = max(0.0, min(1.0, float(temperature)))
    hum = max(0.0, min(1.0, float(downfall)))
    u = 1.0 - temp
    v = hum * temp
    return (u, v)


def sample_colormap_pixel(
    image_data: Any,
    temperature: float,
    downfall: float,
    default_color: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> tuple[float, float, float]:
    """
    Sample an sRGB color (0..1) from a 256x256 colormap (PIL Image or NumPy array or byte array)
    using canonical Minecraft coordinate indexing:
      i = int((1.0 - temp) * 255.0)
      j = int((1.0 - (downfall * temp)) * 255.0)  # row 0 at top
    """
    if image_data is None:
        return default_color
    temp = max(0.0, min(1.0, float(temperature)))
    hum = max(0.0, min(1.0, float(downfall)))
    adj_downfall = hum * temp
    i = max(0, min(255, int((1.0 - temp) * 255.0)))
    j = max(0, min(255, int((1.0 - adj_downfall) * 255.0)))

    try:
        # Handle PIL Image
        if hasattr(image_data, "getpixel"):
            px = image_data.getpixel((i, j))
            if isinstance(px, (int, float)):
                return (px / 255.0, px / 255.0, px / 255.0)
            return (px[0] / 255.0, px[1] / 255.0, px[2] / 255.0)
        # Handle 2D/3D array or list
        if hasattr(image_data, "shape"):
            px = image_data[j, i]
            return (float(px[0]) / 255.0, float(px[1]) / 255.0, float(px[2]) / 255.0)
    except Exception:
        pass
    return default_color


# --- Canonical Minecraft 26.2 Biome Palettes Registry (66 Biomes) ---
BIOME_PALETTES: dict[str, dict[str, Any]] = {
    "BADLANDS": {
        "id": "badlands",
        "name": "Badlands",
        "grass": "#90814D",
        "foliage": "#9E814D",
        "dry_foliage": "#A38046",
        "water": "#3F76E4",
        "temperature": 2.0,
        "humidity": 0.0,
        "modifier": "none",
        "has_custom_grass": True,
        "has_custom_foliage": True,
        "has_custom_dry_foliage": False
    },
    "BAMBOO_JUNGLE": {
        "id": "bamboo_jungle",
        "name": "Bamboo Jungle",
        "grass": "#59C93C",
        "foliage": "#30BB0B",
        "dry_foliage": "#A36346",
        "water": "#3F76E4",
        "temperature": 0.95,
        "humidity": 0.9,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "BASALT_DELTAS": {
        "id": "basalt_deltas",
        "name": "Basalt Deltas",
        "grass": "#BFB755",
        "foliage": "#AEA42A",
        "dry_foliage": "#A38046",
        "water": "#3F76E4",
        "temperature": 2.0,
        "humidity": 0.0,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "BEACH": {
        "id": "beach",
        "name": "Beach",
        "grass": "#91BD59",
        "foliage": "#77AB2F",
        "dry_foliage": "#A37546",
        "water": "#3F76E4",
        "temperature": 0.8,
        "humidity": 0.4,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "BIRCH_FOREST": {
        "id": "birch_forest",
        "name": "Birch Forest",
        "grass": "#88BB67",
        "foliage": "#6BA941",
        "dry_foliage": "#A37246",
        "water": "#3F76E4",
        "temperature": 0.6,
        "humidity": 0.6,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "CHERRY_GROVE": {
        "id": "cherry_grove",
        "name": "Cherry Grove",
        "grass": "#B6DB61",
        "foliage": "#B6DB61",
        "dry_foliage": "#A17148",
        "water": "#5DB7EF",
        "temperature": 0.5,
        "humidity": 0.8,
        "modifier": "none",
        "has_custom_grass": True,
        "has_custom_foliage": True,
        "has_custom_dry_foliage": False
    },
    "COLD_OCEAN": {
        "id": "cold_ocean",
        "name": "Cold Ocean",
        "grass": "#8EB971",
        "foliage": "#71A74D",
        "dry_foliage": "#A17448",
        "water": "#3D57D6",
        "temperature": 0.5,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "CRIMSON_FOREST": {
        "id": "crimson_forest",
        "name": "Crimson Forest",
        "grass": "#BFB755",
        "foliage": "#AEA42A",
        "dry_foliage": "#A38046",
        "water": "#3F76E4",
        "temperature": 2.0,
        "humidity": 0.0,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "DARK_FOREST": {
        "id": "dark_forest",
        "name": "Dark Forest",
        "grass": "#507A32",
        "foliage": "#59AE30",
        "dry_foliage": "#7B5334",
        "water": "#3F76E4",
        "temperature": 0.7,
        "humidity": 0.8,
        "modifier": "dark_forest",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": True
    },
    "DEEP_COLD_OCEAN": {
        "id": "deep_cold_ocean",
        "name": "Deep Cold Ocean",
        "grass": "#8EB971",
        "foliage": "#71A74D",
        "dry_foliage": "#A17448",
        "water": "#3D57D6",
        "temperature": 0.5,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "DEEP_DARK": {
        "id": "deep_dark",
        "name": "Deep Dark",
        "grass": "#91BD59",
        "foliage": "#77AB2F",
        "dry_foliage": "#A37546",
        "water": "#3F76E4",
        "temperature": 0.8,
        "humidity": 0.4,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "DEEP_FROZEN_OCEAN": {
        "id": "deep_frozen_ocean",
        "name": "Deep Frozen Ocean",
        "grass": "#8EB971",
        "foliage": "#71A74D",
        "dry_foliage": "#A17448",
        "water": "#3938C9",
        "temperature": 0.5,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "DEEP_LUKEWARM_OCEAN": {
        "id": "deep_lukewarm_ocean",
        "name": "Deep Lukewarm Ocean",
        "grass": "#8EB971",
        "foliage": "#71A74D",
        "dry_foliage": "#A17448",
        "water": "#45ADF2",
        "temperature": 0.5,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "DEEP_OCEAN": {
        "id": "deep_ocean",
        "name": "Deep Ocean",
        "grass": "#8EB971",
        "foliage": "#71A74D",
        "dry_foliage": "#A17448",
        "water": "#3F76E4",
        "temperature": 0.5,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "DESERT": {
        "id": "desert",
        "name": "Desert",
        "grass": "#BFB755",
        "foliage": "#AEA42A",
        "dry_foliage": "#A38046",
        "water": "#3F76E4",
        "temperature": 2.0,
        "humidity": 0.0,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "DRIPSTONE_CAVES": {
        "id": "dripstone_caves",
        "name": "Dripstone Caves",
        "grass": "#91BD59",
        "foliage": "#77AB2F",
        "dry_foliage": "#A37546",
        "water": "#3F76E4",
        "temperature": 0.8,
        "humidity": 0.4,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "END_BARRENS": {
        "id": "end_barrens",
        "name": "End Barrens",
        "grass": "#8EB971",
        "foliage": "#71A74D",
        "dry_foliage": "#A17448",
        "water": "#3F76E4",
        "temperature": 0.5,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "END_HIGHLANDS": {
        "id": "end_highlands",
        "name": "End Highlands",
        "grass": "#8EB971",
        "foliage": "#71A74D",
        "dry_foliage": "#A17448",
        "water": "#3F76E4",
        "temperature": 0.5,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "END_MIDLANDS": {
        "id": "end_midlands",
        "name": "End Midlands",
        "grass": "#8EB971",
        "foliage": "#71A74D",
        "dry_foliage": "#A17448",
        "water": "#3F76E4",
        "temperature": 0.5,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "ERODED_BADLANDS": {
        "id": "eroded_badlands",
        "name": "Eroded Badlands",
        "grass": "#90814D",
        "foliage": "#9E814D",
        "dry_foliage": "#A38046",
        "water": "#3F76E4",
        "temperature": 2.0,
        "humidity": 0.0,
        "modifier": "none",
        "has_custom_grass": True,
        "has_custom_foliage": True,
        "has_custom_dry_foliage": False
    },
    "FLOWER_FOREST": {
        "id": "flower_forest",
        "name": "Flower Forest",
        "grass": "#79C05A",
        "foliage": "#59AE30",
        "dry_foliage": "#A36D46",
        "water": "#3F76E4",
        "temperature": 0.7,
        "humidity": 0.8,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "FOREST": {
        "id": "forest",
        "name": "Forest",
        "grass": "#79C05A",
        "foliage": "#59AE30",
        "dry_foliage": "#A36D46",
        "water": "#3F76E4",
        "temperature": 0.7,
        "humidity": 0.8,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "FROZEN_OCEAN": {
        "id": "frozen_ocean",
        "name": "Frozen Ocean",
        "grass": "#80B497",
        "foliage": "#60A17B",
        "dry_foliage": "#8F7A5A",
        "water": "#3938C9",
        "temperature": 0.0,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "FROZEN_PEAKS": {
        "id": "frozen_peaks",
        "name": "Frozen Peaks",
        "grass": "#80B497",
        "foliage": "#60A17B",
        "dry_foliage": "#8F7A5A",
        "water": "#3F76E4",
        "temperature": -0.7,
        "humidity": 0.9,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "FROZEN_RIVER": {
        "id": "frozen_river",
        "name": "Frozen River",
        "grass": "#80B497",
        "foliage": "#60A17B",
        "dry_foliage": "#8F7A5A",
        "water": "#3938C9",
        "temperature": 0.0,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "GROVE": {
        "id": "grove",
        "name": "Grove",
        "grass": "#80B497",
        "foliage": "#60A17B",
        "dry_foliage": "#8F7A5A",
        "water": "#3F76E4",
        "temperature": -0.2,
        "humidity": 0.8,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "ICE_SPIKES": {
        "id": "ice_spikes",
        "name": "Ice Spikes",
        "grass": "#80B497",
        "foliage": "#60A17B",
        "dry_foliage": "#8F7A5A",
        "water": "#3F76E4",
        "temperature": 0.0,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "JAGGED_PEAKS": {
        "id": "jagged_peaks",
        "name": "Jagged Peaks",
        "grass": "#80B497",
        "foliage": "#60A17B",
        "dry_foliage": "#8F7A5A",
        "water": "#3F76E4",
        "temperature": -0.7,
        "humidity": 0.9,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "JUNGLE": {
        "id": "jungle",
        "name": "Jungle",
        "grass": "#59C93C",
        "foliage": "#30BB0B",
        "dry_foliage": "#A36346",
        "water": "#3F76E4",
        "temperature": 0.95,
        "humidity": 0.9,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "LUKEWARM_OCEAN": {
        "id": "lukewarm_ocean",
        "name": "Lukewarm Ocean",
        "grass": "#8EB971",
        "foliage": "#71A74D",
        "dry_foliage": "#A17448",
        "water": "#45ADF2",
        "temperature": 0.5,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "LUSH_CAVES": {
        "id": "lush_caves",
        "name": "Lush Caves",
        "grass": "#8EB971",
        "foliage": "#71A74D",
        "dry_foliage": "#A17448",
        "water": "#3F76E4",
        "temperature": 0.5,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "MANGROVE_SWAMP": {
        "id": "mangrove_swamp",
        "name": "Mangrove Swamp",
        "grass": "#6A7039",
        "foliage": "#8DB127",
        "dry_foliage": "#7B5334",
        "water": "#3A7A6A",
        "temperature": 0.8,
        "humidity": 0.9,
        "modifier": "swamp",
        "has_custom_grass": True,
        "has_custom_foliage": True,
        "has_custom_dry_foliage": True
    },
    "MEADOW": {
        "id": "meadow",
        "name": "Meadow",
        "grass": "#83BB6D",
        "foliage": "#64A948",
        "dry_foliage": "#A17148",
        "water": "#0E4ECF",
        "temperature": 0.5,
        "humidity": 0.8,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "MUSHROOM_FIELDS": {
        "id": "mushroom_fields",
        "name": "Mushroom Fields",
        "grass": "#55C93F",
        "foliage": "#2BBB0F",
        "dry_foliage": "#A36246",
        "water": "#3F76E4",
        "temperature": 0.9,
        "humidity": 1.0,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "NETHER_WASTES": {
        "id": "nether_wastes",
        "name": "Nether Wastes",
        "grass": "#BFB755",
        "foliage": "#AEA42A",
        "dry_foliage": "#A38046",
        "water": "#3F76E4",
        "temperature": 2.0,
        "humidity": 0.0,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "OCEAN": {
        "id": "ocean",
        "name": "Ocean",
        "grass": "#8EB971",
        "foliage": "#71A74D",
        "dry_foliage": "#A17448",
        "water": "#3F76E4",
        "temperature": 0.5,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "OLD_GROWTH_BIRCH_FOREST": {
        "id": "old_growth_birch_forest",
        "name": "Old Growth Birch Forest",
        "grass": "#88BB67",
        "foliage": "#6BA941",
        "dry_foliage": "#A37246",
        "water": "#3F76E4",
        "temperature": 0.6,
        "humidity": 0.6,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "OLD_GROWTH_PINE_TAIGA": {
        "id": "old_growth_pine_taiga",
        "name": "Old Growth Pine Taiga",
        "grass": "#86B87F",
        "foliage": "#68A55F",
        "dry_foliage": "#9C754D",
        "water": "#3F76E4",
        "temperature": 0.3,
        "humidity": 0.8,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "OLD_GROWTH_SPRUCE_TAIGA": {
        "id": "old_growth_spruce_taiga",
        "name": "Old Growth Spruce Taiga",
        "grass": "#86B783",
        "foliage": "#68A464",
        "dry_foliage": "#9A764F",
        "water": "#3F76E4",
        "temperature": 0.25,
        "humidity": 0.8,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "PALE_GARDEN": {
        "id": "pale_garden",
        "name": "Pale Garden",
        "grass": "#778272",
        "foliage": "#878D76",
        "dry_foliage": "#A0A69C",
        "water": "#76889D",
        "temperature": 0.7,
        "humidity": 0.8,
        "modifier": "none",
        "has_custom_grass": True,
        "has_custom_foliage": True,
        "has_custom_dry_foliage": True
    },
    "PLAINS": {
        "id": "plains",
        "name": "Plains",
        "grass": "#91BD59",
        "foliage": "#77AB2F",
        "dry_foliage": "#A37546",
        "water": "#3F76E4",
        "temperature": 0.8,
        "humidity": 0.4,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "RIVER": {
        "id": "river",
        "name": "River",
        "grass": "#8EB971",
        "foliage": "#71A74D",
        "dry_foliage": "#A17448",
        "water": "#3F76E4",
        "temperature": 0.5,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "SAVANNA": {
        "id": "savanna",
        "name": "Savanna",
        "grass": "#BFB755",
        "foliage": "#AEA42A",
        "dry_foliage": "#A38046",
        "water": "#3F76E4",
        "temperature": 2.0,
        "humidity": 0.0,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "SAVANNA_PLATEAU": {
        "id": "savanna_plateau",
        "name": "Savanna Plateau",
        "grass": "#BFB755",
        "foliage": "#AEA42A",
        "dry_foliage": "#A38046",
        "water": "#3F76E4",
        "temperature": 2.0,
        "humidity": 0.0,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "SMALL_END_ISLANDS": {
        "id": "small_end_islands",
        "name": "Small End Islands",
        "grass": "#8EB971",
        "foliage": "#71A74D",
        "dry_foliage": "#A17448",
        "water": "#3F76E4",
        "temperature": 0.5,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "SNOWY_BEACH": {
        "id": "snowy_beach",
        "name": "Snowy Beach",
        "grass": "#83B593",
        "foliage": "#64A278",
        "dry_foliage": "#917958",
        "water": "#3D57D6",
        "temperature": 0.05,
        "humidity": 0.3,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "SNOWY_PLAINS": {
        "id": "snowy_plains",
        "name": "Snowy Plains",
        "grass": "#80B497",
        "foliage": "#60A17B",
        "dry_foliage": "#8F7A5A",
        "water": "#3F76E4",
        "temperature": 0.0,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "SNOWY_SLOPES": {
        "id": "snowy_slopes",
        "name": "Snowy Slopes",
        "grass": "#80B497",
        "foliage": "#60A17B",
        "dry_foliage": "#8F7A5A",
        "water": "#3F76E4",
        "temperature": -0.3,
        "humidity": 0.9,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "SNOWY_TAIGA": {
        "id": "snowy_taiga",
        "name": "Snowy Taiga",
        "grass": "#80B497",
        "foliage": "#60A17B",
        "dry_foliage": "#8F7A5A",
        "water": "#3D57D6",
        "temperature": -0.5,
        "humidity": 0.4,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "SOUL_SAND_VALLEY": {
        "id": "soul_sand_valley",
        "name": "Soul Sand Valley",
        "grass": "#BFB755",
        "foliage": "#AEA42A",
        "dry_foliage": "#A38046",
        "water": "#3F76E4",
        "temperature": 2.0,
        "humidity": 0.0,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "SPARSE_JUNGLE": {
        "id": "sparse_jungle",
        "name": "Sparse Jungle",
        "grass": "#64C73F",
        "foliage": "#3EB80F",
        "dry_foliage": "#A36646",
        "water": "#3F76E4",
        "temperature": 0.95,
        "humidity": 0.8,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "STONY_PEAKS": {
        "id": "stony_peaks",
        "name": "Stony Peaks",
        "grass": "#9ABE4B",
        "foliage": "#82AC1E",
        "dry_foliage": "#A37946",
        "water": "#3F76E4",
        "temperature": 1.0,
        "humidity": 0.3,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "STONY_SHORE": {
        "id": "stony_shore",
        "name": "Stony Shore",
        "grass": "#8AB689",
        "foliage": "#6DA36B",
        "dry_foliage": "#967753",
        "water": "#3F76E4",
        "temperature": 0.2,
        "humidity": 0.3,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "SULFUR_CAVES": {
        "id": "sulfur_caves",
        "name": "Sulfur Caves",
        "grass": "#ABA64F",
        "foliage": "#77AB2F",
        "dry_foliage": "#A37546",
        "water": "#34BF89",
        "temperature": 0.8,
        "humidity": 0.4,
        "modifier": "none",
        "has_custom_grass": True,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "SUNFLOWER_PLAINS": {
        "id": "sunflower_plains",
        "name": "Sunflower Plains",
        "grass": "#91BD59",
        "foliage": "#77AB2F",
        "dry_foliage": "#A37546",
        "water": "#3F76E4",
        "temperature": 0.8,
        "humidity": 0.4,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "SWAMP": {
        "id": "swamp",
        "name": "Swamp",
        "grass": "#6A7039",
        "foliage": "#6A7039",
        "dry_foliage": "#7B5334",
        "water": "#617B64",
        "temperature": 0.8,
        "humidity": 0.9,
        "modifier": "swamp",
        "has_custom_grass": True,
        "has_custom_foliage": True,
        "has_custom_dry_foliage": True
    },
    "TAIGA": {
        "id": "taiga",
        "name": "Taiga",
        "grass": "#86B783",
        "foliage": "#68A464",
        "dry_foliage": "#9A764F",
        "water": "#3F76E4",
        "temperature": 0.25,
        "humidity": 0.8,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "THE_END": {
        "id": "the_end",
        "name": "The End",
        "grass": "#8EB971",
        "foliage": "#71A74D",
        "dry_foliage": "#A17448",
        "water": "#3F76E4",
        "temperature": 0.5,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "THE_VOID": {
        "id": "the_void",
        "name": "The Void",
        "grass": "#8EB971",
        "foliage": "#71A74D",
        "dry_foliage": "#A17448",
        "water": "#3F76E4",
        "temperature": 0.5,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "WARM_OCEAN": {
        "id": "warm_ocean",
        "name": "Warm Ocean",
        "grass": "#8EB971",
        "foliage": "#71A74D",
        "dry_foliage": "#A17448",
        "water": "#43D5EE",
        "temperature": 0.5,
        "humidity": 0.5,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "WARPED_FOREST": {
        "id": "warped_forest",
        "name": "Warped Forest",
        "grass": "#BFB755",
        "foliage": "#AEA42A",
        "dry_foliage": "#A38046",
        "water": "#3F76E4",
        "temperature": 2.0,
        "humidity": 0.0,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "WINDSWEPT_FOREST": {
        "id": "windswept_forest",
        "name": "Windswept Forest",
        "grass": "#8AB689",
        "foliage": "#6DA36B",
        "dry_foliage": "#967753",
        "water": "#3F76E4",
        "temperature": 0.2,
        "humidity": 0.3,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "WINDSWEPT_GRAVELLY_HILLS": {
        "id": "windswept_gravelly_hills",
        "name": "Windswept Gravelly Hills",
        "grass": "#8AB689",
        "foliage": "#6DA36B",
        "dry_foliage": "#967753",
        "water": "#3F76E4",
        "temperature": 0.2,
        "humidity": 0.3,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "WINDSWEPT_HILLS": {
        "id": "windswept_hills",
        "name": "Windswept Hills",
        "grass": "#8AB689",
        "foliage": "#6DA36B",
        "dry_foliage": "#967753",
        "water": "#3F76E4",
        "temperature": 0.2,
        "humidity": 0.3,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "WINDSWEPT_SAVANNA": {
        "id": "windswept_savanna",
        "name": "Windswept Savanna",
        "grass": "#BFB755",
        "foliage": "#AEA42A",
        "dry_foliage": "#A38046",
        "water": "#3F76E4",
        "temperature": 2.0,
        "humidity": 0.0,
        "modifier": "none",
        "has_custom_grass": False,
        "has_custom_foliage": False,
        "has_custom_dry_foliage": False
    },
    "WOODED_BADLANDS": {
        "id": "wooded_badlands",
        "name": "Wooded Badlands",
        "grass": "#90814D",
        "foliage": "#9E814D",
        "dry_foliage": "#A38046",
        "water": "#3F76E4",
        "temperature": 2.0,
        "humidity": 0.0,
        "modifier": "none",
        "has_custom_grass": True,
        "has_custom_foliage": True,
        "has_custom_dry_foliage": False
    }
}

# Hardcoded block-specific tints (independent of biome, or special formula)
HARDCODED_BLOCK_TINTS: dict[str, str] = {
    "spruce_leaves": "#619961",
    "birch_leaves": "#80A755",
    "lily_pad": "#208030",
    "attached_melon_stem": "#E0C71C",
    "attached_pumpkin_stem": "#E0C71C",
    "melon_stem": "#E0C71C",
    "pumpkin_stem": "#E0C71C",
}

# Canonical Minecraft 26.2 Block Colors Registry
# Maps block stem to list of layer definitions (tuple of (category, weight_or_hex))
BLOCK_TINT_REGISTRY: dict[str, list[tuple[str, Any]]] = {
    # Grass & Flora
    "grass_block": [("grass", 1.0)],
    "short_grass": [("grass", 1.0)],
    "grass": [("grass", 1.0)],
    "tall_grass": [("grass", 1.0)],
    "fern": [("grass", 1.0)],
    "large_fern": [("grass", 1.0)],
    "potted_fern": [("grass", 1.0)],
    "bush": [("grass", 1.0)],
    "sugar_cane": [("grass", 1.0)],
    # Multi-layer Flora (Layer 0 = Petals/Blank, Layer 1 = Stem/Grass)
    "pink_petals": [("none", 0.0), ("grass", 1.0)],
    "wildflowers": [("none", 0.0), ("grass", 1.0)],
    "bamboo": [("grass", 1.0)],
    # Foliage
    "oak_leaves": [("foliage", 1.0)],
    "jungle_leaves": [("foliage", 1.0)],
    "acacia_leaves": [("foliage", 1.0)],
    "dark_oak_leaves": [("foliage", 1.0)],
    "vine": [("foliage", 1.0)],
    "mangrove_leaves": [("foliage", 1.0)],
    # Dry Foliage
    "leaf_litter": [("dry_foliage", 1.0)],
    "pale_hanging_moss": [("dry_foliage", 1.0)],
    "pale_hanging_moss_tip": [("dry_foliage", 1.0)],
    "pale_oak_leaves": [("none", 1.0)],
    # Water & Fluid
    "water": [("water", 1.0)],
    "flowing_water": [("water", 1.0)],
    "water_still": [("water", 1.0)],
    "water_flow": [("water", 1.0)],
    "water_cauldron": [("water", 1.0)],
    "bubble_column": [("water", 1.0)],
    # Hardcoded tints
    "spruce_leaves": [("hardcoded", "#619961")],
    "birch_leaves": [("hardcoded", "#80A755")],
    "lily_pad": [("hardcoded", "#208030")],
    "attached_melon_stem": [("hardcoded", "#E0C71C")],
    "attached_pumpkin_stem": [("hardcoded", "#E0C71C")],
    "melon_stem": [("hardcoded", "#E0C71C")],
    "pumpkin_stem": [("hardcoded", "#E0C71C")],
}


# Known paired overlay textures (base -> overlay)

KNOWN_OVERLAY_PAIRS: dict[str, str] = {
    "grass_block_side": "grass_block_side_overlay",
    "dirt_path_side": "dirt_path_side_overlay",
}

# Tint categories enum values
TINT_TYPE_NONE = 0
TINT_TYPE_GRASS = 1
TINT_TYPE_FOLIAGE = 2
TINT_TYPE_WATER = 3
TINT_TYPE_HARDCODED = 4
TINT_TYPE_DRY_FOLIAGE = 5

# Vanilla texture stems with a biome colour provider.
KNOWN_GRASS_STEMS = frozenset({
    "grass_block_top",
    "grass_block_side_overlay",
    "short_grass",
    "grass",
    "tall_grass_top",
    "tall_grass_bottom",
    "tall_grass",
    "fern",
    "large_fern_top",
    "large_fern_bottom",
    "large_fern",
    "sugar_cane",
    "potted_fern",
    "bush",
    "pink_petals_stem",
    "wildflowers_stem",
    "bamboo_large_leaves",
    "bamboo_small_leaves",
    "bamboo_stage0",
})

KNOWN_FOLIAGE_STEMS = frozenset({
    "oak_leaves",
    "jungle_leaves",
    "acacia_leaves",
    "dark_oak_leaves",
    "vine",
    "mangrove_leaves",
})

KNOWN_DRY_FOLIAGE_STEMS = frozenset({
    "leaf_litter",
    "pale_hanging_moss",
    "pale_hanging_moss_tip",
})

KNOWN_WATER_STEMS = frozenset({
    "water_still",
    "water_flow",
    "water_overlay",
})


def classify_tint_category(
    clean_stem: str,
    block_name: Optional[str] = None,
    tint_index: Optional[int] = None,
) -> str:
    """
    Classify a texture stem and/or block name into a tint category:
    'grass', 'foliage', 'dry_foliage', 'water', 'hardcoded', or 'none'.
    Respects BlockColors semantic registration and face tintindex.
    """
    if not clean_stem and not block_name:
        return "none"

    from ..specialized import is_firefly_bush_tint_exempt
    if is_firefly_bush_tint_exempt(clean_stem) or (block_name and is_firefly_bush_tint_exempt(block_name)):
        return "none"

    # 1. Check explicit block-level registration if block_name is provided
    if block_name:
        clean_block = block_name.lower().removeprefix("minecraft:").removeprefix("block/").removeprefix("models/block/").removeprefix("models/")
        if "[" in clean_block:
            clean_block = clean_block.split("[", 1)[0]
        if clean_block in BLOCK_TINT_REGISTRY:
            layers = BLOCK_TINT_REGISTRY[clean_block]
            if tint_index is not None:
                if tint_index < 0:
                    return "none"
                if tint_index < len(layers):
                    return layers[tint_index][0]
                return layers[-1][0]
            for cat, _ in layers:
                if cat != "none":
                    return cat

    # 2. Check canonical known stems
    stem_norm = clean_stem.lower().removeprefix("minecraft:").removeprefix("block/") if clean_stem else ""
    if ":" in stem_norm:
        stem_norm = stem_norm.split(":", 1)[1]

    if stem_norm in HARDCODED_BLOCK_TINTS:
        return "hardcoded"
    if stem_norm in KNOWN_GRASS_STEMS:
        return "grass"
    if stem_norm in KNOWN_FOLIAGE_STEMS:
        return "foliage"
    if stem_norm in KNOWN_DRY_FOLIAGE_STEMS:
        return "dry_foliage"
    if stem_norm in KNOWN_WATER_STEMS:
        return "water"

    # 3. Heuristic fallback for custom models
    if "seagrass" in stem_norm or "kelp" in stem_norm:
        return "none"

    if "leaves" in stem_norm:
        if "spruce" in stem_norm:
            return "hardcoded"
        if "birch" in stem_norm:
            return "hardcoded"
        if any(w in stem_norm for w in ("cherry", "azalea", "pale_oak")):
            return "none"
        return "foliage"

    from ..specialized import is_firefly_bush_tint_exempt
    if is_firefly_bush_tint_exempt(stem_norm):
        return "none"

    if any(stem_norm.endswith(w) for w in ("_grass", "_fern", "_vine")) or stem_norm in ("bush", "potted_bush"):
        return "grass"

    return "none"


def blend_biome_colors(
    biome_weights: list[tuple[Union[str, dict], float]],
    tint_type: str = "grass",
) -> tuple[float, float, float, float]:
    """
    Compute a smooth blended Linear RGBA color across multiple weighted biomes (群系过渡).
    biome_weights: List of tuples (biome_preset_or_dict, weight).
    tint_type: 'grass', 'foliage', 'dry_foliage', or 'water'.
    """
    if not biome_weights:
        return (1.0, 1.0, 1.0, 1.0)

    total_weight = sum(w for _, w in biome_weights)
    if total_weight <= 0.0:
        return (1.0, 1.0, 1.0, 1.0)

    r_acc, g_acc, b_acc, a_acc = 0.0, 0.0, 0.0, 1.0
    key_map = {
        "grass": "grass_linear",
        "foliage": "foliage_linear",
        "dry_foliage": "dry_foliage_linear",
        "water": "water_linear",
    }
    col_key = key_map.get(tint_type.lower(), "grass_linear")

    for biome_entry, weight in biome_weights:
        if weight <= 0.0:
            continue
        norm_w = weight / total_weight
        if isinstance(biome_entry, dict):
            # Dynamic dictionary with hex or rgba
            hex_str = biome_entry.get(tint_type.lower()) or biome_entry.get("grass") or "#91BD59"
            col = hex_to_linear_rgba(hex_str)
        else:
            colors = get_biome_colors(str(biome_entry))
            col = colors.get(col_key, (1.0, 1.0, 1.0, 1.0))

        r_acc += col[0] * norm_w
        g_acc += col[1] * norm_w
        b_acc += col[2] * norm_w

    return (r_acc, g_acc, b_acc, a_acc)


def get_biome_colors(biome_name: str, pack_stack: Any = None) -> dict[str, Any]:
    """
    Look up biome color data by preset name or ID.
    If pack_stack is provided, checks for stack-level custom colormaps / biome overrides first.
    Returns dictionary with hex and linear RGBA values for grass, foliage, dry_foliage, and water.
    """
    name_upper = (biome_name or "PLAINS").strip().upper().replace(" ", "_").replace("MINECRAFT:", "")
    if pack_stack is not None and hasattr(pack_stack, "get_biome_data"):
        stack_data = pack_stack.get_biome_data(name_upper)
        if stack_data:
            return stack_data

    palette = BIOME_PALETTES.get(name_upper)
    if not palette:
        for k, v in BIOME_PALETTES.items():
            if v.get("id") == biome_name.lower().removeprefix("minecraft:"):
                palette = v
                break
    if not palette:
        palette = BIOME_PALETTES["PLAINS"]

    grass_hex = palette.get("grass", "#91BD59")
    foliage_hex = palette.get("foliage", "#77AB2F")
    dry_foliage_hex = palette.get("dry_foliage", "#A37546")
    water_hex = palette.get("water", "#3F76E4")

    return {
        "id": palette.get("id", name_upper.lower()),
        "name": palette.get("name", name_upper.capitalize()),
        "grass_hex": grass_hex,
        "foliage_hex": foliage_hex,
        "dry_foliage_hex": dry_foliage_hex,
        "water_hex": water_hex,
        "grass_linear": hex_to_linear_rgba(grass_hex),
        "foliage_linear": hex_to_linear_rgba(foliage_hex),
        "dry_foliage_linear": hex_to_linear_rgba(dry_foliage_hex),
        "water_linear": hex_to_linear_rgba(water_hex),
        "temperature": palette.get("temperature", 0.8),
        "humidity": palette.get("humidity", 0.4),
        "modifier": palette.get("modifier", "none"),
        "has_custom_grass": bool(palette.get("has_custom_grass", False)),
        "has_custom_foliage": bool(palette.get("has_custom_foliage", False)),
        "has_custom_dry_foliage": bool(palette.get("has_custom_dry_foliage", False)),
    }


BIOME_ENUM_ITEMS: list[tuple[str, str, str]] = [
    (
        k,
        v.get("name", k.replace("_", " ").title()),
        f"Temperature: {v.get('temperature', 0.8)}, Downfall: {v.get('humidity', 0.4)}",
    )
    for k, v in sorted(BIOME_PALETTES.items(), key=lambda item: (item[0] != "PLAINS", item[0]))
]


class BiomeResolver:
    """
    Parses block model JSONs (including parent inheritance chains) and texture names
    to automatically classify tint types and discover overlay layers for Minecraft blocks.
    """

    def __init__(self, models: dict[str, dict] | None = None, pack_root: str | Path | None = None):
        self.models: dict[str, dict] = dict(models) if models else {}
        self.models_by_stem: dict[str, dict] = {}
        self.overlay_pairs: dict[str, str] = dict(KNOWN_OVERLAY_PAIRS)
        self.texture_tint_categories: dict[str, str] = {}
        self.texture_hardcoded_colors: dict[str, str] = {}
        self._update_models_index()
        if pack_root:
            self.load_from_pack_root(pack_root)
        elif self.models:
            self._analyze_models()

    def _update_models_index(self):
        """Build stem and clean lookup indexes for loaded models."""
        self.models_by_stem.clear()
        for k, v in self.models.items():
            stem = k.split("/")[-1].replace(".json", "")
            self.models_by_stem[stem] = v

    def load_from_pack(self, pack: Any):
        """Load models from a ZipResourcePack instance (directory or zip)."""
        if hasattr(pack, "get_all_models"):
            self.models.update(pack.get_all_models())
            self._update_models_index()
            self._analyze_models()
        elif getattr(pack, "extract_dir", None) and Path(pack.extract_dir).exists():
            self.load_from_pack_root(pack.extract_dir)
        elif getattr(pack, "zip_path", None) and Path(pack.zip_path).exists():
            self.load_from_zip(pack.zip_path)

    def load_from_pack_stack(self, pack_stack: Any):
        """Load models across a full ResourcePackStack in correct priority order."""
        if hasattr(pack_stack, "get_all_models"):
            self.models.update(pack_stack.get_all_models())
            self._update_models_index()
            self._analyze_models()
        elif hasattr(pack_stack, "packs"):
            for pack in reversed(pack_stack.packs):
                self.load_from_pack(pack)


    def load_from_pack_root(self, pack_root: str | Path):
        """Scan and load models from an extracted resource pack root directory."""
        pack_path = Path(pack_root)
        if not pack_path.exists():
            return
        assets_dir = pack_path / "assets"
        if not assets_dir.exists():
            return
        for model_file in assets_dir.glob("*/models/**/*.json"):
            try:
                with open(model_file, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    if isinstance(data, dict):
                        rel_key = model_file.as_posix().split("/models/", 1)[-1].replace(".json", "").lower()
                        self.models[rel_key] = data
                        self.models[model_file.stem.lower()] = data
            except Exception:
                pass
        self._update_models_index()
        self._analyze_models()

    def load_from_zip(self, zip_path: str | Path):
        """Scan and load models directly from a .zip or .jar file."""
        zp = Path(zip_path)
        if not zp.exists() or not zipfile.is_zipfile(zp):
            return
        try:
            with zipfile.ZipFile(zp, "r") as z:
                for name in z.namelist():
                    if name.startswith("assets/") and "/models/" in name and name.endswith(".json"):
                        rel_key = name.split("/models/", 1)[1].replace(".json", "").lower()
                        try:
                            data = json.loads(z.read(name))
                            if isinstance(data, dict):
                                self.models[rel_key] = data
                                stem = rel_key.split("/")[-1]
                                self.models[stem] = data
                        except Exception:
                            pass
        except Exception:
            pass
        self._update_models_index()
        self._analyze_models()

    def set_models(self, models: dict[str, dict]):
        """Set or update loaded block models and re-analyze."""
        self.models = dict(models)
        self.overlay_pairs = dict(KNOWN_OVERLAY_PAIRS)
        self.texture_tint_categories.clear()
        self.texture_hardcoded_colors.clear()
        self._update_models_index()
        self._analyze_models()

    def _resolve_model(self, model_key: str, depth: int = 0) -> dict:
        """Recursively resolve parent model inheritance and merge textures/elements."""
        if depth > 10:
            return {}
        clean_k = model_key.removeprefix("minecraft:").lower()
        model_data = self.models.get(clean_k) or self.models_by_stem.get(clean_k.split("/")[-1])
        if not model_data or not isinstance(model_data, dict):
            return {}

        resolved = dict(model_data)
        parent = resolved.get("parent")
        if parent and isinstance(parent, str):
            parent_key = parent.removeprefix("minecraft:").lower()
            parent_resolved = self._resolve_model(parent_key, depth + 1)
            # Merge textures: child textures override parent
            merged_tex = dict(parent_resolved.get("textures", {})) if isinstance(parent_resolved.get("textures"), dict) else {}
            if isinstance(resolved.get("textures"), dict):
                merged_tex.update(resolved["textures"])
            resolved["textures"] = merged_tex
            # Inherit elements if child does not explicitly define its own
            if "elements" not in resolved and "elements" in parent_resolved:
                resolved["elements"] = parent_resolved["elements"]
        return resolved

    def _resolve_texture_var(self, tex_ref: str, textures_dict: dict) -> str:
        """Follow #variable reference chains in a model's textures dictionary."""
        seen = set()
        curr = tex_ref
        while isinstance(curr, str) and curr.startswith("#") and isinstance(textures_dict, dict):
            var_name = curr[1:]
            if var_name in seen:
                break
            seen.add(var_name)
            curr = textures_dict.get(var_name, "")
        if isinstance(curr, str) and not curr.startswith("#"):
            return curr.removeprefix("minecraft:block/").removeprefix("block/").removeprefix("minecraft:item/").removeprefix("item/").strip().lower()
        return ""

    def _analyze_models(self):
        """Analyze loaded model JSONs to discover overlay pairs, tint indexes, and custom textures."""
        for model_name in sorted(self.models.keys()):
            resolved_model = self._resolve_model(model_name)
            if not isinstance(resolved_model, dict):
                continue

            textures = resolved_model.get("textures", {})
            if isinstance(textures, dict):
                # Discover overlay pairs
                side_tex = self._resolve_texture_var(textures.get("side", ""), textures)
                overlay_tex = self._resolve_texture_var(textures.get("overlay", ""), textures)
                if side_tex and overlay_tex and side_tex != overlay_tex:
                    self.overlay_pairs[side_tex] = overlay_tex

                cross_tex = self._resolve_texture_var(textures.get("cross", ""), textures)
                cross_overlay = self._resolve_texture_var(textures.get("cross_overlay", ""), textures)
                if cross_tex and cross_overlay and cross_tex != cross_overlay:
                    self.overlay_pairs[cross_tex] = cross_overlay

            elements = resolved_model.get("elements")
            model_stem = model_name.lower().removeprefix("block/").removeprefix("models/block/").removeprefix("models/").split("/")[-1]

            if isinstance(elements, list):
                for elem in elements:
                    if not isinstance(elem, dict):
                        continue
                    faces = elem.get("faces", {})
                    if not isinstance(faces, dict):
                        continue
                    for f_name, f_data in faces.items():
                        if not isinstance(f_data, dict):
                            continue
                        tint_idx = f_data.get("tintindex")
                        if tint_idx is not None and tint_idx >= 0:
                            raw_tex = f_data.get("texture", "")
                            clean_tex = self._resolve_texture_var(raw_tex, textures) if isinstance(textures, dict) else ""
                            if clean_tex:
                                cat = classify_tint_category(clean_tex, block_name=model_stem, tint_index=tint_idx)
                                if cat != "none":
                                    self.texture_tint_categories[clean_tex] = cat
            else:
                cat = classify_tint_category("", block_name=model_stem)
                if cat == "foliage" and isinstance(textures, dict):
                    for tex_var, tex_path in textures.items():
                        clean_tex = self._resolve_texture_var(tex_path, textures)
                        if clean_tex:
                            self.texture_tint_categories[clean_tex] = cat

    def get_overlay_texture(self, texture_stem: str) -> Optional[str]:
        """Return the paired overlay texture stem for a given base texture stem, or None."""
        clean = texture_stem.lower().replace("block/", "")
        if ":" in clean:
            clean = clean.split(":", 1)[1]
        return self.overlay_pairs.get(clean)

    def get_tint_info(
        self,
        texture_name: str,
        block_name: Optional[str] = None,
        tint_index: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Determine full tint metadata for a texture stem / resource key.
        Returns dictionary with tint_type, tint_category, weights, and hardcoded colors.
        """
        clean = texture_name.lower().replace("block/", "")
        if ":" in clean:
            clean = clean.split(":", 1)[1]

        # 1. Check Hardcoded block tints
        if clean in HARDCODED_BLOCK_TINTS or (block_name and block_name in HARDCODED_BLOCK_TINTS):
            hex_col = HARDCODED_BLOCK_TINTS.get(clean) or HARDCODED_BLOCK_TINTS.get(block_name or "")
            linear_rgba = hex_to_linear_rgba(hex_col) if hex_col else (1.0, 1.0, 1.0, 1.0)
            return {
                "tint_type": TINT_TYPE_HARDCODED,
                "tint_category": "hardcoded",
                "tint_weight": 1.0,
                "base_tint_weight": 1.0,
                "overlay_tint_weight": 1.0,
                "has_overlay": False,
                "overlay_texture": None,
                "is_hardcoded": True,
                "hardcoded_color": linear_rgba,
                "hardcoded_hex": hex_col,
            }

        # 2. Check Overlays (e.g. grass_block_side has grass_block_side_overlay)
        overlay_stem = self.get_overlay_texture(clean)
        has_overlay = overlay_stem is not None

        # 3. Category classification (Prioritize discovered model textures, then block semantic, then stem)
        category = self.texture_tint_categories.get(clean)
        if not category or category == "none":
            category = classify_tint_category(clean, block_name=block_name, tint_index=tint_index)
        if category == "none" and overlay_stem:
            category = classify_tint_category(overlay_stem, block_name=block_name, tint_index=tint_index)

        if category == "grass":
            base_weight = 0.0 if has_overlay else 1.0
            return {
                "tint_type": TINT_TYPE_GRASS,
                "tint_category": "grass",
                "tint_weight": 1.0,
                "base_tint_weight": base_weight,
                "overlay_tint_weight": 1.0,
                "has_overlay": has_overlay,
                "overlay_texture": overlay_stem,
                "is_hardcoded": False,
                "hardcoded_color": None,
                "hardcoded_hex": None,
            }
        elif category == "foliage":
            return {
                "tint_type": TINT_TYPE_FOLIAGE,
                "tint_category": "foliage",
                "tint_weight": 1.0,
                "base_tint_weight": 1.0,
                "overlay_tint_weight": 1.0,
                "has_overlay": has_overlay,
                "overlay_texture": overlay_stem,
                "is_hardcoded": False,
                "hardcoded_color": None,
                "hardcoded_hex": None,
            }
        elif category == "dry_foliage":
            return {
                "tint_type": TINT_TYPE_DRY_FOLIAGE,
                "tint_category": "dry_foliage",
                "tint_weight": 1.0,
                "base_tint_weight": 1.0,
                "overlay_tint_weight": 1.0,
                "has_overlay": has_overlay,
                "overlay_texture": overlay_stem,
                "is_hardcoded": False,
                "hardcoded_color": None,
                "hardcoded_hex": None,
            }
        elif category == "water":
            return {
                "tint_type": TINT_TYPE_WATER,
                "tint_category": "water",
                "tint_weight": 1.0,
                "base_tint_weight": 1.0,
                "overlay_tint_weight": 1.0,
                "has_overlay": has_overlay,
                "overlay_texture": overlay_stem,
                "is_hardcoded": False,
                "hardcoded_color": None,
                "hardcoded_hex": None,
            }
        elif category == "hardcoded":
            hex_col = self.texture_hardcoded_colors.get(clean, HARDCODED_BLOCK_TINTS.get(clean, "#619961"))
            linear_rgba = hex_to_linear_rgba(hex_col)
            return {
                "tint_type": TINT_TYPE_HARDCODED,
                "tint_category": "hardcoded",
                "tint_weight": 1.0,
                "base_tint_weight": 1.0,
                "overlay_tint_weight": 1.0,
                "has_overlay": False,
                "overlay_texture": None,
                "is_hardcoded": True,
                "hardcoded_color": linear_rgba,
                "hardcoded_hex": hex_col,
            }

        # 4. Non-tinted default
        return {
            "tint_type": TINT_TYPE_NONE,
            "tint_category": "none",
            "tint_weight": 0.0,
            "base_tint_weight": 0.0,
            "overlay_tint_weight": 0.0,
            "has_overlay": False,
            "overlay_texture": None,
            "is_hardcoded": False,
            "hardcoded_color": None,
            "hardcoded_hex": None,
        }

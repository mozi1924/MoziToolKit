"""
Minecraft Biome Definitions, Tint Classification, and Block Model JSON Resolver.
Provides standard vanilla biome color palettes, hardcoded block colors,
and automatic overlay detection from block models.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Dict, Any, Tuple


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



# ---# Standard Biome Palettes
# Colors represent vanilla Minecraft defaults (hex sRGB).
BIOME_PALETTES: dict[str, dict[str, Any]] = {
    "PLAINS": {
        "name": "Plains",
        "grass": "#91BD59",
        "foliage": "#77AB2F",
        "water": "#3F76E4",
        "temperature": 0.8,
        "humidity": 0.4,
    },
    "FOREST": {
        "name": "Forest",
        "grass": "#79C05A",
        "foliage": "#59AE30",
        "water": "#3F76E4",
        "temperature": 0.7,
        "humidity": 0.8,
    },
    "BIRCH_FOREST": {
        "name": "Birch Forest",
        "grass": "#88BB67",
        "foliage": "#6BA941",
        "water": "#3F76E4",
        "temperature": 0.6,
        "humidity": 0.6,
    },
    "TAIGA": {
        "name": "Taiga",
        "grass": "#86B783",
        "foliage": "#68A55E",
        "water": "#3F76E4",
        "temperature": 0.25,
        "humidity": 0.8,
    },
    "OLD_GROWTH_TAIGA": {
        "name": "Old Growth Taiga",
        "grass": "#86B783",
        "foliage": "#68A55E",
        "water": "#3F76E4",
        "temperature": 0.3,
        "humidity": 0.8,
    },
    "SNOWY_PLAINS": {
        "name": "Snowy Plains",
        "grass": "#80B497",
        "foliage": "#60A17B",
        "water": "#3F76E4",
        "temperature": 0.0,
        "humidity": 0.5,
    },
    "SNOWY_TAIGA": {
        "name": "Snowy Taiga",
        "grass": "#80B497",
        "foliage": "#60A17B",
        "water": "#3F76E4",
        "temperature": -0.5,
        "humidity": 0.4,
    },
    "JUNGLE": {
        "name": "Jungle",
        "grass": "#59C93C",
        "foliage": "#30BB0B",
        "water": "#3F76E4",
        "temperature": 0.95,
        "humidity": 0.9,
    },
    "SPARSE_JUNGLE": {
        "name": "Sparse Jungle",
        "grass": "#64C73F",
        "foliage": "#3EB80F",
        "water": "#3F76E4",
        "temperature": 0.95,
        "humidity": 0.8,
    },
    "SAVANNA": {
        "name": "Savanna",
        "grass": "#BFB755",
        "foliage": "#AEA42A",
        "water": "#3F76E4",
        "temperature": 1.1,
        "humidity": 0.0,
    },
    "DESERT": {
        "name": "Desert",
        "grass": "#BFB755",
        "foliage": "#AEA42A",
        "water": "#3F76E4",
        "temperature": 2.0,
        "humidity": 0.0,
    },
    "BADLANDS": {
        "name": "Badlands",
        "grass": "#90814D",
        "foliage": "#90814D",
        "water": "#3F76E4",
        "temperature": 2.0,
        "humidity": 0.0,
    },
    "SWAMP": {
        "name": "Swamp",
        "grass": "#6A7039",
        "foliage": "#6A7039",
        "water": "#617B64",
        "temperature": 0.8,
        "humidity": 0.9,
    },
    "MANGROVE_SWAMP": {
        "name": "Mangrove Swamp",
        "grass": "#6A7039",
        "foliage": "#8DB127",
        "water": "#3A7A6A",
        "temperature": 0.8,
        "humidity": 0.9,
    },
    "DARK_FOREST": {
        "name": "Dark Forest",
        "grass": "#507A32",
        "foliage": "#507A32",
        "water": "#3F76E4",
        "temperature": 0.7,
        "humidity": 0.8,
    },
    "CHERRY_GROVE": {
        "name": "Cherry Grove",
        "grass": "#B6DB63",
        "foliage": "#B6DB63",
        "water": "#5DB7EF",
        "temperature": 0.5,
        "humidity": 0.8,
    },
    "MEADOW": {
        "name": "Meadow",
        "grass": "#83BB6D",
        "foliage": "#63A948",
        "water": "#0E4ECF",
        "temperature": 0.5,
        "humidity": 0.8,
    },
    "WARM_OCEAN": {
        "name": "Warm Ocean",
        "grass": "#91BD59",
        "foliage": "#77AB2F",
        "water": "#43D5EE",
        "temperature": 0.5,
        "humidity": 0.5,
    },
    "LUKEWARM_OCEAN": {
        "name": "Lukewarm Ocean",
        "grass": "#91BD59",
        "foliage": "#77AB2F",
        "water": "#45ADF2",
        "temperature": 0.5,
        "humidity": 0.5,
    },
    "COLD_OCEAN": {
        "name": "Cold Ocean",
        "grass": "#91BD59",
        "foliage": "#77AB2F",
        "water": "#3D57D6",
        "temperature": 0.5,
        "humidity": 0.5,
    },
    "FROZEN_OCEAN": {
        "name": "Frozen Ocean",
        "grass": "#91BD59",
        "foliage": "#77AB2F",
        "water": "#3938C9",
        "temperature": 0.0,
        "humidity": 0.5,
    },
    "THE_END": {
        "name": "The End",
        "grass": "#8AB689",
        "foliage": "#68A55E",
        "water": "#62529E",
        "temperature": 0.5,
        "humidity": 0.5,
    },
}

# Hardcoded block-specific tints (independent of biome, or special formula)
HARDCODED_BLOCK_TINTS: dict[str, str] = {
    "spruce_leaves": "#619961",
    "birch_leaves": "#80A755",
    "lily_pad": "#208030",
    "attached_melon_stem": "#E0C71C",
    "attached_pumpkin_stem": "#E0C71C",
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
    # Foliage
    "oak_leaves": [("foliage", 1.0)],
    "jungle_leaves": [("foliage", 1.0)],
    "acacia_leaves": [("foliage", 1.0)],
    "dark_oak_leaves": [("foliage", 1.0)],
    "vine": [("foliage", 1.0)],
    "mangrove_leaves": [("foliage", 1.0)],
    "leaf_litter": [("foliage", 1.0)],
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


def get_hardcoded_block_tint_rgba(name: str, default: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)) -> tuple[float, float, float, float]:
    """Return sRGB RGBA tuple for a hardcoded block name."""
    clean = name.removeprefix("minecraft:").removeprefix("block/")
    hex_str = HARDCODED_BLOCK_TINTS.get(clean)
    if hex_str:
        return hex_to_rgba(hex_str)
    return default


def get_hardcoded_block_tint_linear(name: str, default: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)) -> tuple[float, float, float, float]:
    """Return Linear RGBA tuple for a hardcoded block name."""
    clean = name.removeprefix("minecraft:").removeprefix("block/")
    hex_str = HARDCODED_BLOCK_TINTS.get(clean)
    if hex_str:
        return hex_to_linear_rgba(hex_str)
    return default

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
    "pink_petals",
    "wildflowers",
})

KNOWN_FOLIAGE_STEMS = frozenset({
    "oak_leaves",
    "jungle_leaves",
    "acacia_leaves",
    "dark_oak_leaves",
    "vine",
    "mangrove_leaves",
    "leaf_litter",
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
    'grass', 'foliage', 'water', 'hardcoded', or 'none'.
    Respects BlockColors semantic registration and face tintindex.
    """
    if not clean_stem and not block_name:
        return "none"

    # 1. Check explicit block-level registration if block_name is provided
    if block_name:
        clean_block = block_name.lower().removeprefix("minecraft:").removeprefix("block/")
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
            # When tint_index is not provided, return first non-none category
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
    if stem_norm in KNOWN_WATER_STEMS:
        return "water"

    # 3. Heuristic fallback for custom models (e.g. 05m_oak_leaves_cube, custom_leaves, custom_water)
    if "leaves" in stem_norm:
        if "spruce" in stem_norm:
            return "hardcoded"
        if "birch" in stem_norm:
            return "hardcoded"
        if any(w in stem_norm for w in ("cherry", "azalea", "pale_oak")):
            return "none"
        return "foliage"

    if "water" in stem_norm:
        return "water"

    if any(stem_norm.endswith(w) for w in ("_grass", "_fern", "_vine")):
        return "grass"

    return "none"


class BiomeResolver:
    """
    Parses block model JSONs and texture names to classify tint types
    and discover overlay layers for Minecraft blocks.
    """

    def __init__(self, models: dict[str, dict] | None = None, pack_root: str | Path | None = None):
        self.models = dict(models) if models else {}
        self.overlay_pairs: dict[str, str] = dict(KNOWN_OVERLAY_PAIRS)
        self.texture_tint_categories: dict[str, str] = {}
        self.texture_hardcoded_colors: dict[str, str] = {}
        if pack_root:
            self.load_from_pack_root(pack_root)
        elif self.models:
            self._analyze_models()

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
                        self.models[model_file.stem.lower()] = data
            except Exception:
                pass
        self._analyze_models()

    def set_models(self, models: dict[str, dict]):
        """Set or update loaded block models and re-analyze."""
        self.models = models
        self.overlay_pairs = dict(KNOWN_OVERLAY_PAIRS)
        self.texture_tint_categories.clear()
        self.texture_hardcoded_colors.clear()
        self._analyze_models()

    def _analyze_models(self):
        """Analyze loaded model JSONs to discover overlay pairs, tint indexes, and custom textures."""
        for model_name, model_data in self.models.items():
            if not isinstance(model_data, dict):
                continue

            textures = model_data.get("textures", {})
            if isinstance(textures, dict):
                # Discover overlay pairs: e.g. "side" + "overlay"
                side_tex = textures.get("side", "")
                overlay_tex = textures.get("overlay", "")
                if side_tex and overlay_tex and isinstance(side_tex, str) and isinstance(overlay_tex, str):
                    clean_side = side_tex.replace("minecraft:block/", "").replace("block/", "").lower()
                    clean_overlay = overlay_tex.replace("minecraft:block/", "").replace("block/", "").lower()
                    if clean_side and clean_overlay and clean_side != clean_overlay:
                        self.overlay_pairs[clean_side] = clean_overlay

            # Discover tint association for custom model textures
            elements = model_data.get("elements")
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
                            tex_ref = f_data.get("texture", "")
                            while isinstance(tex_ref, str) and tex_ref.startswith("#") and isinstance(textures, dict):
                                tex_ref = textures.get(tex_ref[1:], "")
                            if isinstance(tex_ref, str) and tex_ref:
                                clean_tex = tex_ref.replace("minecraft:block/", "").replace("block/", "").lower()
                                if ":" in clean_tex:
                                    clean_tex = clean_tex.split(":", 1)[1]
                                model_stem = model_name.lower().removeprefix("block/").removeprefix("models/block/")
                                cat = classify_tint_category(clean_tex, block_name=model_stem, tint_index=tint_idx)
                                if cat != "none":
                                    self.texture_tint_categories[clean_tex] = cat
            else:
                model_stem = model_name.lower().removeprefix("block/").removeprefix("models/block/")
                cat = classify_tint_category("", block_name=model_stem)
                if cat == "foliage" and isinstance(textures, dict):
                    for tex_var, tex_path in textures.items():
                        if isinstance(tex_path, str) and not tex_path.startswith("#"):
                            clean_tex = tex_path.replace("minecraft:block/", "").replace("block/", "").lower()
                            if ":" in clean_tex:
                                clean_tex = clean_tex.split(":", 1)[1]
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




def get_biome_colors(preset_name: str = "PLAINS") -> dict[str, Any]:
    """Return sRGB and Linear RGBA color dict for a given biome preset."""
    key = preset_name.upper()
    palette = BIOME_PALETTES.get(key, BIOME_PALETTES["PLAINS"])
    return {
        "name": palette["name"],
        "grass_hex": palette["grass"],
        "grass_linear": hex_to_linear_rgba(palette["grass"]),
        "foliage_hex": palette["foliage"],
        "foliage_linear": hex_to_linear_rgba(palette["foliage"]),
        "water_hex": palette["water"],
        "water_linear": hex_to_linear_rgba(palette["water"]),
        "temperature": palette.get("temperature", 0.8),
        "humidity": palette.get("humidity", 0.4),
    }

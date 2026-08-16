"""
Minecraft Biome Definitions, Tint Classification, and Block Model JSON Resolver.
Provides standard vanilla biome color palettes, hardcoded block colors,
and automatic overlay / tint detection from block models.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Dict, Any, Tuple


# --- Color Conversion Utilities ---

def hex_to_rgb(hex_str: str) -> tuple[float, float, float]:
    """Convert hex color string (e.g. '#91BD59' or '91BD59') to sRGB float tuple (0..1)."""
    clean = hex_str.strip().lstrip("#")
    if len(clean) == 6:
        r = int(clean[0:2], 16) / 255.0
        g = int(clean[2:4], 16) / 255.0
        b = int(clean[4:6], 16) / 255.0
        return (r, g, b)
    elif len(clean) == 8:
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
    r, g, b = hex_to_rgb(hex_str)
    return (r, g, b, alpha)


def hex_to_linear_rgba(hex_str: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    """Convert hex color string to Linear RGBA tuple for Blender shaders."""
    lr, lg, lb = hex_to_linear_rgb(hex_str)
    return (lr, lg, lb, alpha)


# --- Standard Biome Palettes ---
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

# Known tint classification keywords / stems
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
})

KNOWN_WATER_STEMS = frozenset({
    "water_still",
    "water_flow",
    "water_overlay",
})


class BiomeResolver:
    """
    Parses block model JSONs and texture names to classify tint types
    and discover overlay layers for Minecraft blocks.
    """

    def __init__(self, models: dict[str, dict] | None = None, pack_root: str | Path | None = None):
        self.models = dict(models) if models else {}
        self.overlay_pairs: dict[str, str] = dict(KNOWN_OVERLAY_PAIRS)
        self.tint_cache: dict[str, dict[str, Any]] = {}
        if pack_root:
            self.load_from_pack_root(pack_root)
        elif self.models:
            self._analyze_models()

    def load_from_pack_root(self, pack_root: str | Path):
        """Scan and load block models from an extracted resource pack root directory."""
        pack_path = Path(pack_root)
        if not pack_path.exists():
            return
        for model_file in pack_path.glob("assets/*/models/block/*.json"):
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
        self.tint_cache.clear()
        self._analyze_models()

    def _analyze_models(self):
        """Analyze loaded model JSONs to discover overlay pairs and tint indexes."""
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

            # Analyze elements for tintindex
            elements = model_data.get("elements", [])
            if isinstance(elements, list):
                for elem in elements:
                    if not isinstance(elem, dict):
                        continue
                    faces = elem.get("faces", {})
                    if isinstance(faces, dict):
                        for face_data in faces.values():
                            if isinstance(face_data, dict) and "tintindex" in face_data:
                                tex_ref = face_data.get("texture", "")
                                if isinstance(tex_ref, str):
                                    resolved_tex = self._resolve_tex_ref(tex_ref, textures)
                                    if resolved_tex:
                                        clean_tex = resolved_tex.replace("minecraft:block/", "").replace("block/", "").lower()
                                        if clean_tex not in self.tint_cache:
                                            self.tint_cache[clean_tex] = {
                                                "has_tint": True,
                                                "tintindex": face_data.get("tintindex", 0),
                                            }

    def _resolve_tex_ref(self, ref: str, textures: dict) -> str:
        """Resolve a texture reference like '#top' or direct texture string."""
        if not ref:
            return ""
        if ref.startswith("#"):
            key = ref[1:]
            return str(textures.get(key, ""))
        return ref

    def get_overlay_texture(self, texture_stem: str) -> Optional[str]:
        """Return the paired overlay texture stem for a given base texture stem, or None."""
        clean = texture_stem.lower().replace("block/", "")
        if ":" in clean:
            clean = clean.split(":", 1)[1]
        return self.overlay_pairs.get(clean)

    def get_tint_info(self, texture_name: str) -> dict[str, Any]:
        """
        Determine full tint metadata for a texture stem / resource key.
        Returns dictionary:
        {
            "tint_type": int (0=None, 1=Grass, 2=Foliage, 3=Water, 4=Hardcoded),
            "tint_category": str ("grass", "foliage", "water", "hardcoded", "none"),
            "tint_weight": float (0.0 or 1.0),
            "has_overlay": bool,
            "overlay_texture": str | None,
            "is_hardcoded": bool,
            "hardcoded_color": tuple[float, float, float, float] | None,
            "hardcoded_hex": str | None,
        }
        """
        clean = texture_name.lower().replace("block/", "")
        if ":" in clean:
            clean = clean.split(":", 1)[1]

        # 1. Check Hardcoded block tints
        if clean in HARDCODED_BLOCK_TINTS:
            hex_col = HARDCODED_BLOCK_TINTS[clean]
            linear_rgba = hex_to_linear_rgba(hex_col)
            return {
                "tint_type": TINT_TYPE_HARDCODED,
                "tint_category": "hardcoded",
                "tint_weight": 1.0,
                "has_overlay": False,
                "overlay_texture": None,
                "is_hardcoded": True,
                "hardcoded_color": linear_rgba,
                "hardcoded_hex": hex_col,
            }

        # 2. Check Overlays (e.g. grass_block_side has grass_block_side_overlay)
        overlay_stem = self.get_overlay_texture(clean)
        has_overlay = overlay_stem is not None

        # 3. Check Known Grass category
        if clean in KNOWN_GRASS_STEMS or clean.startswith("grass_") or "grass" in clean or clean.startswith("fern"):
            # Note: grass_block_side itself has overlay fringe; the base dirt side is not tinted, the overlay is tinted.
            base_tint_weight = 0.0 if has_overlay else 1.0
            return {
                "tint_type": TINT_TYPE_GRASS,
                "tint_category": "grass",
                "tint_weight": base_tint_weight,
                "has_overlay": has_overlay,
                "overlay_texture": overlay_stem,
                "is_hardcoded": False,
                "hardcoded_color": None,
                "hardcoded_hex": None,
            }

        # 4. Check Known Foliage category
        if clean in KNOWN_FOLIAGE_STEMS or "leaves" in clean or "vine" in clean:
            return {
                "tint_type": TINT_TYPE_FOLIAGE,
                "tint_category": "foliage",
                "tint_weight": 1.0,
                "has_overlay": has_overlay,
                "overlay_texture": overlay_stem,
                "is_hardcoded": False,
                "hardcoded_color": None,
                "hardcoded_hex": None,
            }

        # 5. Check Known Water category
        if clean in KNOWN_WATER_STEMS or "water" in clean:
            return {
                "tint_type": TINT_TYPE_WATER,
                "tint_category": "water",
                "tint_weight": 1.0,
                "has_overlay": has_overlay,
                "overlay_texture": overlay_stem,
                "is_hardcoded": False,
                "hardcoded_color": None,
                "hardcoded_hex": None,
            }

        # 6. Check Model JSON tint cache
        if clean in self.tint_cache:
            return {
                "tint_type": TINT_TYPE_GRASS,
                "tint_category": "grass",
                "tint_weight": 1.0,
                "has_overlay": has_overlay,
                "overlay_texture": overlay_stem,
                "is_hardcoded": False,
                "hardcoded_color": None,
                "hardcoded_hex": None,
            }

        # 7. Non-tinted default
        return {
            "tint_type": TINT_TYPE_NONE,
            "tint_category": "none",
            "tint_weight": 0.0,
            "has_overlay": has_overlay,
            "overlay_texture": overlay_stem,
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
